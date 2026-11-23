import logging

from sqlalchemy.orm import Session

from backend.database.models import ResumeFormatting
from backend.services.jd_retrieval import retrieve_for_job
from backend.services.retrieval import get_source_paragraphs
from backend.services.resume_ext import extract_rag_formatting
from backend.services.resume_text import clean_resume_text


logger = logging.getLogger(__name__)


def build_ai_context(
    db: Session,
    resume_id: int,
    job_description: str,
):
    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    retrieval = retrieve_for_job(
        db,
        resume_id,
        job_description,
    )

    source_paragraphs = get_source_paragraphs(
        db,
        resume_id,
    )

    matches = {
        item["paragraph_id"]: item["matched_requirements"]
        for item in retrieval["unique_paragraphs"]
    }

    resume_paragraphs = []
    seen_ids = set()

    for item in source_paragraphs:
        paragraph_id = item.get("id")
        text = clean_resume_text(item.get("text", ""))

        if not paragraph_id or not text:
            continue

        if paragraph_id in seen_ids:
            raise ValueError(
                f"Duplicate source paragraph ID: {paragraph_id}"
            )

        seen_ids.add(paragraph_id)

        resume_paragraphs.append({
            "paragraph_id": paragraph_id,
            "text": text,
            "matched_requirements": matches.get(paragraph_id, []),
        })

    if not resume_paragraphs:
        raise ValueError("The source resume contains no usable paragraphs.")

    formatting_record = (
        db.query(ResumeFormatting)
        .filter(ResumeFormatting.resume_id == resume_id)
        .first()
    )

    if not formatting_record:
        raise ValueError(
            f"No formatting data found for resume_id={resume_id}"
        )

    formatting = extract_rag_formatting(
        formatting_record.formatting_data,
        [item["paragraph_id"] for item in resume_paragraphs],
    )

    logger.info(
        "Resume context built. resume_id=%s paragraphs=%d matched=%d",
        resume_id,
        len(resume_paragraphs),
        len(matches),
    )

    return {
        "job_requirements": retrieval["requirements"],
        "resume_paragraphs": resume_paragraphs,
        "resume_formatting": formatting,
    }