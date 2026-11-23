import logging

from sqlalchemy.orm import Session

from backend.database.models import ResumeFormatting
from backend.services.jd_retrieval import retrieve_for_job
from backend.services.retrieval import get_source_paragraphs
from backend.services.resume_ext import extract_rag_formatting

logger = logging.getLogger(__name__)


def build_ai_context(
    db: Session,
    resume_id: int,
    job_description: str
) -> dict:

    logger.info("Building AI context for resume_id=%s", resume_id)

    retrieval_data = retrieve_for_job(
        db,
        resume_id,
        job_description
    )

    logger.info(
        "JD retrieval completed. Requirements=%s, unique_paragraphs=%s",
        len(retrieval_data.get("requirements", [])),
        len(retrieval_data.get("unique_paragraphs", []))
    )

    source_paragraphs = get_source_paragraphs(
        db,
        resume_id
    )

    logger.info(
        "Loaded %s source paragraphs for resume_id=%s",
        len(source_paragraphs),
        resume_id
    )

    source_lookup = {
        paragraph["id"]: paragraph["text"]
        for paragraph in source_paragraphs
    }

    resume_paragraphs = []

    for paragraph in retrieval_data["unique_paragraphs"]:

        paragraph_id = paragraph["paragraph_id"]

        if paragraph_id not in source_lookup:
            logger.error(
                "Retrieved paragraph %s not found in source data",
                paragraph_id
            )
            raise ValueError(
                f"Retrieved paragraph not found: {paragraph_id}"
            )

        resume_paragraphs.append({
            "paragraph_id": paragraph_id,
            "text": source_lookup[paragraph_id],
            "matched_requirements": paragraph["matched_requirements"]
        })

    retrieved_paragraph_ids = [
        paragraph["paragraph_id"]
        for paragraph in resume_paragraphs
    ]

    formatting_record = db.query(ResumeFormatting).filter(
        ResumeFormatting.resume_id == resume_id
    ).first()

    if not formatting_record:
        logger.error(
            "Formatting data missing for resume_id=%s",
            resume_id
        )
        raise ValueError(
            f"No formatting data found for resume_id={resume_id}"
        )

    resume_formatting = extract_rag_formatting(
        formatting_record.formatting_data,
        retrieved_paragraph_ids
    )

    formatting_paragraphs = resume_formatting.get("paragraphs", [])

    logger.info(
        "Context built. Resume paragraphs=%s, formatting paragraphs=%s",
        len(resume_paragraphs),
        len(formatting_paragraphs)
    )

    if not resume_paragraphs:
        logger.warning(
            "No resume paragraphs retrieved for resume_id=%s",
            resume_id
        )

    return {
        "job_requirements": retrieval_data["requirements"],
        "resume_paragraphs": resume_paragraphs,
        "resume_formatting": resume_formatting
    }