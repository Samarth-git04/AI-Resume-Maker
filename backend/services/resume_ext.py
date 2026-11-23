import json

import pymupdf

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn


def extract_pdf_text(file_path: str) -> str:
    with pymupdf.open(file_path) as pdf:
        return "".join(page.get_text() for page in pdf).strip()


def iter_paragraphs(parent, seen_cells=None):
    if seen_cells is None:
        seen_cells = set()

    if isinstance(parent, DocumentObject):
        container = parent.element.body
    elif isinstance(parent, _Cell):
        container = parent._tc
    else:
        return

    for child in container.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            table = Table(child, parent)
            for row in table.rows:
                for cell in row.cells:
                    cell_id = id(cell._tc)
                    if cell_id in seen_cells:
                        continue
                    seen_cells.add(cell_id)
                    yield from iter_paragraphs(cell, seen_cells)


def extract_docx_paragraphs(file_path: str) -> list:
    document = Document(file_path)
    return [
        {"id": f"P{index}", "text": paragraph.text.strip()}
        for index, paragraph in enumerate(
            (p for p in iter_paragraphs(document) if p.text.strip()),
            start=1,
        )
    ]


def extract_docx_text(file_path: str) -> str:
    return "\n".join(item["text"] for item in extract_docx_paragraphs(file_path))


def remove_nulls(data):
    if isinstance(data, dict):
        return {
            key: remove_nulls(value)
            for key, value in data.items()
            if value is not None and value != {} and value != []
        }
    if isinstance(data, list):
        return [remove_nulls(item) for item in data if item is not None]
    return data


def get_style_chain(style):
    while style:
        yield style
        style = style.base_style


def resolve_font_property(run, property_name):
    candidates = [run.font]
    if run.style:
        candidates.append(run.style.font)

    paragraph = run._parent
    if paragraph.style:
        candidates.extend(
            style.font for style in get_style_chain(paragraph.style)
        )

    for font in candidates:
        value = getattr(font, property_name)
        if value is not None:
            return value
    return None


def resolve_paragraph_property(paragraph, property_name):
    value = getattr(paragraph.paragraph_format, property_name)
    if value is not None:
        return value
    if paragraph.style:
        for style in get_style_chain(paragraph.style):
            value = getattr(style.paragraph_format, property_name)
            if value is not None:
                return value
    return None


def format_length(value, unit="pt"):
    if value is None:
        return None
    if unit == "pt":
        return round(value.pt, 1)
    if unit == "inches":
        return round(value.inches, 2)
    return value


def get_numbering_properties(paragraph):
    ppr = paragraph._p.pPr
    if ppr is not None and ppr.numPr is not None:
        return ppr.numPr

    if paragraph.style:
        for style in get_style_chain(paragraph.style):
            style_ppr = style.element.pPr
            if style_ppr is not None and style_ppr.numPr is not None:
                return style_ppr.numPr
    return None


def extract_list_formatting(paragraph, document):
    num_pr = get_numbering_properties(paragraph)
    if num_pr is None or num_pr.numId is None:
        return None

    num_id = num_pr.numId.val
    level = num_pr.ilvl.val if num_pr.ilvl is not None else 0

    try:
        numbering = document.part.numbering_part.element
    except (AttributeError, KeyError):
        return {"t": "unknown"}

    num = [
        item for item in numbering.findall(qn("w:num"))
        if item.get(qn("w:numId")) == str(num_id)
    ]
    if not num:
        return {"t": "unknown"}

    abstract_id = num[0].abstractNumId.val
    abstract = [
        item for item in numbering.findall(qn("w:abstractNum"))
        if item.get(qn("w:abstractNumId")) == str(abstract_id)
    ]
    if not abstract:
        return {"t": "unknown"}

    levels = [
        item for item in abstract[0].findall(qn("w:lvl"))
        if item.get(qn("w:ilvl")) == str(level)
    ]
    if not levels:
        return {"t": "unknown"}

    num_format = levels[0].find(qn("w:numFmt"))
    list_type = (
        "bullet"
        if num_format is not None and num_format.get(qn("w:val")) == "bullet"
        else "numbered"
    )
    result = {"t": list_type}
    if level:
        result["l"] = level
    return result


def is_bullet(paragraph, document):
    list_data = extract_list_formatting(paragraph, document)
    if list_data and list_data.get("t") != "unknown":
        return True

    style_name = paragraph.style.name.lower() if paragraph.style else ""
    return "list bullet" in style_name or "list number" in style_name


