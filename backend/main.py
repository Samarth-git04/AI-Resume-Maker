import json
import logging
import shutil

from pathlib import Path
from uuid import uuid4

import faiss
import numpy as np

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from backend.database.dependencies import get_db
from backend.database.database import engine, Base
from backend.database.models import (
    MasterResume,
    ExtractedResume,
    ResumeFormatting,
    ProcessedResume
)

from backend.services.embeddings import (
    CACHE_ROOT as EMBEDDINGS_CACHE_ROOT,
    EmbeddingEngine
)

from backend.services.pdf_generator import create_resume_docx

from backend.services.ri_engine import run_ri_engine

from backend.services.resume_ext import (
    extract_docx_paragraphs,
    extract_docx_formatting,
    remove_nulls
)

from backend.services.retrieval import (
    prepare_resume_cache,
    CACHE_ROOT
)

from backend.services.vector_store import VectorStore

from backend.routers.document_editor import router as document_editor_router

from backend.logging_config import configure_logging


configure_logging()

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(__file__).resolve().parent / "generated"


class JobDescriptionRequest(BaseModel):
    job_description: str = Field(min_length=1)


app = FastAPI(
    title="AI Resume Builder",
    description="An AI-powered resume builder that helps users create professional resumes with ease.",
    version="0.0.1"
)


app.include_router(
    document_editor_router,
    prefix="/documents",
    tags=["Documents"],
)


Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def home():
    return {
        "message": "AI Resume Builder API is running"
    }


@app.get("/resumes/latest")
def get_latest_resume(db: Session = Depends(get_db)):

    resume = db.query(MasterResume).order_by(
        MasterResume.created_at.desc()
    ).first()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No resumes found"
        )

    return resume


@app.get("/resumes/{resume_id}")
def get_resume(
    resume_id: int,
    db: Session = Depends(get_db)
):

    resume = db.query(MasterResume).filter(
        MasterResume.id == resume_id
    ).first()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="Resume not found"
        )

    return resume


@app.post("/resumes/{resume_id}/analyze")
def analyze_resume(
    resume_id: int,
    request: JobDescriptionRequest,
    db: Session = Depends(get_db)
):

    resume = db.query(MasterResume).filter(
        MasterResume.id == resume_id
    ).first()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="Resume not found"
        )

    try:

        result = run_ri_engine(
            db=db,
            resume_id=resume_id,
            job_description=request.job_description
        )

        processed_resume = ProcessedResume(
            resume_id=resume_id,
            job_description=request.job_description,
            processed_data=json.dumps(
                result,
                ensure_ascii=False
            )
        )

        db.add(processed_resume)
        db.commit()
        db.refresh(processed_resume)

        return {
            "processed_resume_id": processed_resume.id,
            "resume_id": resume_id,
            "processed_data": result
        }

    except ValueError as error:

        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except RuntimeError as error:

        db.rollback()

        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    except Exception:

        db.rollback()
        raise


@app.post("/resumes/{resume_id}/generate")
def generate_resume(
    resume_id: int,
    db: Session = Depends(get_db)
):

    resume = db.query(MasterResume).filter(
        MasterResume.id == resume_id
    ).first()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="Resume not found."
        )

    processed_resume = db.query(ProcessedResume).filter(
        ProcessedResume.resume_id == resume_id
    ).order_by(
        ProcessedResume.id.desc()
    ).first()

    if not processed_resume:
        raise HTTPException(
            status_code=404,
            detail="No processed resume found. Analyse the job description first."
        )

    try:

        output_path = create_resume_docx(
            db,
            processed_resume.id
        )

        return {
            "processed_resume_id": processed_resume.id,
            "filename": Path(output_path).name
        }

    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=f"Resume generation failed: {str(error)}"
        )


