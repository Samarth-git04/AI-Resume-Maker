from backend.database.database import SessionLocal
from backend.database.models import ResumeFormatting

from backend.services.jd_retrieval import retrieve_for_job
from backend.services.retrieval import get_source_paragraphs
from backend.services.resume_ext import extract_rag_formatting


def build_ai_context(resume_id: int, job_description: str) -> dict:

    retrieval_data = retrieve_for_job(
        resume_id,
        job_description
    )

    db = SessionLocal()

    try:
        source_paragraphs = get_source_paragraphs(
            db,
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
            raise ValueError(
                f"No formatting data found for resume_id={resume_id}"
            )

        resume_formatting = extract_rag_formatting(
            formatting_record.formatting_data,
            retrieved_paragraph_ids
        )

        return {
            "job_requirements": retrieval_data["requirements"],
            "resume_paragraphs": resume_paragraphs,
            "resume_formatting": resume_formatting
        }

    finally:
        db.close()