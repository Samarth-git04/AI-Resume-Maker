import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
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


TECHNOLOGY_TERMS = (
    "scikit-learn",
    "TensorFlow",
    "PyTorch",
    "Power BI",
    "Power Query",
    "PowerPoint",
    "JavaScript",
    "TypeScript",
    "Node.js",
    "Next.js",
    "React",
    "FastAPI",
    "LangGraph",
    "LangChain",
    "PostgreSQL",
    "SQL Server",
    "SQLite",
    "BigQuery",
    "Databricks",
    "Snowflake",
    "Supabase",
    "MongoDB",
    "Microsoft Excel",
    "Google Cloud Platform",
    "Google Cloud",
    "Amazon Web Services",
    "GitHub",
    "Docker",
    "Kubernetes",
    "Airflow",
    "dbt",
    "Tableau",
    "Looker",
    "Matplotlib",
    "Plotly",
    "Pandas",
    "NumPy",
    "SciPy",
    "XGBoost",
    "CatBoost",
    "Random Forest",
    "Geant4",
    "Groq API",
    "Python",
    "Java",
    "C++",
    "C#",
    "SQL",
    "NoSQL",
    "Excel",
    "FAISS",
    "LLM",
    "LLMs",
    "API",
    "APIs",
    "Jupyter Notebook",
    "Jupyter",
    "Agile",
    "CI/CD",
    "ETL",
    "ELT",
)

TECHNOLOGY_PATTERN = re.compile(
    r"(?<![\w])(?:"
    + "|".join(
        re.escape(term)
        for term in sorted(
            set(TECHNOLOGY_TERMS),
            key=len,
            reverse=True,
        )
    )
    + r")(?![\w])",
    re.IGNORECASE,
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

    master_resume = (
        db.query(MasterResume)
        .filter(
            MasterResume.id == resume_id
        )
        .first()
    )

    if not master_resume:
        raise ValueError(
            "Original resume record not found."
        )

    if not extracted or not extracted.extracted_data:
        raise ValueError(
            "Extracted resume data not found."
        )

    if not formatting or not formatting.formatting_data:
        raise ValueError(
            "Resume formatting data not found."
        )

    original_path = Path(
        master_resume.file_path
    ).expanduser()

    if not original_path.is_absolute():
        original_path = original_path.resolve()

    if not original_path.exists():
        raise ValueError(
            "Original uploaded DOCX file not found: "
            f"{original_path}"
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
                f"Invalid paragraph at position {index}."
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
                f"Paragraph at position {index} has no ID."
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
        "formatting": formatting.formatting_data,
        "original_path": original_path,
    }


def _format_lookup(formatting_data):

    paragraph_lookup = {
        item["id"]: item
        for item in formatting_data.get(
            "paragraphs", []
        )
        if isinstance(item, dict)
        and item.get("id")
    }

    definitions = formatting_data.get(
        "formats", {}
    )

    return paragraph_lookup, definitions


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


def _base_run_properties(paragraph):

    for run in paragraph.runs:
        if run.text.strip() and run._r.rPr is not None:
            return deepcopy(run._r.rPr)

    for run in paragraph.runs:
        if run._r.rPr is not None:
            return deepcopy(run._r.rPr)

    return None


def _append_styled_run(
    paragraph,
    text,
    base_properties,
    bold=False,
):

    if not text:
        return

    run = paragraph.add_run(text)

    if base_properties is not None:
        run._r.insert(
            0,
            deepcopy(base_properties),
        )

    if bold:
        run.bold = True


def _replace_paragraph_text(
    paragraph,
    text,
    highlight_technologies=False,
):

    text = clean_resume_text(text)

    base_properties = _base_run_properties(
        paragraph
    )

    # Preserve paragraph properties, including style,
    # alignment, indentation, spacing and numbering.
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)

    if not text:
        return

    if not highlight_technologies:
        _append_styled_run(
            paragraph,
            text,
            base_properties,
        )
        return

    matches = list(
        TECHNOLOGY_PATTERN.finditer(text)
    )

    if not matches:
        _append_styled_run(
            paragraph,
            text,
            base_properties,
        )
        return

    cursor = 0

    for match in matches:

        if match.start() > cursor:
            _append_styled_run(
                paragraph,
                text[cursor:match.start()],
                base_properties,
            )

        _append_styled_run(
            paragraph,
            match.group(0),
            base_properties,
            bold=True,
        )

        cursor = match.end()

    if cursor < len(text):
        _append_styled_run(
            paragraph,
            text[cursor:],
            base_properties,
        )