def verify_resume_index(
    resume_id: int,
    vector_store: VectorStore
):
    cache_dir = CACHE_ROOT / str(resume_id)

    required_files = [
        cache_dir / "chunks.json",
        cache_dir / "chunk_metadata.json",
        cache_dir / "embeddings.npy",
        cache_dir / "embeddings_metadata.json",
        cache_dir / "faiss.index",
        cache_dir / "index_metadata.json",
    ]

    for path in required_files:

        if not path.is_file():

            raise RuntimeError(
                f"Resume indexing incomplete: {path.name} is missing."
            )

    with (cache_dir / "chunks.json").open(
        "r",
        encoding="utf-8"
    ) as file:

        chunks = json.load(file)

    with (cache_dir / "chunk_metadata.json").open(
        "r",
        encoding="utf-8"
    ) as file:

        chunk_metadata = json.load(file)

    with (cache_dir / "embeddings_metadata.json").open(
        "r",
        encoding="utf-8"
    ) as file:

        embedding_metadata = json.load(file)

    with (cache_dir / "index_metadata.json").open(
        "r",
        encoding="utf-8"
    ) as file:

        index_metadata = json.load(file)

    embeddings = np.load(
        cache_dir / "embeddings.npy",
        allow_pickle=False
    )

    if not isinstance(chunks, list) or not chunks:

        raise RuntimeError(
            "Resume indexing produced no valid chunks."
        )

    if embeddings.ndim != 2 or not np.isfinite(embeddings).all():

        raise RuntimeError(
            "Resume embeddings are invalid."
        )

    if len(chunks) != len(embeddings):

        raise RuntimeError(
            "Embedding and chunk counts do not match."
        )

    if (
        chunk_metadata.get("resume_id") != resume_id
        or chunk_metadata.get("chunk_count") != len(chunks)
    ):

        raise RuntimeError(
            "Chunk metadata validation failed."
        )

    if (
        embedding_metadata.get("resume_id") != resume_id
        or embedding_metadata.get("embedding_count") != len(embeddings)
        or embedding_metadata.get("dimensions") != embeddings.shape[1]
    ):

        raise RuntimeError(
            "Embedding metadata validation failed."
        )

    if (
        index_metadata.get("resume_id") != resume_id
        or index_metadata.get("vector_count") != len(chunks)
        or index_metadata.get("dimensions") != embeddings.shape[1]
    ):

        raise RuntimeError(
            "FAISS index metadata validation failed."
        )

    try:

        disk_index = faiss.read_index(
            str(cache_dir / "faiss.index")
        )

    except Exception as error:

        raise RuntimeError(
            "The saved FAISS index could not be loaded."
        ) from error

    if (
        disk_index.ntotal != len(chunks)
        or disk_index.d != embeddings.shape[1]
        or not isinstance(disk_index, faiss.IndexFlatIP)
    ):

        raise RuntimeError(
            "The saved FAISS index is inconsistent with its embeddings."
        )

    if (
        vector_store.index is None
        or vector_store.chunks is None
        or vector_store.index.ntotal != len(chunks)
    ):

        raise RuntimeError(
            "The in-memory FAISS index is not ready."
        )

    test_results = vector_store.search(
        embeddings[0],
        top_k=1
    )

    if not test_results:

        raise RuntimeError(
            "FAISS retrieval verification failed."
        )

    logger.info(
        "Resume RAG verification successful. resume_id=%s chunks=%s vectors=%s",
        resume_id,
        len(chunks),
        disk_index.ntotal
    )

    return True


def remove_resumes(
    resumes: list,
    db: Session
):
    if not resumes:
        return

    file_paths = []
    cache_dirs = []
    generated_files = []

    for resume in resumes:

        file_paths.append(
            Path(resume.file_path)
        )

        cache_dirs.append(
            CACHE_ROOT / str(resume.id)
        )

        processed_records = db.query(ProcessedResume).filter(
            ProcessedResume.resume_id == resume.id
        ).all()

        for processed_record in processed_records:

            generated_files.append(
                GENERATED_DIR / f"resume_{processed_record.id}.docx"
            )

            generated_files.append(
                GENERATED_DIR / f"resume_{processed_record.id}.pdf"
            )

    try:

        for resume in resumes:
            db.delete(resume)

        db.commit()

    except Exception:

        db.rollback()

        logger.exception(
            "Database cleanup failed. Old resume files were retained."
        )

        raise

    for file_path in file_paths:

        try:

            file_path.unlink(missing_ok=True)

        except OSError:

            logger.exception(
                "Could not delete original resume file: %s",
                file_path
            )

    for cache_dir in cache_dirs:

        try:

            if cache_dir.exists():
                shutil.rmtree(cache_dir)

        except OSError:

            logger.exception(
                "Could not delete RAG storage directory: %s",
                cache_dir
            )

    for generated_file in generated_files:

        try:

            generated_file.unlink(missing_ok=True)

        except OSError:

            logger.exception(
                "Could not delete generated resume file: %s",
                generated_file
            )

    logger.info(
        "Old resume cleanup completed. Deleted resume IDs: %s",
        [resume.id for resume in resumes]
    )


def remove_resume(
    resume: MasterResume,
    db: Session
):

    remove_resumes(
        [resume],
        db
    )


