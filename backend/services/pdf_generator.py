import json
import subprocess
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from backend.database.models import (
    ExtractedResume,
    ResumeFormatting,
    ProcessedResume
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "generated"
HEADER_RESUME_ID = 1


def load_json(data):
    if isinstance(data, str):
        return json.loads(data)
    return data


def load_resume_data(db, resume_id):
    extracted = db.query(ExtractedResume).filter(
        ExtractedResume.resume_id == resume_id
    ).order_by(
        ExtractedResume.id.desc()
    ).first()

    formatting = db.query(ResumeFormatting).filter(
        ResumeFormatting.resume_id == resume_id
    ).first()

    if not extracted or not formatting:
        raise ValueError("Resume data or formatting not found.")

    return {
        "paragraphs": load_json(extracted.extracted_data),
        "formatting": formatting.formatting_data
    }


def apply_formatting(paragraph, format_data):
    if not format_data:
        return

    paragraph_format = paragraph.paragraph_format

    if "sb" in format_data:
        paragraph_format.space_before = Pt(format_data["sb"])

    if "sa" in format_data:
        paragraph_format.space_after = Pt(format_data["sa"])

    if "li" in format_data:
        paragraph_format.left_indent = Inches(format_data["li"])

    if "ri" in format_data:
        paragraph_format.right_indent = Inches(format_data["ri"])

    if "list" in format_data:
        list_type = format_data["list"].get("t")

        if list_type == "bullet":
            paragraph.style = "List Bullet"
        elif list_type == "numbered":
            paragraph.style = "List Number"

    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()

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


def build_format_lookup(formatting_data):
    paragraph_lookup = {
        item["id"]: item
        for item in formatting_data.get("paragraphs", [])
    }

    format_definitions = formatting_data.get("formats", {})

    return paragraph_lookup, format_definitions


def add_paragraph(document, text, paragraph_id, formatting_data):
    paragraph_lookup, format_definitions = build_format_lookup(
        formatting_data
    )

    paragraph_info = paragraph_lookup.get(paragraph_id, {})
    element_type = paragraph_info.get("t")
    format_id = paragraph_info.get("f")
    format_data = format_definitions.get(format_id, {})

    if element_type == "subheader":
        paragraph = document.add_heading(text, level=2)
    elif element_type == "bullet":
        paragraph = document.add_paragraph(text, style="List Bullet")
    else:
        paragraph = document.add_paragraph(text)

    apply_formatting(paragraph, format_data)
    return paragraph

def add_hyperlink(paragraph, text, url, format_data):
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(
        qn("r:id"),
        paragraph.part.relate_to(
            url,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True
        )
    )

    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")

    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    properties.append(color)

    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)

    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "16")
    properties.append(size)

    size_complex = OxmlElement("w:szCs")
    size_complex.set(qn("w:val"), "16")
    properties.append(size_complex)

    run.append(properties)

    text_element = OxmlElement("w:t")
    text_element.text = text
    run.append(text_element)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)

def add_fixed_header(document, header_data):
    paragraphs = header_data["paragraphs"]
    formatting_data = header_data["formatting"]

    paragraph_lookup, format_definitions = build_format_lookup(
        formatting_data
    )

    header_paragraphs = []

    for index, item in enumerate(paragraphs):
        text = item["text"].strip()
        paragraph_info = paragraph_lookup.get(item["id"], {})

        if (
            index > 0
            and paragraph_info.get("t") == "subheader"
            and text.isupper()
        ):
            break

        header_paragraphs.append({
            "text": text,
            "format_data": format_definitions.get(
                paragraph_info.get("f"), {}
            )
        })

    if len(header_paragraphs) < 3:
        raise ValueError("Expected name, tagline and contact details in header.")

    name = header_paragraphs[0]
    tagline = header_paragraphs[1]
    contact_text = header_paragraphs[2]["text"]

    email = "samarthgohel78@gmail.com"
    linkedin = "linkedin.com/in/samarth-gohel"
    portfolio = "datascienceportfol.io/samarthgohel"

    location_phone = contact_text
    for value in (email, linkedin, portfolio):
        location_phone = location_phone.replace(value, "")

    location_phone = location_phone.replace(" |  | ", " | ")
    location_phone = location_phone.replace("  ", " ").strip(" |")

    for item in (name, tagline):
        paragraph = document.add_paragraph(item["text"])
        apply_formatting(paragraph, item["format_data"])
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    links_paragraph = document.add_paragraph()
    links_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    links_paragraph.paragraph_format.space_before = Pt(0)
    links_paragraph.paragraph_format.space_after = Pt(0)

    apply_formatting(
        links_paragraph,
        header_paragraphs[2]["format_data"]
    )

    add_hyperlink(
        links_paragraph,
        email,
        f"mailto:{email}",
        {}
    )
    links_paragraph.add_run(" | ")

    add_hyperlink(
        links_paragraph,
        linkedin,
        f"https://{linkedin}",
        {}
    )
    links_paragraph.add_run(" | ")

    add_hyperlink(
        links_paragraph,
        portfolio,
        f"https://{portfolio}",
        {}
    )

    location_paragraph = document.add_paragraph(location_phone)

    paragraph.paragraph_format.space_after = Pt(2)
    apply_formatting(
        location_paragraph,
        header_paragraphs[2]["format_data"]
    )
    location_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    links_paragraph.paragraph_format.space_before = Pt(0)
    links_paragraph.paragraph_format.space_after = Pt(0)

def create_resume_docx(db, processed_resume_id):
    processed = db.query(ProcessedResume).filter(
        ProcessedResume.id == processed_resume_id
    ).first()

    if not processed:
        raise ValueError("Processed resume not found.")

    header_data = load_resume_data(db, HEADER_RESUME_ID)
    resume_data = load_resume_data(db, processed.resume_id)
    processed_data = load_json(processed.processed_data)

    document = Document()

    add_fixed_header(document, header_data)

    summary = processed_data.get("professional_summary")
    if summary:
        document.add_heading("Professional Summary", level=1)
        document.add_paragraph(summary)

    for item in processed_data.get("tailored_paragraphs", []):
        add_paragraph(
            document,
            item["rewritten_text"],
            item["paragraph_id"],
            resume_data["formatting"]
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"resume_{processed_resume_id}.docx"
    document.save(output_path)

    return str(output_path)


def convert_to_pdf(docx_path: str) -> str:
    docx_path = Path(docx_path).resolve()

    if not docx_path.exists():
        raise FileNotFoundError(
            f"DOCX file not found: {docx_path}"
        )

    output_dir = docx_path.parent

    try:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path)
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60
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
