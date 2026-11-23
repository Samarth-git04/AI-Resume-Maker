import re

from sqlalchemy.orm import Session

from backend.services.jd_analyzer import extract_requirements, TOP_K
from backend.services.embeddings import EmbeddingEngine
from backend.services.vector_store import VectorStore
from backend.services.retrieval import prepare_resume_cache


MIN_SEMANTIC_SCORE = 0.35
MAX_RESULTS_PER_REQUIREMENT = 5


def _tokens(text):
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9+#.]+", text.lower())
        if len(token) > 1
    }


def _lexical_score(requirement, candidate):
    required = _tokens(requirement)
    available = _tokens(candidate)

    if not required:
        return 0.0

    return len(required & available) / len(required)


def _combined_score(requirement, result):
    semantic = max(0.0, float(result["score"]))
    lexical = _lexical_score(requirement, result["text"])

    # Semantic similarity is the primary signal. Lexical overlap
    # helps distinguish exact technical evidence from broad similarity.
    return (0.75 * semantic) + (0.25 * lexical)


def retrieve_for_job(
    db: Session,
    resume_id: int,
    job_description: str,
):
    requirements = extract_requirements(job_description)

    cache = prepare_resume_cache(db, resume_id)

    embedding_engine = EmbeddingEngine()
    embedding_engine.generate_embeddings(
        resume_id,
        cache["chunks"],
    )

    vector_store = VectorStore(resume_id)
    vector_store.prepare()

    requirement_results = []
    paragraph_map = {}

    for requirement in requirements:
        candidates = []

        if requirement["priority"] != "not_required":
            query_embedding = embedding_engine.encode_query(
                requirement["text"]
            )

            retrieved = vector_store.search(
                query_embedding,
                top_k=TOP_K,
            )

            for item in retrieved:
                combined = _combined_score(
                    requirement["text"],
                    item,
                )

                if (
                    item["score"] < MIN_SEMANTIC_SCORE
                    and combined < 0.30
                ):
                    continue

                candidates.append({
                    **item,
                    "combined_score": combined,
                })

            candidates.sort(
                key=lambda item: item["combined_score"],
                reverse=True,
            )

            candidates = candidates[:MAX_RESULTS_PER_REQUIREMENT]

        matched_ids = []

        for candidate in candidates:
            for paragraph_id in candidate["paragraph_ids"]:
                matched_ids.append(paragraph_id)

                if paragraph_id not in paragraph_map:
                    paragraph_map[paragraph_id] = {
                        "paragraph_id": paragraph_id,
                        "text": candidate["text"],
                        "matched_requirements": [],
                    }

                paragraph_map[paragraph_id]["matched_requirements"].append({
                    "requirement_id": requirement["requirement_id"],
                    "semantic_score": candidate["score"],
                    "lexical_score": _lexical_score(
                        requirement["text"],
                        candidate["text"],
                    ),
                    "combined_score": candidate["combined_score"],
                })

        requirement_results.append({
            "requirement_id": requirement["requirement_id"],
            "requirement": requirement["text"],
            "categories": requirement["categories"],
            "priority": requirement["priority"],
            "retrieved_paragraph_ids": list(dict.fromkeys(matched_ids)),
        })

    return {
        "requirements": requirement_results,
        "unique_paragraphs": list(paragraph_map.values()),
    }