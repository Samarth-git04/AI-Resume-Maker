import re

from backend.services.resume_text import (
    clean_resume_text,
    comparison_text,
)


MAJOR_SECTIONS = {
    "HIGHLIGHTS",
    "EXPERIENCE",
    "KEY PROJECTS",
    "PROJECTS",
    "CERTIFICATIONS",
    "KEY SKILLS",
    "SKILLS",
    "EDUCATION",
}


KNOWN_PROJECT_TITLES = {
    "FOOTBALL MATCH PREDICTION ANALYSIS",
    "CYCLISTIC BIKE SHARE ANALYSIS",
    "BELLABEAT FITNESS ANALYSIS",
    "MELBOURNE HOUSING MARKET ANALYSIS",
    "CONTOSO DATABASE ANALYSIS",
    "VICTORIA STATE BUDGET 2025–2026 ANALYSIS",
    "VICTORIA STATE BUDGET 2025-2026 ANALYSIS",
    "BLACKMORES HR DASHBOARD",
    "WOOLWORTHS REWARDS DASHBOARD",
    "NETFLIX VIEWING & RECOMMENDATIONS ANALYSIS",
    "YOUTUBE CLONE – FRONTEND DEVELOPMENT",
    "YOUTUBE CLONE - FRONTEND DEVELOPMENT",
}


def clean_heading(text: str) -> str:
    return re.sub(
        r"[\s:]+$",
        "",
        clean_resume_text(text),
    ).upper()


def is_major_heading(text: str) -> bool:
    return clean_heading(text) in MAJOR_SECTIONS


def _format_type(format_lookup: dict, paragraph_id: str) -> str:
    return format_lookup.get(paragraph_id, {}).get("t", "")


def _is_bullet(text: str, element_type: str) -> bool:
    return element_type == "bullet" or bool(
        re.match(
            r"^\s*[•●▪◦‣∙·\uf0b7\-]\s+",
            text,
        )
    )


def _is_technology_line(text: str) -> bool:
    return bool(
        re.match(
            r"^\s*(technologies|technology|tools|tech stack|technology stack)\s*:",
            text,
            re.I,
        )
    )


def _is_project_title(text: str, element_type: str) -> bool:
    normalized = clean_heading(text)

    normalized = re.sub(
        r"^\s*\d+[\.\)]\s*",
        "",
        normalized,
    )

    if normalized in KNOWN_PROJECT_TITLES:
        return True

    if _is_technology_line(text):
        return False

    return element_type == "subheader"


def build_resume_structure(
    paragraphs: list,
    formatting: dict,
) -> dict:

    format_lookup = {
        item["id"]: item
        for item in formatting.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id")
    }

    sections = []
    current_section = None

    project_groups = []
    current_project = None

    profile_id = None
    profile_comparison = None

    seen_highlights_text = set()

    records = []

    for index, paragraph in enumerate(paragraphs):

        if not isinstance(paragraph, dict):
            raise ValueError(
                f"Invalid paragraph at position {index}."
            )

        paragraph_id = (
            paragraph.get("id")
            or paragraph.get("paragraph_id")
        )

        text = clean_resume_text(
            paragraph.get("text", "")
        )

        if not paragraph_id:
            raise ValueError(
                f"Paragraph at position {index} has no ID."
            )

        element_type = _format_type(
            format_lookup,
            paragraph_id,
        )

        normalized = comparison_text(text)

        is_bullet = _is_bullet(
            text,
            element_type,
        )

        # The first three paragraphs are the fixed header.
        if index < 3:
            role = "header"

        # Major resume sections.
        elif is_major_heading(text):

            role = "section_heading"

            current_section = clean_heading(text)

            sections.append({
                "name": current_section,
                "paragraph_id": paragraph_id,
            })

            current_project = None

        # Project titles.
        elif (
            current_section == "KEY PROJECTS"
            and _is_project_title(text, element_type)
        ):

            role = "project_title"

            current_project = {
                "title": text,
                "title_id": paragraph_id,
                "paragraph_ids": [paragraph_id],
            }

            project_groups.append(current_project)

        # Key Achievements heading.
        elif (
            current_section == "HIGHLIGHTS"
            and clean_heading(text) == "KEY ACHIEVEMENTS"
        ):

            role = "subheading"

        # Profile and duplicate-profile detection.
        elif (
            current_section == "HIGHLIGHTS"
            and not is_bullet
        ):

            if profile_id is None:

                role = "profile"

                profile_id = paragraph_id
                profile_comparison = normalized

                seen_highlights_text.add(normalized)

            elif normalized and (
                normalized == profile_comparison
                or normalized in seen_highlights_text
            ):

                role = "duplicate_profile"

            else:

                role = "content"

                if normalized:
                    seen_highlights_text.add(normalized)

        # Content belonging to the current project.
        elif (
            current_section == "KEY PROJECTS"
            and current_project is not None
        ):

            if _is_technology_line(text):
                role = "project_metadata"
            else:
                role = "project_content"

            current_project["paragraph_ids"].append(
                paragraph_id
            )

        elif element_type == "subheader":

            role = "subheading"

        elif is_bullet:

            role = "bullet"

        else:

            role = "content"

        # Ensure all project paragraphs belong to their project group.
        if (
            current_section == "KEY PROJECTS"
            and current_project is not None
            and paragraph_id not in current_project["paragraph_ids"]
        ):

            current_project["paragraph_ids"].append(
                paragraph_id
            )

        records.append({
            "id": paragraph_id,
            "text": text,
            "section": current_section,
            "role": role,
            "is_bullet": is_bullet,
            "format_type": element_type,
        })

    structural_roles = {
        "header",
        "section_heading",
        "subheading",
        "project_title",
        "project_metadata",
        "profile",
        "duplicate_profile",
    }

    structural_ids = {
        item["id"]
        for item in records
        if item["role"] in structural_roles
    }

    editable_ids = {
        item["id"]
        for item in records
        if item["role"] in {
            "bullet",
            "project_content",
            "content",
        }
    }

    return {
        "records": records,
        "sections": sections,
        "projects": project_groups,
        "profile_id": profile_id,
        "structural_ids": structural_ids,
        "editable_ids": editable_ids,
    }