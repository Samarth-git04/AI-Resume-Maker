import hashlib
import logging
import urllib.request

import jwt

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import ONLYOFFICE_JWT_SECRET
from backend.database.dependencies import get_db
from backend.database.models import ProcessedResume
from backend.services.document_editor import (
    GENERATED_DIR,
    generate_editor_config,
)
from backend.services.pdf_generator import create_resume_docx


logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate/{processed_resume_id}")
async def generate_processed_document(
    processed_resume_id: int,
    db: Session = Depends(get_db),
):
    processed = (
        db.query(ProcessedResume)
        .filter(ProcessedResume.id == processed_resume_id)
        .first()
    )

    if not processed:
        logger.warning(
            "Document generation rejected. processed_resume_id=%s not_found=true",
            processed_resume_id,
        )
        raise HTTPException(
            status_code=404,
            detail="Processed resume not found.",
        )

    jd_hash = hashlib.sha256(
        (processed.job_description or "").encode("utf-8")
    ).hexdigest()[:12]

    logger.info(
        "Document generation started. processed_resume_id=%s "
        "resume_id=%s jd_hash=%s",
        processed.id,
        processed.resume_id,
        jd_hash,
    )

    try:
        output_path = create_resume_docx(
            db,
            processed.id,
        )

        filename = Path(output_path).name

        logger.info(
            "Document generation completed. processed_resume_id=%s "
            "resume_id=%s filename=%s",
            processed.id,
            processed.resume_id,
            filename,
        )

        return {
            "processed_resume_id": processed.id,
            "resume_id": processed.resume_id,
            "filename": filename,
        }

    except ValueError as error:
        logger.exception(
            "Document generation validation failed. processed_resume_id=%s",
            processed.id,
        )
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    except Exception:
        logger.exception(
            "Document generation failed. processed_resume_id=%s",
            processed.id,
        )
        raise HTTPException(
            status_code=500,
            detail="Resume generation failed. Check the backend logs.",
        )


@router.get("/{filename}")
async def get_document(filename: str):
    filename = Path(filename).name
    file_path = GENERATED_DIR / filename

    if not file_path.is_file():
        logger.warning(
            "Document download failed. filename=%s",
            filename,
        )
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    logger.info(
        "Document download requested. filename=%s",
        filename,
    )

    return FileResponse(
        file_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=filename,
    )


@router.post("/callback")
async def document_callback(
    request: Request,
    filename: str = Query(...),
):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()

    if not token:
        logger.warning(
            "ONLYOFFICE callback rejected. filename=%s reason=missing_jwt",
            Path(filename).name,
        )
        raise HTTPException(
            status_code=401,
            detail="Missing JWT",
        )

    try:
        claims = jwt.decode(
            token,
            ONLYOFFICE_JWT_SECRET,
            algorithms=["HS256"],
        )
    except jwt.InvalidTokenError as error:
        logger.warning(
            "ONLYOFFICE callback rejected. filename=%s reason=invalid_jwt type=%s",
            Path(filename).name,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid JWT",
        )

    data = await request.json()
    signed_data = claims.get("payload")

    if not isinstance(signed_data, dict):
        raise HTTPException(
            status_code=401,
            detail="Invalid JWT payload",
        )

    mismatches = [
        key
        for key, value in data.items()
        if key != "token" and signed_data.get(key) != value
    ]

    if mismatches:
        logger.warning(
            "ONLYOFFICE callback rejected. filename=%s mismatched_keys=%s",
            Path(filename).name,
            mismatches,
        )
        raise HTTPException(
            status_code=401,
            detail="Callback payload mismatch",
        )

    status = data.get("status")

    logger.info(
        "ONLYOFFICE callback received. filename=%s status=%s",
        Path(filename).name,
        status,
    )

    if status not in (2, 6):
        return {"error": 0}

    document_url = data.get("url")

    if not document_url:
        raise HTTPException(
            status_code=400,
            detail="Missing document URL",
        )

    filename = Path(filename).name
    file_path = GENERATED_DIR / filename
    temporary_path = file_path.with_suffix(".tmp")

    try:
        urllib.request.urlretrieve(
            document_url,
            temporary_path,
        )
        temporary_path.replace(file_path)

        logger.info(
            "ONLYOFFICE document saved. filename=%s size_bytes=%d",
            filename,
            file_path.stat().st_size,
        )

    except Exception:
        temporary_path.unlink(missing_ok=True)

        logger.exception(
            "ONLYOFFICE document save failed. filename=%s",
            filename,
        )

        raise HTTPException(
            status_code=500,
            detail="Document save failed",
        )

    return {"error": 0}


@router.get("/config/{filename}")
async def get_editor_config(filename: str):
    filename = Path(filename).name

    try:
        return generate_editor_config(filename)

    except FileNotFoundError:
        logger.warning(
            "ONLYOFFICE editor config requested for missing file. filename=%s",
            filename,
        )
        raise HTTPException(
            status_code=404,
            detail="Generated document not found",
        )