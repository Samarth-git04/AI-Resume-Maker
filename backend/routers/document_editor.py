import jwt
import urllib.request

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend.config import ONLYOFFICE_JWT_SECRET
from backend.services.document_editor import (
    GENERATED_DIR,
    generate_editor_config,
)


router = APIRouter()


@router.get("/{filename}")
async def get_document(filename: str):
    filename = Path(filename).name
    file_path = GENERATED_DIR / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
        print("Callback error: Authorization header missing")
        raise HTTPException(status_code=401, detail="Missing JWT")

    try:
        claims = jwt.decode(
            token,
            ONLYOFFICE_JWT_SECRET,
            algorithms=["HS256"],
        )
    except jwt.InvalidTokenError as exc:
        print(f"Callback JWT error: {type(exc).__name__}")
        raise HTTPException(status_code=401, detail="Invalid JWT")

    data = await request.json()
    signed_data = claims.get("payload")

    print("JWT top-level keys:", list(claims.keys()))
    print(
        "JWT payload keys:",
        list(signed_data.keys()) if isinstance(signed_data, dict) else None,
    )
    print("Callback body keys:", list(data.keys()))

    if not isinstance(signed_data, dict):
        raise HTTPException(status_code=401, detail="Invalid JWT payload")

    mismatches = [
        key for key, value in data.items()
        if key != "token" and signed_data.get(key) != value
    ]

    if mismatches:
        print("Callback payload mismatches:", mismatches)
        raise HTTPException(status_code=401, detail="Callback payload mismatch")

    status = data.get("status")
    print("ONLYOFFICE callback status:", status)

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
        urllib.request.urlretrieve(document_url, temporary_path)
        temporary_path.replace(file_path)

        print("Document saved successfully:", file_path)
        print("Saved file size:", file_path.stat().st_size)

    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        print("Document save error:", str(exc))
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
        raise HTTPException(
            status_code=404,
            detail="Generated document not found",
        )