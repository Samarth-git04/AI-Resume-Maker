# AI Resume Builder

An AI-powered resume intelligence and generation platform that analyses job descriptions, retrieves relevant experience from a user's existing resumes, and generates tailored resumes while preserving the original document's structure and formatting.

The project combines **Retrieval-Augmented Generation (RAG)**, **FAISS vector search**, **Large Language Models (LLMs)**, and document-processing technologies to make resume customisation more structured, relevant, and efficient.

---

# 1. Project Structure

The project is organised into separate backend and frontend applications, with dedicated modules for document processing, retrieval, AI analysis, and resume generation.

```text
AI Resume Website/
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   │
│   ├── database/
│   │   ├── database.py
│   │   ├── dependencies.py
│   │   └── models.py
│   │
│   ├── routers/
│   │   ├── document_editor.py
│   │   ├── resume.py
│   │   ├── jobs.py
│   │   └── applications.py
│   │
│   ├── schemas/
│   │   ├── job.py
│   │   └── resume.py
│   │
│   ├── services/
│   │   ├── context_builder.py
│   │   ├── document_editor.py
│   │   ├── embeddings.py
│   │   ├── jd_analyzer.py
│   │   ├── jd_retrieval.py
│   │   ├── llm_service.py
│   │   ├── pdf_generator.py
│   │   ├── resume_ext.py
│   │   ├── resume_generator.py
│   │   ├── retrieval.py
│   │   ├── ri_engine.py
│   │   └── vector_store.py
│   │
│   ├── tests/
│   │   ├── test_context_builder.py
│   │   ├── test_embeddings.py
│   │   ├── test_jd_analyzer.py
│   │   ├── test_jd_retrieval.py
│   │   ├── test_llm_service.py
│   │   └── test_pdf_generator.py
│   │
│   ├── rag_storage/
│   │   └── [Cached FAISS indexes and related data]
│   │
│   └── generated/
│       └── [Generated resume documents]
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   │       └── DocumentEditor.jsx
│   │
│   ├── public/
│   ├── package.json
│   └── index.html
│
├── resume_intelligence.db
├── docker-compose.yml
├── onlyoffice.env.example
├── package.json
├── package-lock.json
├── .gitignore
└── README.md
```

## 1.1 Backend

The backend is built with **FastAPI** and follows a modular architecture. It separates API endpoints, database operations, data validation, and core application logic.

### Core Files

| File | Responsibility |
|---|---|
| `main.py` | Initialises the FastAPI application, registers routers, configures CORS, and exposes health-check endpoints. |
| `config.py` | Manages application configuration and environment variables. |
| `requirements.txt` | Contains the Python dependencies required by the backend. |

### Database

The `database/` directory contains the database configuration and ORM models.

| File | Responsibility |
|---|---|
| `database.py` | Creates the SQLAlchemy engine and database session configuration. |
| `dependencies.py` | Provides database sessions to API endpoints through FastAPI dependencies. |
| `models.py` | Defines the SQLAlchemy database models. |

### API Routers

The `routers/` directory contains the application's API endpoints.

| Router | Responsibility |
|---|---|
| `resume.py` | Handles resume uploads, extraction, and resume-related operations. |
| `jobs.py` | Handles job descriptions and job-related operations. |
| `applications.py` | Manages job application records and related operations. |
| `document_editor.py` | Handles document editing and ONLYOFFICE integration. |

### Schemas

The `schemas/` directory defines Pydantic models used for request validation and response serialization.

| File | Responsibility |
|---|---|
| `job.py` | Defines validation schemas for job-related requests and responses. |
| `resume.py` | Defines validation schemas for resume-related requests and responses. |

## 1.2 Backend Services

The `services/` directory contains the core business logic of the application. Each module is responsible for a specific stage of the resume intelligence and generation workflow.

