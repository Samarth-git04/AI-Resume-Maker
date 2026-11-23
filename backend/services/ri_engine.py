import logging

from sqlalchemy.orm import Session

from backend.services.context_builder import build_ai_context
from backend.services.resume_generator import generate_resume
from backend.services.resume_structure import build_resume_structure


logger = logging.getLogger(__name__)


def run_ri_engine(
    db: Session,
    resume_id: int,
    job_description: str,
):
    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    context = build_ai_context(
        db,
        resume_id,
        job_description,
    )

    paragraphs = context["resume_paragraphs"]

    if len(paragraphs) < 2:
        raise ValueError(
            "The uploaded resume does not contain enough usable content."
        )

    structure = build_resume_structure(
        paragraphs,
        context["resume_formatting"],
    )

    if not structure["records"]:
        raise ValueError("Could not identify resume content.")

    result = generate_resume(
        context,
        structure,
    )

    logger.info(
        "Resume tailoring completed. resume_id=%s "
        "selected_projects=%d selected_achievements=%d decisions=%d",
        resume_id,
        len(result["selected_project_ids"]),
        len(result["selected_achievement_ids"]),
        len(result["paragraph_decisions"]),
    )

    return result