@app.post("/resumes/upload")
def upload_resume(
    file: UploadFile = File(...),
    replace: bool = False,
    db: Session = Depends(get_db)
):

    original_filename = Path(
        file.filename or ""
    ).name

    if Path(original_filename).suffix.lower() != ".docx":

        raise HTTPException(
            status_code=400,
            detail="Only DOCX files are currently supported"
        )

    user_id = "samarth"

    existing_resumes = db.query(MasterResume).filter(
        MasterResume.user_id == user_id
    ).all()

    if existing_resumes and not replace:

        return serialize_master_resume(
            max(
                existing_resumes,
                key=lambda resume: resume.created_at
            )
        )

    upload_dir = Path("backend/uploads")
    upload_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    stored_filename = f"{uuid4().hex}.docx"

    file_path = (
        upload_dir / stored_filename
    ).resolve()

    cache_dir = None

    with file_path.open("wb") as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )

    try:

        db_resume = MasterResume(
            user_id=user_id,
            file_name=original_filename,
            file_path=str(file_path)
        )

        db.add(db_resume)
        db.flush()

        paragraphs = extract_docx_paragraphs(
            str(file_path)
        )

        if not paragraphs:

            raise ValueError(
                "No paragraphs could be extracted from the uploaded resume."
            )

        extracted_text = "\n".join(
            paragraph["text"]
            for paragraph in paragraphs
        )

        extracted_data = json.dumps(
            paragraphs,
            separators=(",", ":")
        )

        formatting_data = remove_nulls(
            extract_docx_formatting(
                str(file_path)
            )
        )

        db_extracted = ExtractedResume(
            resume_id=db_resume.id,
            extracted_text=extracted_text,
            extracted_data=extracted_data
        )

        db_formatting = ResumeFormatting(
            resume_id=db_resume.id,
            formatting_data=formatting_data
        )

        db.add_all([
            db_extracted,
            db_formatting
        ])

        db.flush()

        cache_dir = CACHE_ROOT / str(db_resume.id)

        cache_result = prepare_resume_cache(
            db,
            db_resume.id
        )

        if not cache_result.get("chunks"):

            raise RuntimeError(
                "RAG chunk generation failed."
            )

        embedding_engine = EmbeddingEngine()

        embeddings = embedding_engine.generate_embeddings(
            db_resume.id,
            cache_result["chunks"]
        )

        if (
            embeddings is None
            or embeddings.ndim != 2
            or len(embeddings) != len(cache_result["chunks"])
        ):

            raise RuntimeError(
                "Resume embedding generation failed."
            )

        logger.info(
            "Generated embeddings. resume_id=%s shape=%s",
            db_resume.id,
            embeddings.shape
        )

        logger.info(
            "Embedding cache root: %s",
            EMBEDDINGS_CACHE_ROOT
        )

        logger.info(
            "Vector store cache root: %s",
            CACHE_ROOT
        )

        vector_store = VectorStore(
            db_resume.id
        )

        vector_store.prepare()

        verify_resume_index(
            db_resume.id,
            vector_store
        )

        db.commit()
        db.refresh(db_resume)

        logger.info(
            "New resume successfully committed. resume_id=%s",
            db_resume.id
        )

    except Exception:

        db.rollback()

        file_path.unlink(
            missing_ok=True
        )

        if cache_dir and cache_dir.exists():

            shutil.rmtree(
                cache_dir,
                ignore_errors=True
            )

        logger.exception(
            "New resume upload or RAG indexing failed. Existing resumes were retained."
        )

        raise HTTPException(
            status_code=500,
            detail="Resume upload or indexing failed. The previous resume has been retained."
        )

    if existing_resumes:

        remove_resumes(
            existing_resumes,
            db
        )

    return serialize_master_resume(
        db_resume
    )


@app.delete("/resumes/{resume_id}")
def delete_resume(
    resume_id: int,
    db: Session = Depends(get_db)
):

    resume = db.query(MasterResume).filter(
        MasterResume.id == resume_id
    ).first()

    if not resume:

        raise HTTPException(
            status_code=404,
            detail="Resume not found"
        )

    remove_resume(
        resume,
        db
    )

    return {
        "message": "Resume deleted successfully"
    }


@app.get("/health")
def health():

    return {
        "status": "Healthy"
    }


@app.get("/api/health")
def api_health():

    return {
        "status": "connected",
        "message": "Frontend and backend are now connected"
    }


def serialize_master_resume(resume):

    return {
        "user_id": resume.user_id,
        "id": resume.id,
        "file_path": resume.file_path,
        "file_name": resume.file_name,
        "created_at": resume.created_at
    }