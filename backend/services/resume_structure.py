import re


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
    return re.sub(r"[\s:]+$", "", text.strip()).upper()


def is_major_heading(text: str) -> bool:
    return clean_heading(text) in MAJOR_SECTIONS


def _format_type(format_lookup: dict, paragraph_id: str) -> str:
    return format_lookup.get(paragraph_id, {}).get("t", "")


def _is_bullet(text: str, element_type: str) -> bool:
    return element_type == "bullet" or bool(
        re.match(r"^\s*[•●▪◦‣\-]\s+", text)
    )


def _is_project_title(text: str, element_type: str) -> bool:
    normalized = clean_heading(text)
    if normalized in KNOWN_PROJECT_TITLES:
        return True
    return element_type == "subheader"


def build_resume_structure(paragraphs: list, formatting: dict) -> dict:
    """Classify source paragraphs without changing their order or content."""
    format_lookup = {
        item["id"]: item
        for item in formatting.get("paragraphs", [])
    }

    sections = []
    current_section = None
    project_groups = []
    current_project = None
    profile_id = None
    key_achievements_seen = False

    records = []
    for index, paragraph in enumerate(paragraphs):
        pid = paragraph.get("id") or paragraph.get("paragraph_id")
        text = paragraph.get("text", "").strip()

        if not pid:
            raise ValueError(
                f"Paragraph at position {index} has no ID."
            )

        element_type = _format_type(format_lookup, pid)

        if index < 3:
            role = "header"
        elif is_major_heading(text):
            role = "section_heading"
            current_section = clean_heading(text)
            sections.append({"name": current_section, "paragraph_id": pid})
            current_project = None
            key_achievements_seen = False
        elif current_section == "KEY PROJECTS" and (
            clean_heading(text) in KNOWN_PROJECT_TITLES
            or (current_project is None and element_type == "subheader")
        ):
            role = "project_title"
            current_project = {
                "title": text,
                "title_id": pid,
                "paragraph_ids": [pid],
            }
            project_groups.append(current_project)
        elif current_section == "HIGHLIGHTS" and clean_heading(text) in {
            "KEY ACHIEVEMENTS", "KEY ACHIEVEMENTS:"
        }:
            role = "subheading"
            key_achievements_seen = True
        elif current_section == "HIGHLIGHTS" and profile_id is None and not _is_bullet(text, element_type):
            role = "profile"
            profile_id = pid
        elif current_section == "KEY PROJECTS" and current_project is not None:
            if re.match(r"^(technologies|technology|tools|tech stack|technology stack)\s*:", text, re.I):
                role = "project_metadata"
            else:
                role = "project_content"
            current_project["paragraph_ids"].append(pid)
        elif element_type == "subheader":
            role = "subheading"
        elif _is_bullet(text, element_type):
            role = "bullet"
        else:
            role = "content"

        if current_section == "KEY PROJECTS" and current_project is not None:
            if pid not in current_project["paragraph_ids"]:
                current_project["paragraph_ids"].append(pid)

        records.append({
            "id": pid,
            "text": text,
            "section": current_section,
            "role": role,
            "is_bullet": _is_bullet(text, element_type),
            "format_type": element_type,
        })

    # A project heading that was not detected through its style can still be
    # identified by the known-title list above. Projects are retained as groups.
    structural_roles = {
        "header", "section_heading", "subheading", "project_title",
        "project_metadata", "profile"
    }
    structural_ids = {
        item["id"] for item in records if item["role"] in structural_roles
    }

    editable_ids = set()
    for item in records:
        if item["role"] in {"bullet", "project_content"}:
            editable_ids.add(item["id"])

    return {
        "records": records,
        "sections": sections,
        "projects": project_groups,
        "profile_id": profile_id,
        "structural_ids": structural_ids,
        "editable_ids": editable_ids,
    }
