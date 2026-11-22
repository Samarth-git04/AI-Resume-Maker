from backend.database.database import SessionLocal
from backend.services.pdf_generator import (
    create_resume_docx,
    convert_to_pdf
)


PROCESSED_RESUME_ID = 1


def test_generate_documents():

    db = SessionLocal()

    try:
        docx_path = create_resume_docx(
            db,
            PROCESSED_RESUME_ID
        )

        print(f"\nGenerated DOCX: {docx_path}")

        pdf_path = convert_to_pdf(docx_path)

        print(f"Generated PDF: {pdf_path}")

    finally:
        db.close()


if __name__ == "__main__":
    test_generate_documents()