| Service | Responsibility |
|---|---|
| `resume_ext.py` | Extracts text, paragraphs, and formatting information from uploaded DOCX resumes. |
| `embeddings.py` | Generates vector embeddings using Sentence Transformers. |
| `vector_store.py` | Manages FAISS indexes and vector storage operations. |
| `jd_analyzer.py` | Analyses job descriptions and extracts structured job requirements. |
| `jd_retrieval.py` | Retrieves relevant resume paragraphs for individual job requirements using FAISS. |
| `retrieval.py` | Handles resume-related retrieval operations. |
| `context_builder.py` | Constructs structured context from retrieved resume content for the LLM. |
| `llm_service.py` | Handles communication with the Groq API and LLM operations. |
| `ri_engine.py` | Orchestrates the Resume Intelligence workflow, connecting analysis, retrieval, context construction, and generation. |
| `resume_generator.py` | Generates tailored DOCX resumes while retaining paragraph identifiers and original formatting. |
| `pdf_generator.py` | Converts generated DOCX documents into PDF files using LibreOffice. |
| `document_editor.py` | Provides the backend integration for the ONLYOFFICE document editor. |

## 1.3 Database and Storage

The application uses **SQLite** with **SQLAlchemy** for persistent data storage.

The database file is located in the project root:

    resume_intelligence.db

The database stores structured information associated with resumes, extracted content, formatting metadata, job descriptions, and other application data.

### FAISS Storage

FAISS indexes and related cached retrieval data are stored separately from the SQLite database:

    backend/rag_storage/

This allows the application to reuse previously generated vector indexes rather than rebuilding them unnecessarily.

### Generated Documents

Generated resume documents are stored in:

    backend/generated/

This directory contains output files produced during the resume generation and document conversion workflows.

## 1.4 Frontend

The frontend is built using **React** and **Vite**.

| File / Directory | Responsibility |
|---|---|
| `src/App.jsx` | Main React application component. |
| `src/components/DocumentEditor.jsx` | Integrates the ONLYOFFICE document editor into the React application. |
| `public/` | Stores static frontend assets. |
| `package.json` | Defines frontend dependencies and scripts. |
| `index.html` | Main HTML entry point for the Vite application. |

### Document Editing

The application integrates **ONLYOFFICE Document Server** through the React document editor component.

This provides an interface for editing generated resume documents while retaining the document's editable structure.

---

# 2. Installation and Replication

Follow the steps below to set up the project locally.

## 2.1 Prerequisites

Ensure the following software is installed:

- Python 3.10 or later
- Node.js and npm
- Git
- Docker and Docker Compose
- LibreOffice
- A Groq API key

The backend uses LibreOffice for DOCX-to-PDF conversion, while Docker is used to run the ONLYOFFICE Document Server.

## 2.2 Clone the Repository

Clone the repository and navigate to the project directory:

    git clone <repository-url>
    cd "AI Resume Website"

Replace `<repository-url>` with the repository's Git URL.

## 2.3 Backend Setup

Create and activate a Python virtual environment:

    python -m venv .venv

On Linux:

    source .venv/bin/activate

On Windows:

    .venv\Scripts\activate

Install the backend dependencies:

    pip install -r backend/requirements.txt

## 2.4 Environment Configuration

Configure the environment variables required by the backend.

Create an appropriate environment file based on the variables read by `backend/config.py`.

At minimum, configure the Groq API key:

    GROQ_API_KEY=your_groq_api_key

Do not commit API keys or other secrets to the repository.

## 2.5 Database Setup

The application uses SQLite.

The database file is located in the project root:

    resume_intelligence.db

Ensure the application has permission to read and write to the project directory.

Database tables are managed through the SQLAlchemy models and database initialisation logic.

## 2.6 Start the Backend

From the project root, activate the virtual environment and run:

    uvicorn backend.main:app --reload

The backend should be accessible at:

    http://localhost:8000

FastAPI's interactive API documentation is available at:

    http://localhost:8000/docs

## 2.7 Frontend Setup

