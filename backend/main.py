import json
import shutil

from pathlib import Path
from uuid import uuid4

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
from backend.services.embeddings import CACHE_ROOT as EMBEDDINGS_CACHE_ROOT
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
from backend.services.embeddings import EmbeddingEngine
from backend.services.vector_store import VectorStore

from backend.routers.document_editor import router as document_editor_router

from backend.logging_config import configure_logging

configure_logging()

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
    return {"message": "AI Resume Builder API is running"}


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
def get_resume(resume_id: int, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=400, detail=str(error))

    except RuntimeError as error:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(error))

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

def remove_resumes(resumes: list, db: Session):
    file_paths = [Path(resume.file_path) for resume in resumes]
    cache_dirs = [
        CACHE_ROOT / str(resume.id)
        for resume in resumes
    ]

    for resume in resumes:
        db.delete(resume)

    db.commit()

    for file_path in file_paths:
        file_path.unlink(missing_ok=True)

    for cache_dir in cache_dirs:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)


def remove_resume(resume: MasterResume, db: Session):
    remove_resumes([resume], db)

@app.post("/resumes/upload")
def upload_resume(
    file: UploadFile = File(...),
    replace: bool = False,
    db: Session = Depends(get_db)
):
    original_filename = Path(file.filename or "").name

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
            max(existing_resumes, key=lambda resume: resume.created_at)
        )

    upload_dir = Path("backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_filename = f"{uuid4().hex}.docx"
    file_path = (upload_dir / stored_filename).resolve()

    cache_dir = None

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        db_resume = MasterResume(
            user_id=user_id,
            file_name=original_filename,
            file_path=str(file_path)
        )

        db.add(db_resume)
        db.flush()

        paragraphs = extract_docx_paragraphs(str(file_path))

        extracted_text = "\n".join(
            paragraph["text"]
            for paragraph in paragraphs
        )

        extracted_data = json.dumps(
            paragraphs,
            separators=(",", ":")
        )

        formatting_data = remove_nulls(
            extract_docx_formatting(str(file_path))
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

        embedding_engine = EmbeddingEngine()

        embeddings = embedding_engine.generate_embeddings(
            db_resume.id,
            cache_result["chunks"]
        )

        print("Generated shape:", embeddings.shape)
        print("Embedding cache root:", EMBEDDINGS_CACHE_ROOT)
        print("Vector store cache root:", CACHE_ROOT)
        print("Embedding file:", EMBEDDINGS_CACHE_ROOT / str(db_resume.id) / "embeddings.npy")
        print("Embedding file exists:", (EMBEDDINGS_CACHE_ROOT / str(db_resume.id) / "embeddings.npy").exists())

        vector_store = VectorStore(db_resume.id)
        vector_store.prepare()

        db.commit()
        db.refresh(db_resume)

    except Exception:
        db.rollback()
        file_path.unlink(missing_ok=True)

        if cache_dir and cache_dir.exists():
            shutil.rmtree(cache_dir)

        raise

    if existing_resumes:
        remove_resumes(existing_resumes, db)

    return serialize_master_resume(db_resume)

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

    remove_resume(resume, db)

    return {"message": "Resume deleted successfully"}


@app.get("/health")
def health():
    return {"status": "Healthy"}


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