def is_heading(paragraph):
    text = paragraph.text.strip()
    if not text or len(text) > 90:
        return False

    style_name = paragraph.style.name.lower() if paragraph.style else ""
    if any(word in style_name for word in ("heading", "title", "subtitle")):
        return True

    if text.isupper() and any(char.isalpha() for char in text):
        return True

    # Treat a short line as a subheading only when all visible text runs are
    # bold. A bold lead-in inside a normal bullet is not a heading.
    visible_runs = [run for run in paragraph.runs if run.text.strip()]
    return bool(visible_runs) and all(run.bold is True for run in visible_runs)


def classify_element(paragraph, index, personal_info_finished, document):
    if index == 0:
        return "header", personal_info_finished

    if is_bullet(paragraph, document):
        return "bullet", personal_info_finished

    if is_heading(paragraph):
        return "subheader", True

    if not personal_info_finished:
        return "personal_info", personal_info_finished

    return "paragraph", personal_info_finished


def extract_element_style(paragraph):
    for run in paragraph.runs:
        if not run.text.strip():
            continue
        properties = {
            "f": resolve_font_property(run, "name"),
            "z": format_length(resolve_font_property(run, "size")),
            "b": resolve_font_property(run, "bold"),
            "i": resolve_font_property(run, "italic"),
            "u": resolve_font_property(run, "underline"),
        }
        return {
            key: value
            for key, value in properties.items()
            if value is not None and value is not False
        }
    return {}


def extract_paragraph_layout(paragraph, document):
    layout = {}
    properties = {
        "sb": ("space_before", "pt"),
        "sa": ("space_after", "pt"),
        "li": ("left_indent", "inches"),
        "ri": ("right_indent", "inches"),
    }

    for key, (property_name, unit) in properties.items():
        value = format_length(
            resolve_paragraph_property(paragraph, property_name),
            unit,
        )
        if value is not None and abs(value) > 0.05:
            layout[key] = value

    list_data = extract_list_formatting(paragraph, document)
    if list_data and list_data.get("t") != "unknown":
        layout["list"] = list_data
    return layout


def normalise_font_sizes(elements, tolerance=5):
    sizes = sorted({
        element["format"]["z"]
        for element in elements
        if "z" in element["format"]
    })
    mapping = {}
    group_min = None

    for size in sizes:
        if group_min is None or size - group_min > tolerance:
            group_min = size
        mapping[size] = group_min

    for element in elements:
        if "z" in element["format"]:
            element["format"]["z"] = mapping[element["format"]["z"]]


def normalise_layout(elements):
    for element in elements:
        formatting = element["format"]
        for key in {"sb", "sa"}:
            if key in formatting:
                formatting[key] = round(formatting[key])
        for key in {"li", "ri"}:
            if key in formatting:
                formatting[key] = round(formatting[key] * 10) / 10


def get_format_id(data, definitions, lookup):
    if not data:
        return None
    key = json.dumps(data, sort_keys=True)
    if key not in lookup:
        format_id = f"F{len(lookup) + 1}"
        lookup[key] = format_id
        definitions[format_id] = data
    return lookup[key]


def extract_docx_formatting(file_path: str) -> dict:
    document = Document(file_path)
    formatting = {"formats": {}, "paragraphs": []}
    paragraphs = [
        paragraph for paragraph in iter_paragraphs(document)
        if paragraph.text.strip()
    ]

    elements = []
    personal_info_finished = False

    for index, paragraph in enumerate(paragraphs):
        element_type, personal_info_finished = classify_element(
            paragraph, index, personal_info_finished, document
        )
        format_data = extract_element_style(paragraph)
        format_data.update(extract_paragraph_layout(paragraph, document))
        elements.append({
            "id": f"P{index + 1}",
            "type": element_type,
            "format": format_data,
        })

    normalise_font_sizes(elements)
    normalise_layout(elements)

    format_lookup = {}
    for element in elements:
        format_id = get_format_id(
            element["format"], formatting["formats"], format_lookup
        )
        item = {"id": element["id"], "t": element["type"]}
        if format_id:
            item["f"] = format_id
        formatting["paragraphs"].append(item)

    return remove_nulls(formatting)


def extract_rag_formatting(formatting_data: dict, retrieved_paragraph_ids: list) -> dict:
    requested_ids = set(retrieved_paragraph_ids)
    selected = [
        item for item in formatting_data.get("paragraphs", [])
        if item["id"] in requested_ids
    ]
    required_formats = {
        item["f"] for item in selected if "f" in item
    }
    formats = {
        key: formatting_data["formats"][key]
        for key in required_formats
        if key in formatting_data.get("formats", {})
    }
    return {"formats": formats, "paragraphs": selected}


def serialise_formatting(formatting_data: dict) -> str:
    return json.dumps(formatting_data, separators=(",", ":"))
