import hashlib 
import json 
import re
import unicodedata

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import ExtractedResume

CACHE_ROOT = Path(__file__).resolve().parents[1] / "rag_storage"

PREPROCESSING_VERSION = "1.0"

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()

def get_source_paragraphs(db: Session, resume_id: int) -> list:
    extracted = db.query(ExtractedResume).filter(
        ExtractedResume.resume_id == resume_id
    ).order_by(
        ExtractedResume.created_at.desc()
    ).first()

    if not extracted:
        raise ValueError(f"No extracted resume found for resume_id={resume_id}")

    if not extracted.extracted_data:
        raise ValueError("Extracted paragraph data is empty")

    try:
        paragraphs = json.loads(extracted.extracted_data)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in extracted_data") from exc

    if not isinstance(paragraphs, list):
        raise TypeError("Extracted data must be a list of paragraphs")

    return paragraphs


def calculate_source_hash(paragraphs: list) -> str:
    source = json.dumps(
        paragraphs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    )

    return hashlib.sha256(source.encode("utf-8")).hexdigest()

def preprocess_paragraphs(paragraphs: list) -> list:
    processed = []
    seen_ids = set()

    for paragraph in paragraphs:
        paragraph_id = paragraph.get("id")
        text = paragraph.get("text")

        if not paragraph_id or not isinstance(text, str):
            raise ValueError("Invalid paragraph structure")

        if paragraph_id in seen_ids:
            raise ValueError(f"Duplicate paragraph ID: {paragraph_id}")

        seen_ids.add(paragraph_id)

        clean_text = normalize_text(text)

        if not clean_text:
            continue

        processed.append({
            "id": paragraph_id,
            "text": clean_text
        })

    return processed


def create_chunks(paragraphs: list) -> list:
    chunks = []

    for index, paragraph in enumerate(paragraphs, start=1):
        chunks.append({
            "chunk_id": f"C{index:05d}",
            "paragraph_ids": [paragraph["id"]],
            "text": paragraph["text"]
        })

    return chunks


def save_json(file_path: Path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = file_path.with_suffix(
        file_path.suffix + ".tmp"
    )

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    temporary_path.replace(file_path)


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)

def prepare_resume_cache(
    db: Session,
    resume_id: int,
    force: bool = False
) -> dict:

    paragraphs = get_source_paragraphs(db, resume_id)

    if not paragraphs:
        raise ValueError(f"No source paragraphs found for resume_id={resume_id}")

    source_hash = calculate_source_hash(paragraphs)

    cache_dir = CACHE_ROOT / str(resume_id)
    cache_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = cache_dir / "chunks.json"
    metadata_path = cache_dir / "chunk_metadata.json"

    if not force and chunks_path.exists() and metadata_path.exists():
        try:
            metadata = load_json(metadata_path)
            chunks = load_json(chunks_path)

            if (
                isinstance(chunks, list)
                and chunks
                and metadata.get("source_hash") == source_hash
                and metadata.get("preprocessing_version") == PREPROCESSING_VERSION
            ):
                return {
                    "cache_hit": True,
                    "resume_id": resume_id,
                    "chunks": chunks,
                    "cache_dir": str(cache_dir)
                }

        except (ValueError, OSError, json.JSONDecodeError):
            pass

    processed_paragraphs = preprocess_paragraphs(paragraphs)
    chunks = create_chunks(processed_paragraphs)

    if not chunks:
        raise ValueError(f"No chunks could be generated for resume_id={resume_id}")

    metadata = {
        "resume_id": resume_id,
        "source_hash": source_hash,
        "preprocessing_version": PREPROCESSING_VERSION,
        "chunking_strategy": "one_paragraph_per_chunk",
        "paragraph_count": len(processed_paragraphs),
        "chunk_count": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    save_json(chunks_path, chunks)
    save_json(metadata_path, metadata)

    return {
        "cache_hit": False,
        "resume_id": resume_id,
        "chunks": chunks,
        "cache_dir": str(cache_dir)
    }