Open a separate terminal and navigate to the frontend directory:

    cd frontend

Install the dependencies:

    npm install

Start the Vite development server:

    npm run dev

The frontend should be accessible at:

    http://localhost:5173

## 2.8 Start ONLYOFFICE Document Server

The project includes a Docker Compose configuration for running ONLYOFFICE Document Server.

From the project root, configure the required environment variables using the provided example configuration:

    onlyoffice.env.example

Start the service:

    docker compose up -d

The Document Server is configured to run locally at:

    http://localhost:8080

Ensure that the frontend and backend can communicate with the Document Server using the configured URLs.

## 2.9 Running Tests

The backend includes tests for several core services.

Run the complete test suite from the project root:

    python -m pytest backend/tests/

Individual test modules can also be executed separately:

    python -m pytest backend/tests/test_embeddings.py
    python -m pytest backend/tests/test_jd_analyzer.py
    python -m pytest backend/tests/test_jd_retrieval.py
    python -m pytest backend/tests/test_context_builder.py
    python -m pytest backend/tests/test_llm_service.py
    python -m pytest backend/tests/test_pdf_generator.py

Some tests may require environment variables, external API access, or local dependencies to be configured.

---

# 3. System Architecture

The application follows a Retrieval-Augmented Generation (RAG) architecture.

Instead of sending an entire collection of resumes directly to an LLM, the system first analyses the job description, retrieves relevant resume content, and constructs a focused context for generation.

The workflow is divided into the following stages:

1. Resume ingestion and extraction.
2. Resume content processing and embedding generation.
3. Job description analysis.
4. Requirement-based vector retrieval.
5. Context construction.
6. LLM-assisted resume generation.
7. DOCX formatting and PDF conversion.

## 3.1 High-Level Workflow

    Existing Resumes (DOCX)
             |
             v
    Resume Extraction
             |
             v
    Paragraphs + Formatting Metadata
             |
             v
    Embedding Generation
             |
             v
    FAISS Vector Store
             |
             |
    Job Description
             |
             v
    Job Description Analyzer
             |
             v
    Structured Requirements
             |
             v
    Requirement-Based Retrieval
             |
             v
    Relevant Resume Paragraphs
             |
             v
    Context Builder
             |
             v
    Groq LLM
             |
             v
    Resume Intelligence Engine
             |
             v
    DOCX Resume Generation
             |
             v
    PDF Conversion

## 3.2 Resume Ingestion and Extraction

The first stage processes the user's existing DOCX resumes.

The extraction service:

- Reads the uploaded DOCX document.
- Extracts paragraph-level text.
- Assigns identifiers to extracted paragraphs.
- Captures relevant formatting metadata.
- Makes the extracted content available for downstream processing.

Paragraph-level extraction is important because the system needs to retrieve and reorganise individual pieces of experience rather than treating an entire resume as one document.

## 3.3 Embedding Generation

Extracted resume content is converted into numerical vector representations using Sentence Transformers.

The embedding model used by the project is:

    BAAI/bge-base-en-v1.5

The model produces 768-dimensional embeddings.

These vectors allow the application to compare the semantic meaning of job requirements and resume paragraphs.

## 3.4 FAISS Vector Store

The application uses **FAISS (Facebook AI Similarity Search)** to perform efficient similarity searches over the generated embeddings.

The configured index uses:

    IndexFlatIP

Vectors are L2-normalised before inner-product similarity search so that the resulting scores correspond to cosine similarity.

The vector store supports retrieving resume paragraphs that are semantically relevant to a particular job requirement.

## 3.5 Job Description Analysis

The job description analyzer processes the supplied job description and extracts structured requirements.

These requirements represent the skills, responsibilities, qualifications, and experience sought by the employer.

The structured output provides the basis for requirement-wise retrieval rather than relying on a single similarity search against the entire job description.

## 3.6 Requirement-Based Retrieval

