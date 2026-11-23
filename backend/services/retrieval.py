import hashlib
import json
import re
import unicodedata

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import ExtractedResume
from backend.services.resume_structure import build_resume_structure


CACHE_ROOT = Path(__file__).resolve().parents[1] / "rag_storage"
PREPROCESSING_VERSION = "3.0"


def normalize_text(text):
    text = unicodedata.normalize("NFC", str(text or ""))
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def get_source_paragraphs(db: Session, resume_id: int):
    extracted = (
        db.query(ExtractedResume)
        .filter(ExtractedResume.resume_id == resume_id)
        .order_by(ExtractedResume.id.desc())
        .first()
    )

    if not extracted or not extracted.extracted_data:
        raise ValueError(
            f"No extracted resume found for resume_id={resume_id}"
        )

    try:
        paragraphs = json.loads(extracted.extracted_data)
    except json.JSONDecodeError as error:
        raise ValueError("Invalid JSON in extracted_data.") from error

    if not isinstance(paragraphs, list):
        raise ValueError("Extracted data must be a list.")

    return paragraphs


def calculate_source_hash(paragraphs):
    source = json.dumps(
        paragraphs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _section_map(paragraphs):
    section_by_id = {}
    current_section = None

    for item in paragraphs:
        text = normalize_text(item.get("text", ""))
        paragraph_id = item.get("id")

        if not paragraph_id or not text:
            continue

        from backend.services.resume_structure import canonical_section

        section = canonical_section(text)

        if section:
            current_section = section

        section_by_id[paragraph_id] = current_section or "GENERAL"

    return section_by_id


def preprocess_paragraphs(paragraphs):
    processed = []
    seen_ids = set()

    for item in paragraphs:
        if not isinstance(item, dict):
            raise ValueError("Invalid paragraph structure.")

        paragraph_id = item.get("id")
        text = normalize_text(item.get("text"))

        if not paragraph_id or not text:
            continue

        if paragraph_id in seen_ids:
            raise ValueError(f"Duplicate paragraph ID: {paragraph_id}")

        seen_ids.add(paragraph_id)

        processed.append({
            "id": paragraph_id,
            "text": text,
        })

    return processed


def create_chunks(paragraphs, section_by_id=None):
    section_by_id = section_by_id or {}
    chunks = []

    for index, paragraph in enumerate(paragraphs, start=1):
        section = section_by_id.get(paragraph["id"], "GENERAL")

        chunks.append({
            "chunk_id": f"C{index:05d}",
            "paragraph_ids": [paragraph["id"]],
            "section": section,
            "text": paragraph["text"],
            "embedding_text": (
                f"Resume section: {section}. "
                f"Candidate evidence: {paragraph['text']}"
            ),
        })

    return chunks


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    temporary.replace(path)


def _load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def prepare_resume_cache(db, resume_id, force=False):
    source_paragraphs = get_source_paragraphs(db, resume_id)

    if not source_paragraphs:
        raise ValueError("No source paragraphs are available.")

    source_hash = calculate_source_hash(source_paragraphs)

    cache_dir = CACHE_ROOT / str(resume_id)
    cache_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = cache_dir / "chunks.json"
    metadata_path = cache_dir / "chunk_metadata.json"

    if not force and chunks_path.exists() and metadata_path.exists():
        try:
            metadata = _load_json(metadata_path)
            chunks = _load_json(chunks_path)

            if (
                isinstance(chunks, list)
                and chunks
                and metadata.get("source_hash") == source_hash
                and metadata.get("preprocessing_version")
                == PREPROCESSING_VERSION
            ):
                return {
                    "cache_hit": True,
                    "resume_id": resume_id,
                    "chunks": chunks,
                    "cache_dir": str(cache_dir),
                }

        except (OSError, ValueError, json.JSONDecodeError):
            pass

    processed = preprocess_paragraphs(source_paragraphs)
    section_by_id = _section_map(source_paragraphs)

    chunks = create_chunks(processed, section_by_id)

    if not chunks:
        raise ValueError("No resume chunks could be generated.")

    metadata = {
        "resume_id": resume_id,
        "source_hash": source_hash,
        "preprocessing_version": PREPROCESSING_VERSION,
        "chunking_strategy": "context_enriched_paragraph",
        "paragraph_count": len(processed),
        "chunk_count": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    _save_json(chunks_path, chunks)
    _save_json(metadata_path, metadata)

    return {
        "cache_hit": False,
        "resume_id": resume_id,
        "chunks": chunks,
        "cache_dir": str(cache_dir),
    }