import re

from backend.services.resume_text import clean_resume_text


SECTION_ALIASES = {
    "SUMMARY": "SUMMARY",
    "PROFILE": "SUMMARY",
    "PROFESSIONAL SUMMARY": "SUMMARY",
    "CAREER SUMMARY": "SUMMARY",
    "HIGHLIGHTS": "HIGHLIGHTS",
    "KEY HIGHLIGHTS": "HIGHLIGHTS",
    "EXPERIENCE": "EXPERIENCE",
    "WORK EXPERIENCE": "EXPERIENCE",
    "PROFESSIONAL EXPERIENCE": "EXPERIENCE",
    "EMPLOYMENT HISTORY": "EXPERIENCE",
    "CAREER HISTORY": "EXPERIENCE",
    "PROJECTS": "PROJECTS",
    "KEY PROJECTS": "PROJECTS",
    "PERSONAL PROJECTS": "PROJECTS",
    "ACADEMIC PROJECTS": "PROJECTS",
    "SELECTED PROJECTS": "PROJECTS",
    "TECHNICAL PROJECTS": "PROJECTS",
    "SKILLS": "SKILLS",
    "KEY SKILLS": "SKILLS",
    "TECHNICAL SKILLS": "SKILLS",
    "CORE SKILLS": "SKILLS",
    "TECHNOLOGIES": "SKILLS",
    "CERTIFICATIONS": "CERTIFICATIONS",
    "CERTIFICATES": "CERTIFICATIONS",
    "EDUCATION": "EDUCATION",
    "ACADEMIC BACKGROUND": "EDUCATION",
    "QUALIFICATIONS": "EDUCATION",
    "AWARDS": "AWARDS",
    "ACHIEVEMENTS": "AWARDS",
    "PUBLICATIONS": "PUBLICATIONS",
    "VOLUNTEERING": "VOLUNTEERING",
    "VOLUNTEER EXPERIENCE": "VOLUNTEERING",
}


def clean_heading(text):
    text = clean_resume_text(text).upper()
    text = re.sub(r"^[\s:|]+|[\s:|]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(".:")


def canonical_section(text):
    return SECTION_ALIASES.get(clean_heading(text))


def is_major_heading(text):
    return canonical_section(text) is not None


def _is_bullet(text, element_type):
    return (
        element_type == "bullet"
        or bool(re.match(r"^\s*[•●▪◦‣∙·\-]\s+", text))
    )


def _is_metadata(text):
    return bool(re.match(
        r"^\s*(technologies|technology|tools|tech stack|"
        r"technology stack|tools used|stack)\s*:",
        text,
        re.IGNORECASE,
    ))


def _looks_like_project_title(text, element_type, is_bullet):
    if not text or is_bullet or _is_metadata(text):
        return False

    if element_type in {"subheader", "heading", "title"}:
        return True

    words = text.split()

    if len(words) > 10 or re.search(r"[.!?]$", text):
        return False

    action_words = (
        "developed", "built", "created", "analysed", "analyzed",
        "implemented", "designed", "utilised", "utilized",
        "managed", "improved", "responsible",
    )

    return (
        len(words) <= 8
        and not any(word in text.lower() for word in action_words)
    )


def _looks_like_role_heading(text, element_type):
    if element_type in {"subheader", "heading", "title"}:
        return True

    return (
        len(text.split()) <= 12
        and bool(re.search(
            r"\b(19|20)\d{2}\b|\b(present|current)\b",
            text,
            re.IGNORECASE,
        ))
    )


def build_resume_structure(paragraphs, formatting):
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("Resume paragraphs are missing or invalid.")

    format_lookup = {
        item["id"]: item
        for item in formatting.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id")
    }

    records = []
    sections = []
    projects = []

    current_section = None
    current_project = None
    profile_id = None
    seen_ids = set()

    for index, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, dict):
            raise ValueError(f"Invalid paragraph at position {index}.")

        paragraph_id = paragraph.get("id") or paragraph.get("paragraph_id")
        text = clean_resume_text(paragraph.get("text", ""))

        if not paragraph_id:
            raise ValueError(f"Paragraph {index} has no ID.")

        if paragraph_id in seen_ids:
            raise ValueError(f"Duplicate paragraph ID: {paragraph_id}")

        seen_ids.add(paragraph_id)

        if not text:
            continue

        element_type = format_lookup.get(
            paragraph_id, {}
        ).get("t", "")

        bullet = _is_bullet(text, element_type)
        section_heading = canonical_section(text)

        if section_heading:
            role = "section_heading"
            current_section = section_heading
            current_project = None

            sections.append({
                "name": current_section,
                "paragraph_id": paragraph_id,
            })

        elif (
            current_section == "PROJECTS"
            and _looks_like_project_title(text, element_type, bullet)
        ):
            role = "project_title"

            current_project = {
                "title": text,
                "title_id": paragraph_id,
                "paragraph_ids": [paragraph_id],
                "content_ids": [],
            }

            projects.append(current_project)

        elif current_section == "PROJECTS" and current_project:
            role = (
                "project_metadata"
                if _is_metadata(text)
                else "project_content"
            )

            current_project["paragraph_ids"].append(paragraph_id)

            if role == "project_content":
                current_project["content_ids"].append(paragraph_id)

        elif (
            current_section == "HIGHLIGHTS"
            and clean_heading(text) == "KEY ACHIEVEMENTS"
        ):
            role = "subheading"

        elif current_section == "EXPERIENCE":
            if bullet:
                role = "bullet"
            elif _looks_like_role_heading(text, element_type):
                role = "subheading"
            else:
                role = "content"

        elif bullet:
            role = "bullet"

        elif element_type in {"subheader", "heading", "title"}:
            role = "subheading"

        else:
            role = "content"

        if (
            current_section == "SUMMARY"
            and role == "content"
            and profile_id is None
        ):
            profile_id = paragraph_id
            role = "profile"

        records.append({
            "id": paragraph_id,
            "text": text,
            "section": current_section,
            "role": role,
            "is_bullet": bullet,
            "format_type": element_type,
        })

    # Some resumes place the profile directly below the contact header
    # without a dedicated SUMMARY heading.
    if profile_id is None:
        for record in records:
            if (
                record["role"] == "content"
                and record["section"] not in {
                    "EXPERIENCE",
                    "PROJECTS",
                    "EDUCATION",
                    "CERTIFICATIONS",
                    "SKILLS",
                    "AWARDS",
                }
                and len(record["text"].split()) >= 20
            ):
                profile_id = record["id"]
                record["role"] = "profile"
                break

    structural_roles = {
        "section_heading",
        "subheading",
        "project_title",
        "project_metadata",
        "profile",
    }

    editable_roles = {
        "bullet",
        "content",
        "project_content",
    }

    return {
        "records": records,
        "sections": sections,
        "projects": projects,
        "profile_id": profile_id,
        "structural_ids": {
            item["id"]
            for item in records
            if item["role"] in structural_roles
        },
        "editable_ids": {
            item["id"]
            for item in records
            if item["role"] in editable_roles
        },
    }