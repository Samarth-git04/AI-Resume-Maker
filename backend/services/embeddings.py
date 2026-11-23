import hashlib
import json

import numpy as np
import torch

from pathlib import Path
from sentence_transformers import SentenceTransformer


CACHE_ROOT = Path(__file__).resolve().parents[1] / "rag_storage"

MODEL_NAME = "BAAI/bge-base-en-v1.5"
MODEL_VERSION = "2.0"

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

DEVICE = "cpu"
BATCH_SIZE = 16
MAX_SEQUENCE_LENGTH = 512


class EmbeddingEngine:

    def __init__(self):
        torch.set_num_threads(4)

        self.model = SentenceTransformer(
            MODEL_NAME,
            device=DEVICE,
        )

        self.model.max_seq_length = MAX_SEQUENCE_LENGTH

    def encode_query(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        embedding = self.model.encode(
            QUERY_PREFIX + query.strip(),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        return np.asarray(embedding, dtype=np.float32)

    @staticmethod
    def calculate_hash(chunks):
        content = json.dumps(
            chunks,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def generate_embeddings(self, resume_id, chunks, force=False):
        if not chunks:
            raise ValueError("Cannot generate embeddings without chunks.")

        cache_dir = CACHE_ROOT / str(resume_id)
        cache_dir.mkdir(parents=True, exist_ok=True)

        embeddings_path = cache_dir / "embeddings.npy"
        metadata_path = cache_dir / "embeddings_metadata.json"

        chunks_hash = self.calculate_hash(chunks)

        if (
            not force
            and embeddings_path.exists()
            and metadata_path.exists()
        ):
            try:
                with metadata_path.open("r", encoding="utf-8") as file:
                    metadata = json.load(file)

                if (
                    metadata.get("chunks_hash") == chunks_hash
                    and metadata.get("model_name") == MODEL_NAME
                    and metadata.get("model_version") == MODEL_VERSION
                ):
                    embeddings = np.load(
                        embeddings_path,
                        allow_pickle=False,
                    )

                    expected_shape = (
                        len(chunks),
                        self.model.get_embedding_dimension(),
                    )

                    if (
                        embeddings.shape == expected_shape
                        and np.isfinite(embeddings).all()
                    ):
                        return embeddings.astype(np.float32)

            except (OSError, ValueError, json.JSONDecodeError):
                pass

        texts = [
            item.get("embedding_text") or item["text"]
            for item in chunks
        ]
        
        embeddings = self.model.encode(
            texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)

        temporary_path = embeddings_path.with_suffix(".tmp.npy")
        np.save(temporary_path, embeddings)
        temporary_path.replace(embeddings_path)

        metadata = {
            "resume_id": resume_id,
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "dimensions": int(embeddings.shape[1]),
            "batch_size": BATCH_SIZE,
            "max_sequence_length": MAX_SEQUENCE_LENGTH,
            "chunks_hash": chunks_hash,
            "embedding_count": len(embeddings),
        }

        temporary_metadata = metadata_path.with_suffix(".tmp")

        with temporary_metadata.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

        temporary_metadata.replace(metadata_path)

        return embeddings