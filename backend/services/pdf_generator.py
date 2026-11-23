import json
import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from backend.database.models import (
    ExtractedResume,
    ProcessedResume,
    ResumeFormatting,
)

from backend.services.resume_structure import (
    build_resume_structure,
    clean_heading,
    is_major_heading,
)

from backend.services.resume_text import (
    clean_resume_text,
    comparison_text,
    strip_leading_bullet_markers,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "generated"


SKILL_LABELS = (
    "Programming & Query",
    "Data Analytics & BI",
    "AI & Data Engineering",
    "Frontend Development",
    "Backend Development",
    "Cloud & Version Control",
    "Tools & Methodologies",
    "Professional Skills",
)


def load_json(data):

    if isinstance(data, str):

        try:
            return json.loads(data)

        except json.JSONDecodeError as error:

            raise ValueError(
                "Stored resume JSON is invalid."
            ) from error

    return data


def load_resume_data(db, resume_id):

    extracted = (
        db.query(ExtractedResume)
        .filter(
            ExtractedResume.resume_id == resume_id
        )
        .order_by(
            ExtractedResume.id.desc()
        )
        .first()
    )

    formatting = (
        db.query(ResumeFormatting)
        .filter(
            ResumeFormatting.resume_id == resume_id
        )
        .first()
    )

    if (
        not extracted
        or not formatting
        or not extracted.extracted_data
    ):

        raise ValueError(
            "Resume data or formatting not found."
        )

    paragraphs = load_json(
        extracted.extracted_data
    )

    if not isinstance(paragraphs, list):

        raise ValueError(
            "Extracted resume paragraphs are invalid."
        )

    cleaned_paragraphs = []

    for index, item in enumerate(paragraphs):

        if not isinstance(item, dict):

            raise ValueError(
                f"Invalid extracted paragraph at position {index}."
            )

        paragraph_id = (
            item.get("id")
            or item.get("paragraph_id")
        )

        text = clean_resume_text(
            item.get("text", "")
        )

        if not paragraph_id:

            raise ValueError(
                f"Extracted paragraph at position {index} has no ID."
            )

        if not text:
            continue

        cleaned_paragraphs.append({
            **item,
            "id": paragraph_id,
            "text": text,
        })

    return {
        "paragraphs": cleaned_paragraphs,
        "formatting": formatting.formatting_data or {},
    }


def _format_lookup(formatting_data):

    paragraph_lookup = {
        item["id"]: item
        for item in formatting_data.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id")
    }

    definitions = formatting_data.get("formats", {})

    return paragraph_lookup, definitions


def _apply_layout(paragraph, format_data):

    if not format_data:
        return

    paragraph_format = paragraph.paragraph_format

    if "sb" in format_data:
        paragraph_format.space_before = Pt(
            format_data["sb"]
        )

    if "sa" in format_data:
        paragraph_format.space_after = Pt(
            format_data["sa"]
        )

    if "li" in format_data:
        paragraph_format.left_indent = Inches(
            format_data["li"]
        )

    if "ri" in format_data:
        paragraph_format.right_indent = Inches(
            format_data["ri"]
        )


def _configure_document(document):

    section = document.sections[0]

    section.top_margin = Inches(0.42)
    section.bottom_margin = Inches(0.42)
    section.left_margin = Inches(0.58)
    section.right_margin = Inches(0.58)

    normal = document.styles["Normal"]

    normal.font.name = "Aptos"
    normal.font.size = Pt(9)

    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.0

    heading_1 = document.styles["Heading 1"]

    heading_1.font.name = "Aptos Display"
    heading_1.font.size = Pt(11)
    heading_1.font.bold = True
    heading_1.font.color.rgb = RGBColor(
        31,
        55,
        78,
    )

    heading_1.paragraph_format.keep_with_next = True
    heading_1.paragraph_format.space_before = Pt(6)
    heading_1.paragraph_format.space_after = Pt(2)

    heading_2 = document.styles["Heading 2"]

    heading_2.font.name = "Aptos Display"
    heading_2.font.size = Pt(9.5)
    heading_2.font.bold = True
    heading_2.font.color.rgb = RGBColor(
        31,
        55,
        78,
    )

    heading_2.paragraph_format.keep_with_next = True
    heading_2.paragraph_format.space_before = Pt(4)
    heading_2.paragraph_format.space_after = Pt(1)


def _add_header(document, paragraphs):

    header = paragraphs[:3]

    if not header:
        return

    name = document.add_paragraph()

    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.paragraph_format.space_after = Pt(0)

    run = name.add_run(
        clean_resume_text(header[0]["text"])
    )

    run.bold = True
    run.font.name = "Aptos Display"
    run.font.size = Pt(17)
    run.font.color.rgb = RGBColor(
        31,
        55,
        78,
    )

    if len(header) > 1:

        tagline = document.add_paragraph()

        tagline.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tagline.paragraph_format.space_after = Pt(1)

        run = tagline.add_run(
            clean_resume_text(header[1]["text"])
        )

        run.italic = True
        run.font.name = "Aptos"
        run.font.size = Pt(9)

    if len(header) > 2:

        contact = document.add_paragraph()

        contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
        contact.paragraph_format.space_after = Pt(5)

        run = contact.add_run(
            clean_resume_text(header[2]["text"])
        )

        run.font.name = "Aptos"
        run.font.size = Pt(8)


def _decision_lookup(processed_data):

    lookup = {}

    for decision in processed_data.get(
        "paragraph_decisions",
        [],
    ):

        if not isinstance(decision, dict):
            continue

        ids = decision.get(
            "source_paragraph_ids",
            [],
        )

        if isinstance(ids, list) and len(ids) == 1:

            lookup[ids[0]] = decision

    return lookup


def _selected_project_ids(
    processed_data,
    structure,
):

    valid_ids = {
        project["title_id"]
        for project in structure["projects"]
    }

    selected = processed_data.get(
        "selected_project_ids"
    )

    if (
        isinstance(selected, list)
        and len(selected) == 3
        and len(set(selected)) == 3
        and set(selected).issubset(valid_ids)
    ):

        return set(selected)

    # Fallback for older processed records.
    return {
        project["title_id"]
        for project in structure["projects"][:3]
    }


def _renumber_project_title(text, number):

    text = clean_resume_text(text)

    text = re.sub(
        r"^\s*\d+[\.\)]\s*",
        "",
        text,
    )

    return f"{number}. {text}"


def _split_skill_label(text):

    cleaned = clean_resume_text(text)

    for label in SKILL_LABELS:

        if cleaned.casefold() == label.casefold():

            return label, ""

        prefix = label.casefold()

        if cleaned.casefold().startswith(prefix + " "):

            remainder = cleaned[len(label):].strip()

            return label, remainder

        if cleaned.casefold().startswith(prefix + ":"):

            remainder = cleaned[len(label):].lstrip(" :")

            return label, remainder

    return None, None


def _add_skill_paragraph(
    document,
    text,
    formatting_data,
    paragraph_id,
):

    label, remainder = _split_skill_label(text)

    paragraph = document.add_paragraph()

    paragraph.paragraph_format.space_after = Pt(1)

    if label is None:

        paragraph.add_run(
            clean_resume_text(text)
        )

    else:

        label_run = paragraph.add_run(
            f"{label}:"
        )

        label_run.bold = True

        if remainder:

            paragraph.add_run(
                f" {clean_resume_text(remainder)}"
            )

    paragraph_lookup, definitions = _format_lookup(
        formatting_data
    )

    info = paragraph_lookup.get(
        paragraph_id,
        {},
    )

    _apply_layout(
        paragraph,
        definitions.get(info.get("f"), {}),
    )

    return paragraph


def _add_source_paragraph(
    document,
    text,
    paragraph_id,
    formatting_data,
    role,
    section_name,
    project_number=None,
):

    text = clean_resume_text(text)

    paragraph_lookup, definitions = _format_lookup(
        formatting_data
    )

    info = paragraph_lookup.get(
        paragraph_id,
        {},
    )

    format_data = definitions.get(
        info.get("f"),
        {},
    )

    # Major section headings.
    if (
        role == "section_heading"
        or is_major_heading(text)
    ):

        return document.add_heading(
            clean_heading(text),
            level=1,
        )

    # Project titles.
    if role == "project_title":

        title = (
            _renumber_project_title(
                text,
                project_number,
            )
            if project_number is not None
            else text
        )

        return document.add_heading(
            title,
            level=2,
        )

    # Skills are formatted separately to prevent labels
    # from becoming oversized headings.
    if section_name == "KEY SKILLS":

        return _add_skill_paragraph(
            document,
            text,
            formatting_data,
            paragraph_id,
        )

    has_literal_bullet = bool(
        re.match(
            r"^\s*[•●▪◦‣∙·\uf0b7]\s*",
            text,
        )
    )

    # Apply exactly one bullet marker.
    if (
        role == "bullet"
        or info.get("t") == "bullet"
        or has_literal_bullet
    ):

        bullet_text = strip_leading_bullet_markers(
            text
        )

        paragraph = document.add_paragraph(
            bullet_text,
            style="List Bullet",
        )

        paragraph.paragraph_format.space_after = Pt(1)

        _apply_layout(
            paragraph,
            format_data,
        )

        return paragraph

    # Normal-sized bold subheadings.
    if (
        role in {"subheading", "project_metadata"}
        or info.get("t") == "subheader"
    ):

        paragraph = document.add_paragraph()

        paragraph.paragraph_format.keep_with_next = (
            role == "subheading"
        )

        if role == "project_metadata":

            match = re.match(
                r"^\s*(Technologies|Technology|Tools|Tech stack|Technology stack)\s*:\s*(.*)$",
                text,
                re.I,
            )

            if match:

                label = paragraph.add_run(
                    f"{match.group(1)}:"
                )

                label.bold = True

                if match.group(2):

                    paragraph.add_run(
                        f" {match.group(2)}"
                    )

            else:

                paragraph.add_run(text)

        else:

            run = paragraph.add_run(text)
            run.bold = True

        paragraph.paragraph_format.space_after = Pt(1)

        _apply_layout(
            paragraph,
            format_data,
        )

        return paragraph

    # Normal body paragraph.
    paragraph = document.add_paragraph(text)

    _apply_layout(
        paragraph,
        format_data,
    )

    return paragraph


def create_resume_docx(
    db,
    processed_resume_id,
):

    processed = (
        db.query(ProcessedResume)
        .filter(
            ProcessedResume.id == processed_resume_id
        )
        .first()
    )

    if not processed:

        raise ValueError(
            "Processed resume not found."
        )

    resume_data = load_resume_data(
        db,
        processed.resume_id,
    )

    processed_data = load_json(
        processed.processed_data
    )

    if not isinstance(processed_data, dict):

        raise ValueError(
            "Processed resume data is invalid."
        )

    paragraphs = resume_data["paragraphs"]
    formatting = resume_data["formatting"]

    structure = build_resume_structure(
        paragraphs,
        formatting,
    )

    document = Document()

    _configure_document(document)

    _add_header(
        document,
        paragraphs,
    )

    records = {
        item["id"]: item
        for item in structure["records"]
    }

    decisions = _decision_lookup(
        processed_data
    )

    selected_projects = _selected_project_ids(
        processed_data,
        structure,
    )

    project_membership = {}

    for project in structure["projects"]:

        for paragraph_id in project["paragraph_ids"]:

            project_membership[paragraph_id] = (
                project["title_id"]
            )

    paragraph_text_lookup = {
        item["id"]: item["text"]
        for item in paragraphs
    }

    profile_id = structure["profile_id"]

    original_profile = paragraph_text_lookup.get(
        profile_id,
        "",
    )

    summary = clean_resume_text(
        processed_data.get("professional_summary")
        or original_profile
    )

    summary_key = comparison_text(summary)
    profile_key = comparison_text(original_profile)

    summary_inserted = False

    current_section = None

    seen_highlights_text = set()

    project_number = 0

    for source in paragraphs[3:]:

        paragraph_id = source["id"]

        original_text = clean_resume_text(
            source["text"]
        )

        record = records.get(
            paragraph_id,
            {},
        )

        role = record.get(
            "role",
            "content",
        )

        section_name = record.get(
            "section"
        )

        # Track the current section.
        if role == "section_heading":

            current_section = clean_heading(
                original_text
            )

        # Replace the original profile with the tailored summary.
        if paragraph_id == profile_id:

            if summary and not summary_inserted:

                document.add_paragraph(summary)

                summary_inserted = True

                if current_section == "HIGHLIGHTS":

                    seen_highlights_text.add(
                        summary_key
                    )

                    seen_highlights_text.add(
                        profile_key
                    )

            continue

        # Suppress duplicate copies of the original profile.
        if role == "duplicate_profile":
            continue

        # Suppress repeated profile/summary text only inside HIGHLIGHTS.
        if (
            current_section == "HIGHLIGHTS"
            and role not in {
                "section_heading",
                "subheading",
            }
        ):

            normalized = comparison_text(
                original_text
            )

            if normalized and normalized in {
                summary_key,
                profile_key,
            } | seen_highlights_text:

                continue

            if normalized:

                seen_highlights_text.add(
                    normalized
                )

        # Exclude every paragraph belonging to an unselected project.
        project_id = project_membership.get(
            paragraph_id
        )

        if (
            project_id
            and project_id not in selected_projects
        ):

            continue

        decision = decisions.get(
            paragraph_id,
            {},
        )

        action = decision.get(
            "action",
            "keep",
        )

        if action == "remove":
            continue

        if (
            action == "rewrite"
            and decision.get("rewritten_text")
        ):

            text = decision["rewritten_text"]

        else:

            text = original_text

        text = clean_resume_text(text)

        # If no profile paragraph was identified, insert the summary
        # immediately after the HIGHLIGHTS heading.
        if (
            not summary_inserted
            and current_section == "HIGHLIGHTS"
            and role != "section_heading"
        ):

            document.add_paragraph(summary)

            summary_inserted = True

            seen_highlights_text.add(
                summary_key
            )

            seen_highlights_text.add(
                profile_key
            )

        # Renumber selected projects sequentially.
        if role == "project_title":

            project_number += 1

        _add_source_paragraph(
            document=document,
            text=text,
            paragraph_id=paragraph_id,
            formatting_data=formatting,
            role=role,
            section_name=current_section,
            project_number=(
                project_number
                if role == "project_title"
                else None
            ),
        )

    # Final fallback for malformed source structures.
    if summary and not summary_inserted:

        document.add_paragraph(summary)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / f"resume_{processed_resume_id}.docx"
    )

    document.save(output_path)

    return str(output_path)


def convert_to_pdf(docx_path: str) -> str:

    docx_path = Path(docx_path).resolve()

    if not docx_path.exists():

        raise FileNotFoundError(
            f"DOCX file not found: {docx_path}"
        )

    try:

        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

    except subprocess.CalledProcessError as error:

        raise RuntimeError(
            f"PDF conversion failed: {error.stderr}"
        ) from error

    except subprocess.TimeoutExpired as error:

        raise RuntimeError(
            "PDF conversion timed out."
        ) from error

    pdf_path = docx_path.with_suffix(".pdf")

    if not pdf_path.exists():

        raise RuntimeError(
            "LibreOffice completed but the PDF was not created."
        )

    return str(pdf_path)