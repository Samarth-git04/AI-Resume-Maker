import json
import re
import subprocess

from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell

from backend.database.models import (
    ExtractedResume,
    MasterResume,
    ProcessedResume,
    ResumeFormatting,
)

from backend.services.resume_ext import iter_paragraphs
from backend.services.resume_structure import (
    build_resume_structure,
    clean_heading,
)
from backend.services.resume_text import (
    clean_resume_text,
    comparison_text,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "generated"


def load_json(data):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError("Stored resume JSON is invalid.") from error
    return data


def load_resume_data(db, resume_id):
    extracted = (
        db.query(ExtractedResume)
        .filter(ExtractedResume.resume_id == resume_id)
        .order_by(ExtractedResume.id.desc())
        .first()
    )

    formatting = (
        db.query(ResumeFormatting)
        .filter(ResumeFormatting.resume_id == resume_id)
        .first()
    )

    master = (
        db.query(MasterResume)
        .filter(MasterResume.id == resume_id)
        .first()
    )

    if not master:
        raise ValueError("Original resume record not found.")

    if not extracted or not extracted.extracted_data:
        raise ValueError("Extracted resume data not found.")

    if not formatting or not formatting.formatting_data:
        raise ValueError("Resume formatting data not found.")

    original_path = Path(master.file_path).expanduser().resolve()

    if not original_path.is_file():
        raise ValueError("Original uploaded DOCX file was not found.")

    paragraphs = load_json(extracted.extracted_data)

    if not isinstance(paragraphs, list):
        raise ValueError("Extracted resume paragraphs are invalid.")

    cleaned = []

    for item in paragraphs:
        if not isinstance(item, dict):
            continue

        paragraph_id = item.get("id") or item.get("paragraph_id")
        text = clean_resume_text(item.get("text", ""))

        if paragraph_id and text:
            cleaned.append({
                **item,
                "id": paragraph_id,
                "text": text,
            })

    return {
        "paragraphs": cleaned,
        "formatting": formatting.formatting_data,
        "original_path": original_path,
    }


def _format_lookup(formatting):
    return {
        item["id"]: item
        for item in formatting.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id")
    }


def _decision_lookup(processed_data):
    result = {}

    for decision in processed_data.get("paragraph_decisions", []):
        if not isinstance(decision, dict):
            continue

        ids = decision.get("source_paragraph_ids", [])

        if isinstance(ids, list) and len(ids) == 1:
            result[ids[0]] = decision

    return result


def _base_run_properties(paragraph):
    for run in paragraph.runs:
        if run.text.strip() and run._r.rPr is not None:
            return deepcopy(run._r.rPr)

    for run in paragraph.runs:
        if run._r.rPr is not None:
            return deepcopy(run._r.rPr)

    return None


def _clear_runs(paragraph):
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def _append_run(paragraph, text, properties=None, bold=None):
    if not text:
        return None

    run = paragraph.add_run(text)

    if properties is not None:
        run._r.insert(0, deepcopy(properties))

    if bold is not None:
        run.bold = bold

    return run


def _replace_text(paragraph, text):
    text = clean_resume_text(text)
    properties = _base_run_properties(paragraph)

    _clear_runs(paragraph)
    _append_run(paragraph, text, properties)


def _replace_achievement(paragraph, text):
    text = clean_resume_text(text)
    properties = _base_run_properties(paragraph)

    match = re.match(r"^([^:]{1,90})\s*:\s*(.*)$", text)

    _clear_runs(paragraph)

    if match:
        company, body = match.groups()

        company_run = _append_run(
            paragraph,
            f"{company}: ",
            properties,
            bold=True,
        )

        if company_run:
            company_run.font.size = Pt(10)

        body_run = _append_run(
            paragraph,
            body,
            properties,
            bold=False,
        )

        if body_run:
            body_run.font.size = Pt(10)

    else:
        _append_run(paragraph, text, properties)


def _remove_paragraph(paragraph):
    if isinstance(paragraph._parent, _Cell):
        _replace_text(paragraph, "")
        return

    element = paragraph._element
    parent = element.getparent()

    if parent is not None:
        parent.remove(element)


def _validate_source_mapping(document, source_paragraphs):
    original = [
        paragraph
        for paragraph in iter_paragraphs(document)
        if clean_resume_text(paragraph.text)
    ]

    if len(original) != len(source_paragraphs):
        raise ValueError(
            "Original DOCX paragraph count differs from extracted data. "
            "Refusing to apply decisions to incorrect paragraphs."
        )

    for index, (source, paragraph) in enumerate(zip(source_paragraphs, original)):
        if comparison_text(source["text"]) != comparison_text(paragraph.text):
            raise ValueError(
                "Original DOCX paragraph mapping mismatch at "
                f"position {index + 1}, ID {source['id']}."
            )

    return original


def create_resume_docx(db, processed_resume_id):
    processed = (
        db.query(ProcessedResume)
        .filter(ProcessedResume.id == processed_resume_id)
        .first()
    )

    if not processed:
        raise ValueError("Processed resume not found.")

    processed_data = load_json(processed.processed_data)

    if not isinstance(processed_data, dict):
        raise ValueError("Processed resume data is invalid.")

    if processed_data.get("generation_version") != "2.0":
        raise ValueError(
            "This processed resume uses an older generation format. "
            "Analyse the job description again before generating."
        )

    resume_data = load_resume_data(db, processed.resume_id)
    source_paragraphs = resume_data["paragraphs"]

    structure = build_resume_structure(
        source_paragraphs,
        resume_data["formatting"],
    )

    document = Document(str(resume_data["original_path"]))

    original_paragraphs = _validate_source_mapping(
        document,
        source_paragraphs,
    )

    records = {
        item["id"]: item
        for item in structure["records"]
    }

    format_lookup = _format_lookup(resume_data["formatting"])
    decisions = _decision_lookup(processed_data)

    selected_projects = set(
        processed_data.get("selected_project_ids", [])
    )

    valid_project_ids = {
        project["title_id"]
        for project in structure["projects"]
    }

    if not selected_projects.issubset(valid_project_ids):
        raise ValueError("Generated resume contains invalid project IDs.")

    selected_achievements = set(
        processed_data.get("selected_achievement_ids", [])
    )

    valid_achievement_ids = {
        item["id"]
        for item in structure["records"]
        if (
            item.get("section") == "HIGHLIGHTS"
            and item.get("role") in {"bullet", "content"}
        )
    }

    if not selected_achievements.issubset(valid_achievement_ids):
        raise ValueError("Generated resume contains invalid achievement IDs.")

    project_membership = {}

    for project in structure["projects"]:
        for paragraph_id in project["paragraph_ids"]:
            project_membership[paragraph_id] = project["title_id"]

    paragraph_text = {
        item["id"]: item["text"]
        for item in source_paragraphs
    }

    profile_id = structure["profile_id"]
    summary = clean_resume_text(
        processed_data.get("professional_summary", "")
    )

    summary_inserted = False
    current_section = None
    project_number = 0

    for index, source in enumerate(source_paragraphs):
        paragraph_id = source["id"]
        original_text = clean_resume_text(source["text"])
        paragraph = original_paragraphs[index]

        record = records.get(paragraph_id, {})
        role = record.get("role", "content")
        format_info = format_lookup.get(paragraph_id, {})

        if role == "section_heading":
            current_section = record.get("section")

        if paragraph_id == profile_id:
            if summary and not summary_inserted:
                _replace_text(paragraph, summary)
                summary_inserted = True
            else:
                _remove_paragraph(paragraph)
            continue

        if role == "profile":
            _remove_paragraph(paragraph)
            continue

        project_id = project_membership.get(paragraph_id)

        if project_id and project_id not in selected_projects:
            _remove_paragraph(paragraph)
            continue

        if (
            role == "project_title"
            and project_id in selected_projects
        ):
            project_number += 1

        decision = decisions.get(paragraph_id, {})
        action = decision.get("action", "keep")

        if action == "remove":
            _remove_paragraph(paragraph)
            continue

        if action == "rewrite":
            rewritten = clean_resume_text(
                decision.get("rewritten_text", "")
            )

            if not rewritten:
                raise ValueError(
                    f"Missing rewritten text for paragraph {paragraph_id}."
                )

            text = rewritten
        else:
            text = original_text

        if (
            current_section == "HIGHLIGHTS"
            and paragraph_id in selected_achievements
        ):
            _replace_achievement(paragraph, text)
            continue

        if (
            current_section == "HIGHLIGHTS"
            and role in {"bullet", "content"}
            and paragraph_id not in selected_achievements
            and paragraph_id in valid_achievement_ids
        ):
            _remove_paragraph(paragraph)
            continue

        # Keep the original Word list formatting. Remove only literal
        # bullet glyphs if the source text itself contains one.
        if format_info.get("t") == "bullet":
            text = re.sub(r"^\s*[•●▪◦‣∙·]\s*", "", text)

        if text != clean_resume_text(paragraph.text):
            _replace_text(paragraph, text)

    if summary and not summary_inserted:
        raise ValueError(
            "A professional summary was generated, but no summary "
            "paragraph was identified in the original DOCX. "
            "Add a Summary/Profile section to the source resume."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"resume_{processed_resume_id}.docx"
    document.save(output_path)

    return str(output_path)


def convert_to_pdf(docx_path):
    docx_path = Path(docx_path).resolve()

    if not docx_path.is_file():
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
        raise RuntimeError(
            f"PDF conversion failed: {error.stderr}"
        ) from error

    except subprocess.TimeoutExpired as error:
        raise RuntimeError("PDF conversion timed out.") from error

    pdf_path = docx_path.with_suffix(".pdf")

    if not pdf_path.exists():
        raise RuntimeError("PDF conversion completed but no PDF was created.")

    return str(pdf_path)