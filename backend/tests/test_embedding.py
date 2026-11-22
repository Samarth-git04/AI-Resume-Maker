import json
import random

import numpy as np

from docx import Document
from docx.shared import Pt, Inches

from backend.database.database import SessionLocal
from backend.database.models import ResumeFormatting

from backend.services.retrieval import (
    prepare_resume_cache,
    get_source_paragraphs
)

from backend.services.vector_store import VectorStore


RESUME_ID = 1
TOP_K = 10
PARAGRAPH_COUNT = 5

random.seed(42)

db = SessionLocal()

try:
    print("\n--- Loading resume data ---")

    source_paragraphs = get_source_paragraphs(db, RESUME_ID)

    source_lookup = {
        paragraph["id"]: paragraph["text"]
        for paragraph in source_paragraphs
    }

    cache = prepare_resume_cache(db, RESUME_ID)
    chunks = cache["chunks"]

    store = VectorStore(RESUME_ID)
    store.prepare()

    embeddings = np.load(
        store.embeddings_path,
        allow_pickle=False
    )

    print("\n--- Retrieving paragraphs ---")

    selected_indices = random.sample(
        range(len(chunks)),
        5
    )

    retrieved_ids = set()

    for index in selected_indices:
        results = store.search(
            embeddings[index],
            top_k=TOP_K
        )

        for result in results:
            retrieved_ids.update(result["paragraph_ids"])

    assert len(retrieved_ids) >= PARAGRAPH_COUNT

    selected_ids = random.sample(
        list(retrieved_ids),
        PARAGRAPH_COUNT
    )

    selected_ids.sort(
        key=lambda paragraph_id: int(paragraph_id[1:])
    )

    print("Selected paragraphs:", selected_ids)

    print("\n--- Loading formatting ---")

    formatting_record = db.query(ResumeFormatting).filter(
        ResumeFormatting.resume_id == RESUME_ID
    ).first()

    formatting_data = formatting_record.formatting_data

    formatting_lookup = {
        paragraph["id"]: paragraph
        for paragraph in formatting_data["paragraphs"]
    }

    format_definitions = formatting_data["formats"]

    print("\n--- Generating DOCX ---")

    document = Document()

    for paragraph_id in selected_ids:

        text = source_lookup[paragraph_id]
        paragraph_data = formatting_lookup[paragraph_id]

        format_id = paragraph_data.get("f")

        format_data = (
            format_definitions.get(format_id, {})
            if format_id
            else {}
        )

        element_type = paragraph_data["t"]

        if element_type == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")

        else:
            paragraph = document.add_paragraph()

        run = paragraph.add_run(text)

        if "f" in format_data:
            run.font.name = format_data["f"]

        if "z" in format_data:
            run.font.size = Pt(format_data["z"])

        if "b" in format_data:
            run.bold = format_data["b"]

        if "i" in format_data:
            run.italic = format_data["i"]

        if "u" in format_data:
            run.underline = format_data["u"]

        if "sb" in format_data:
            paragraph.paragraph_format.space_before = Pt(
                format_data["sb"]
            )

        if "sa" in format_data:
            paragraph.paragraph_format.space_after = Pt(
                format_data["sa"]
            )

        if "li" in format_data:
            paragraph.paragraph_format.left_indent = Inches(
                format_data["li"]
            )

        if "ri" in format_data:
            paragraph.paragraph_format.right_indent = Inches(
                format_data["ri"]
            )

        print(
            paragraph_id,
            "|",
            element_type,
            "|",
            format_id,
            "|",
            text[:60]
        )

    output_path = "rag_formatting_preview.docx"

    document.save(output_path)

    print("\nDOCX created:", output_path)
    print("Paragraphs included:", PARAGRAPH_COUNT)

finally:
    db.close()