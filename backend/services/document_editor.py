import jwt
from uuid import uuid4
from pathlib import Path

from backend.config import (
    ONLYOFFICE_JWT_SECRET,
    BACKEND_INTERNAL_URL,
)

from urllib.parse import quote


GENERATED_DIR = Path(__file__).resolve().parent.parent / "generated"


def generate_editor_config(filename: str):
    file_path = GENERATED_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError("Generated document not found")

    document_key = str(uuid4())

    config = {
        "document": {
            "fileType": "docx",
            "key": document_key,
            "title": filename,
            "url": f"{BACKEND_INTERNAL_URL}/documents/{filename}",
            "permissions": {
                "edit": True,
                "download": True,
            },
        },
        "documentType": "word",
        "editorConfig": {
            "mode": "edit",
            "callbackUrl": (
                f"{BACKEND_INTERNAL_URL}/documents/callback"
                f"?filename={quote(filename)}"
            ),
            "user": {
                "id": "samarth",
                "name": "User",
            },
        },
    }

    config["token"] = jwt.encode(
        config,
        ONLYOFFICE_JWT_SECRET,
        algorithm="HS256",
    )

    return config