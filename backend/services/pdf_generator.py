import json
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from backend.database.models import (
    ExtractedResume,
    ResumeFormatting,
    ProcessedResume,
)
from backend.services.resume_structure import build_resume_structure

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "generated"


def load_json(data):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError("Stored resume JSON is invalid.") from error
    return data


def load_resume_data(db, resume_id):
    extracted = db.query(ExtractedResume).filter(
        ExtractedResume.resume_id == resume_id
    ).order_by(ExtractedResume.id.desc()).first()

    formatting = db.query(ResumeFormatting).filter(
        ResumeFormatting.resume_id == resume_id
    ).first()

    if not extracted or not formatting or not extracted.extracted_data:
        raise ValueError("Resume data or formatting not found.")

    paragraphs = load_json(extracted.extracted_data)
    if not isinstance(paragraphs, list):
        raise ValueError("Extracted resume paragraphs are invalid.")

    return {
        "paragraphs": paragraphs,
        "formatting": formatting.formatting_data or {},
    }


def _format_lookup(formatting_data):
    paragraph_lookup = {
        item["id"]: item
        for item in formatting_data.get("paragraphs", [])
    }
    definitions = formatting_data.get("formats", {})
    return paragraph_lookup, definitions


def _apply_formatting(paragraph, format_data):
    if not format_data:
        return

    pf = paragraph.paragraph_format
    if "sb" in format_data:
        pf.space_before = Pt(format_data["sb"])
    if "sa" in format_data:
        pf.space_after = Pt(format_data["sa"])
    if "li" in format_data:
        pf.left_indent = Inches(format_data["li"])
    if "ri" in format_data:
        pf.right_indent = Inches(format_data["ri"])

    for run in paragraph.runs:
        if format_data.get("f"):
            run.font.name = format_data["f"]
        if format_data.get("z"):
            run.font.size = Pt(format_data["z"])
        if format_data.get("b") is not None:
            run.bold = format_data["b"]
        if format_data.get("i") is not None:
            run.italic = format_data["i"]
        if format_data.get("u") is not None:
            run.underline = format_data["u"]


def _add_source_paragraph(document, text, paragraph_id, formatting_data):
    paragraph_lookup, definitions = _format_lookup(formatting_data)
    info = paragraph_lookup.get(paragraph_id, {})
    element_type = info.get("t")
    format_data = definitions.get(info.get("f"), {})

    if element_type == "subheader":
        paragraph = document.add_heading(text, level=2)
        paragraph.paragraph_format.keep_with_next = True
    elif element_type == "bullet":
        paragraph = document.add_paragraph(text, style="List Bullet")
    else:
        paragraph = document.add_paragraph(text)

    _apply_formatting(paragraph, format_data)
    return paragraph


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

    for style_name in ("Heading 1", "Heading 2"):
        style = document.styles[style_name]
        style.font.name = "Aptos Display"
        style.font.color.rgb = RGBColor(31, 55, 78)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(5)
        style.paragraph_format.space_after = Pt(2)

    document.styles["Heading 1"].font.size = Pt(11)
    document.styles["Heading 1"].font.bold = True
    document.styles["Heading 2"].font.size = Pt(9.5)
    document.styles["Heading 2"].font.bold = True


def _add_header(document, paragraphs):
    header = paragraphs[:3]
    if not header:
        return

    name = document.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.paragraph_format.space_after = Pt(0)
    run = name.add_run(header[0]["text"])
    run.bold = True
    run.font.name = "Aptos Display"
    run.font.size = Pt(17)
    run.font.color.rgb = RGBColor(31, 55, 78)

    if len(header) > 1:
        tagline = document.add_paragraph()
        tagline.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tagline.paragraph_format.space_after = Pt(1)
        run = tagline.add_run(header[1]["text"])
        run.italic = True
        run.font.size = Pt(9)

    if len(header) > 2:
        contact = document.add_paragraph()
        contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
        contact.paragraph_format.space_after = Pt(5)
        run = contact.add_run(header[2]["text"])
        run.font.size = Pt(8)


def _decision_lookup(processed_data):
    lookup = {}
    for decision in processed_data.get("paragraph_decisions", []):
        ids = decision.get("source_paragraph_ids", [])
        if len(ids) != 1:
            continue
        lookup[ids[0]] = decision
    return lookup


def _selected_project_ids(processed_data, structure):
    valid = {project["title_id"] for project in structure["projects"]}
    selected = processed_data.get("selected_project_ids")

    if (
        isinstance(selected, list)
        and len(selected) == 3
        and len(set(selected)) == 3
        and set(selected).issubset(valid)
    ):
        return set(selected)

    # Compatibility with older processed records that did not store selection.
    return {project["title_id"] for project in structure["projects"][:3]}


def create_resume_docx(db, processed_resume_id):
    processed = db.query(ProcessedResume).filter(
        ProcessedResume.id == processed_resume_id
    ).first()
    if not processed:
        raise ValueError("Processed resume not found.")

    resume_data = load_resume_data(db, processed.resume_id)
    processed_data = load_json(processed.processed_data)

    if not isinstance(processed_data, dict):
        raise ValueError("Processed resume data is invalid.")

    paragraphs = resume_data["paragraphs"]
    formatting = resume_data["formatting"]
    structure = build_resume_structure(paragraphs, formatting)

    document = Document()
    _configure_document(document)
    _add_header(document, paragraphs)

    decisions = _decision_lookup(processed_data)
    selected_projects = _selected_project_ids(processed_data, structure)
    project_title_ids = {
        project["title_id"] for project in structure["projects"]
    }
    project_membership = {}
    for project in structure["projects"]:
        for paragraph_id in project["paragraph_ids"]:
            project_membership[paragraph_id] = project["title_id"]

    profile_id = structure["profile_id"]
    summary = processed_data.get("professional_summary")
    summary_inserted = False

    for source in paragraphs[3:]:
        paragraph_id = source["id"]
        original_text = source["text"]

        # The original profile is replaced by the tailored summary, keeping it
        # in the HIGHLIGHTS section and preventing a duplicate profile.
        if paragraph_id == profile_id:
            if summary:
                document.add_paragraph(summary)
                summary_inserted = True
            continue

        # Exclude every paragraph belonging to an unselected project, not just
        # its title. This prevents orphaned technology and description lines.
        project_id = project_membership.get(paragraph_id)
        if project_id and project_id not in selected_projects:
            continue

        decision = decisions.get(paragraph_id, {})
        action = decision.get("action", "keep")
        if action == "remove":
            continue

        text = (
            decision.get("rewritten_text")
            if action == "rewrite" and decision.get("rewritten_text")
            else original_text
        )

        paragraph = _add_source_paragraph(
            document,
            text,
            paragraph_id,
            formatting,
        )

        # If the profile paragraph was absent from the original structure,
        # place the summary immediately after the HIGHLIGHTS heading.
        if (
            not summary_inserted
            and summary
            and paragraph_id in {
                item["paragraph_id"]
                for item in structure["sections"]
                if item["name"] == "HIGHLIGHTS"
            }
        ):
            document.add_paragraph(summary)
            summary_inserted = True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"resume_{processed_resume_id}.docx"
    document.save(output_path)
    return str(output_path)


def convert_to_pdf(docx_path: str) -> str:
    docx_path = Path(docx_path).resolve()
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX file not found: {docx_path}")

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
        raise RuntimeError(f"PDF conversion failed: {error.stderr}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("PDF conversion timed out.") from error

    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RuntimeError("LibreOffice completed but the PDF was not created.")
    return str(pdf_path)
