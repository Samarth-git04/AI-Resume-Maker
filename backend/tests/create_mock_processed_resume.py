import json

from backend.database.database import SessionLocal
from backend.database.models import (
    MasterResume,
    ProcessedResume
)


RESUME_ID = 1 # Replace with your existing resume ID


def create_mock():

    db = SessionLocal()

    try:
        resume = db.query(MasterResume).filter(
            MasterResume.id == RESUME_ID
        ).first()

        if not resume:
            raise ValueError("Master resume not found.")

        processed_data = {
            "professional_summary": (
                "A motivated professional with experience in "
                "data analysis, programming and statistical modelling."
            ),
            "tailored_paragraphs": [
                {
                    "paragraph_id": "P1",
                    "rewritten_text": "Mock rewritten paragraph.",
                    "matched_requirements": ["R001"]
                }
            ],
            "omitted_paragraph_ids": ["P5"],
            "changes_summary": [
                "Rewritten P1 for improved job relevance.",
                "Omitted P5 as it was not relevant."
            ]
        }

        record = ProcessedResume(
            resume_id=RESUME_ID,
            job_description="Mock job description for testing.",
            processed_data=json.dumps(
                processed_data,
                ensure_ascii=False
            )
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        print(f"Mock ProcessedResume created: {record.id}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    create_mock()