def _remove_paragraph(paragraph):

    # Word table cells must retain at least one paragraph.
    if isinstance(paragraph._parent, _Cell):
        _replace_paragraph_text(
            paragraph,
            "",
        )
        return

    element = paragraph._element
    parent = element.getparent()

    if parent is not None:
        parent.remove(element)


def _validate_source_mapping(
    document,
    source_paragraphs,
):

    original_paragraphs = [
        paragraph
        for paragraph in iter_paragraphs(document)
        if paragraph.text.strip()
    ]

    if len(original_paragraphs) != len(source_paragraphs):
        raise ValueError(
            "Original DOCX paragraph count does not match "
            "the SQL extraction. Refusing to apply formatting "
            "to potentially incorrect paragraphs. "
            f"SQL: {len(source_paragraphs)}, "
            f"DOCX: {len(original_paragraphs)}."
        )

    for index, (source, original) in enumerate(
        zip(
            source_paragraphs,
            original_paragraphs,
        )
    ):

        if comparison_text(source["text"]) != comparison_text(
            original.text
        ):
            raise ValueError(
                "Original DOCX content does not match SQL "
                "paragraph mapping at position "
                f"{index + 1} ({source['id']})."
            )

    return original_paragraphs


def _is_bullet(text, role, format_info):

    has_literal_bullet = bool(
        re.match(
            r"^\s*[•●▪◦‣∙·\uf0b7]\s*",
            text,
        )
    )

    return (
        role == "bullet"
        or format_info.get("t") == "bullet"
        or has_literal_bullet
    )


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

    source_paragraphs = resume_data["paragraphs"]
    formatting = resume_data["formatting"]

    if len(source_paragraphs) < 3:
        raise ValueError(
            "Original resume does not contain the "
            "expected three-paragraph header."
        )

    structure = build_resume_structure(
        source_paragraphs,
        formatting,
    )

    # Open the original uploaded document instead of
    # creating a new blank document.
    document = Document(
        str(resume_data["original_path"])
    )

    original_paragraphs = _validate_source_mapping(
        document,
        source_paragraphs,
    )

    records = {
        item["id"]: item
        for item in structure["records"]
    }

    format_lookup, _ = _format_lookup(
        formatting
    )

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
        for item in source_paragraphs
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

    for index in range(
        3,
        len(source_paragraphs),
    ):

        source = source_paragraphs[index]
        paragraph = original_paragraphs[index]

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

        format_info = format_lookup.get(
            paragraph_id,
            {},
        )

        if role == "section_heading":
            current_section = clean_heading(
                original_text
            )

        # Replace the original profile paragraph.
        if paragraph_id == profile_id:

            if summary and not summary_inserted:
                _replace_paragraph_text(
                    paragraph,
                    summary,
                )

                summary_inserted = True

                if current_section == "HIGHLIGHTS":
                    seen_highlights_text.add(
                        summary_key
                    )

                    seen_highlights_text.add(
                        profile_key
                    )
            else:
                _remove_paragraph(paragraph)

            continue

        # Remove duplicate profile paragraphs.
        if role == "duplicate_profile":
            _remove_paragraph(paragraph)
            continue

        # Prevent duplicate summaries in HIGHLIGHTS.
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

                _remove_paragraph(paragraph)
                continue

            if normalized:
                seen_highlights_text.add(
                    normalized
                )

        # Remove paragraphs from unselected projects.
        project_id = project_membership.get(
            paragraph_id
        )

        if (
            project_id
            and project_id not in selected_projects
        ):
            _remove_paragraph(paragraph)
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
            _remove_paragraph(paragraph)
            continue

        if (
            action == "rewrite"
            and decision.get("rewritten_text")
        ):
            text = clean_resume_text(
                decision["rewritten_text"]
            )
        else:
            text = original_text

        # Renumber selected projects sequentially.
        if role == "project_title":
            project_number += 1

            text = _renumber_project_title(
                text,
                project_number,
            )

        is_bullet = _is_bullet(
            text,
            role,
            format_info,
        )

        # Preserve original run formatting while highlighting
        # technology terms in bullet points.
        should_highlight = is_bullet

        if text != clean_resume_text(paragraph.text):

            _replace_paragraph_text(
                paragraph,
                text,
                highlight_technologies=should_highlight,
            )

        elif should_highlight and TECHNOLOGY_PATTERN.search(text):

            _replace_paragraph_text(
                paragraph,
                text,
                highlight_technologies=True,
            )

    if summary and not summary_inserted:
        raise ValueError(
            "Could not identify the original profile paragraph. "
            "Refusing to insert a newly styled paragraph."
        )

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

    docx_path = Path(
        docx_path
    ).resolve()

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
