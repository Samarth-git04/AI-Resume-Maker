from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from backend.database.database import Base
from sqlalchemy.orm import relationship

class MasterResume(Base):
    __tablename__ = "master_resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    extracted_resumes = relationship(
        "ExtractedResume",
        back_populates="master_resume",
        cascade="all, delete-orphan"
    )
    processed_resumes = relationship(
        "ProcessedResume",
        back_populates="master_resume",
        cascade="all, delete-orphan"
    )
    resume_formatting = relationship(
        "ResumeFormatting",
        back_populates="master_resume",
        cascade="all, delete-orphan",
        uselist=False
    )

class ExtractedResume(Base):
    __tablename__ = "extracted_resumes"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("master_resumes.id"), nullable=False)
    extracted_text = Column(String, nullable=False)
    extracted_data = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    master_resume = relationship("MasterResume", back_populates="extracted_resumes")

class ProcessedResume(Base):
    __tablename__ = "processed_resumes"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("master_resumes.id"), nullable=False)
    job_description = Column(String, nullable=True)
    processed_data = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    master_resume = relationship("MasterResume", back_populates="processed_resumes")

class ResumeFormatting(Base):
    __tablename__ = "resume_formatting"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(
        Integer,
        ForeignKey("master_resumes.id"),
        nullable=False,
        unique=True
    )
    formatting_data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    master_resume = relationship(
        "MasterResume",
        back_populates="resume_formatting"
    )