The JD retrieval service searches the FAISS index separately for each extracted requirement.

The retrieval configuration supports a configurable `TOP_K` value, with the target set to five results per requirement.

This approach allows the system to retrieve relevant resume content across multiple requirements without imposing a global result limit.

Duplicate paragraphs can be consolidated while retaining their associated requirement identifiers, retrieval ranks, and similarity scores.

## 3.7 Context Construction

The context builder organises the retrieved paragraphs into structured information for the LLM.

This stage is intended to keep the model's input focused on relevant evidence from the user's existing resumes.

The context retains paragraph identifiers so that selected content can later be mapped back to its original formatting metadata.

## 3.8 LLM Integration

The application integrates with the Groq API to perform LLM-assisted resume analysis and generation.

The LLM receives the structured job requirements and retrieved resume content.

Its role is to select and, where appropriate, rewrite relevant experience while keeping the generated content grounded in the user's existing information.

## 3.9 Resume Generation

The resume intelligence engine coordinates the final generation process.

The generation design follows these principles:

- The header is taken from the first resume and remains fixed.
- The header is excluded from the body retrieval and rewriting process.
- Only AI-selected body paragraphs are included in the generated resume.
- Unselected paragraphs are excluded rather than automatically reinserted.
- Original paragraph identifiers are retained to map content back to its formatting metadata.
- The generated document preserves the original paragraph formatting wherever supported by the generation process.

The result is a tailored resume that prioritises relevant experience while retaining the structure and formatting of the source document.

## 3.10 Document Export

The generated resume is produced as a DOCX document.

The PDF generation service uses headless LibreOffice to convert the DOCX output into PDF format.

This provides an additional export format for applications and sharing.

---

# 4. Technology Stack

| Category | Technology | Purpose |
|---|---|---|
| Backend | Python | Core application logic |
| API Framework | FastAPI | REST API development |
| Database | SQLite | Persistent application data |
| ORM | SQLAlchemy | Database operations and model management |
| Data Validation | Pydantic | Request and response validation |
| Frontend | React | User interface |
| Frontend Tooling | Vite | Frontend development and bundling |
| Embeddings | Sentence Transformers | Semantic vector generation |
| Embedding Model | BAAI/bge-base-en-v1.5 | Resume content embeddings |
| Vector Search | FAISS | Similarity-based retrieval |
| LLM | Groq API | AI-assisted analysis and generation |
| Document Processing | python-docx | DOCX extraction and generation |
| PDF Conversion | LibreOffice | DOCX-to-PDF conversion |
| Document Editor | ONLYOFFICE | Browser-based document editing |
| Containerisation | Docker Compose | Local ONLYOFFICE deployment |
| Testing | pytest | Backend testing |

---

# 5. Current Development Status

The project is being developed incrementally, with individual services and integration points tested as they are implemented.

The following components have been developed or exercised during testing:

- DOCX resume extraction.
- Paragraph-level content processing.
- Formatting metadata extraction.
- Embedding generation.
- FAISS index creation and loading.
- Structured job description requirement extraction.
- Requirement-wise FAISS retrieval.
- Duplicate paragraph handling.
- SQLite and SQLAlchemy integration.
- Backend API development.
- Frontend and ONLYOFFICE integration work.
- DOCX and PDF generation components.

The complete end-to-end workflow, including successful LLM-assisted generation and final formatting validation, remains subject to integration testing.

---

# 6. Future Improvements

Potential areas for further development include:

- Improving the accuracy of job requirement extraction.
- Evaluating retrieval quality across different resume formats and job descriptions.
- Improving LLM output validation and content-grounding checks.
- Expanding automated integration testing.
- Improving document formatting consistency across generated resumes.
- Strengthening API authentication and application security.
- Improving deployment configuration for production environments.
- Adding workflow monitoring and usage analytics.

---

# 7. License

This project is currently under development. Licensing information will be added when the project's distribution terms are finalised.