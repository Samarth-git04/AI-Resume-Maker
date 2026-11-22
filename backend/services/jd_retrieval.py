from backend.services.jd_analyzer import extract_requirements, TOP_K
from backend.services.embeddings import EmbeddingEngine
from backend.services.vector_store import VectorStore


def retrieve_for_job(resume_id: int, job_description: str) -> dict:

    requirements = extract_requirements(job_description)

    embedding_engine = EmbeddingEngine()
    vector_store = VectorStore(resume_id)

    vector_store.prepare()

    requirement_results = []
    paragraph_map = {}

    for requirement in requirements:

        retrieved_paragraphs = []

        if requirement["priority"] != "not_required":

            query_embedding = embedding_engine.encode_query(
                requirement["text"]
            )

            retrieved_paragraphs = vector_store.search(
                query_embedding,
                top_k=TOP_K
            )

        matched_paragraph_ids = []

        for paragraph in retrieved_paragraphs:

            for paragraph_id in paragraph["paragraph_ids"]:

                if paragraph_id not in paragraph_map:

                    paragraph_map[paragraph_id] = {
                        "paragraph_id": paragraph_id,
                        "text": paragraph["text"],
                        "matched_requirements": []
                    }

                paragraph_map[paragraph_id]["matched_requirements"].append({
                    "requirement_id": requirement["requirement_id"],
                    "rank": paragraph["rank"],
                    "score": paragraph["score"]
                })

                matched_paragraph_ids.append(paragraph_id)

        requirement_results.append({
            "requirement_id": requirement["requirement_id"],
            "requirement": requirement["text"],
            "categories": requirement["categories"],
            "priority": requirement["priority"],
            "retrieved_paragraph_ids": matched_paragraph_ids
        })

    return {
        "requirements": requirement_results,
        "unique_paragraphs": list(paragraph_map.values())
    }