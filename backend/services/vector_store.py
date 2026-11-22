import hashlib
import json

import faiss
import numpy as np

from pathlib import Path


CACHE_ROOT = Path(__file__).resolve().parents[1] / "rag_storage"


class VectorStore:

    def __init__(self, resume_id: int):
        self.resume_id = resume_id
        self.cache_dir = CACHE_ROOT / str(resume_id)

        self.index_path = self.cache_dir / "faiss.index"
        self.metadata_path = self.cache_dir / "index_metadata.json"
        self.embeddings_path = self.cache_dir / "embeddings.npy"
        self.chunks_path = self.cache_dir / "chunks.json"

        self.index = None
        self.chunks = None

    @staticmethod
    def calculate_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def load_source_data(self):
        if not self.embeddings_path.exists():
            raise FileNotFoundError("Embeddings file not found.")

        if not self.chunks_path.exists():
            raise FileNotFoundError("Chunks file not found.")

        embeddings = np.load(
            self.embeddings_path,
            allow_pickle=False
        )

        with self.chunks_path.open("r", encoding="utf-8") as file:
            chunks = json.load(file)

        if embeddings.ndim != 2:
            raise ValueError("Embeddings must be a 2D array.")

        if len(embeddings) != len(chunks):
            raise ValueError("Embedding and chunk counts do not match.")

        if not np.isfinite(embeddings).all():
            raise ValueError("Embeddings contain invalid values.")

        if not chunks:
            raise ValueError("No chunks available.")

        embeddings = np.ascontiguousarray(
            embeddings,
            dtype=np.float32
        )

        return embeddings, chunks

    def create_metadata(self, embeddings, chunks):
        return {
            "resume_id": self.resume_id,
            "index_type": "IndexFlatIP",
            "dimensions": embeddings.shape[1],
            "vector_count": len(embeddings),
            "embeddings_hash": self.calculate_hash(
                embeddings.tobytes()
            ),
            "chunks_hash": self.calculate_hash(
                json.dumps(
                    chunks,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":")
                ).encode("utf-8")
            )
        }

    def load_cached_index(self, expected_metadata):
        if not self.index_path.exists() or not self.metadata_path.exists():
            return False

        try:
            with self.metadata_path.open("r", encoding="utf-8") as file:
                metadata = json.load(file)

            if metadata != expected_metadata:
                return False

            index = faiss.read_index(str(self.index_path))

            if (
                index.d != expected_metadata["dimensions"]
                or index.ntotal != expected_metadata["vector_count"]
                or not isinstance(index, faiss.IndexFlatIP)
            ):
                return False

            self.index = index
            print("Using cached FAISS index.")

            return True

        except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
            return False

    def build_index(self, embeddings):
        dimensions = embeddings.shape[1]

        index = faiss.IndexFlatIP(dimensions)
        index.add(embeddings)

        temporary_path = self.index_path.with_name("faiss.tmp.index")

        faiss.write_index(index, str(temporary_path))
        temporary_path.replace(self.index_path)

        self.index = index

        print("Generated and saved FAISS index.")

    def prepare(self, force=False):
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        embeddings, chunks = self.load_source_data()
        metadata = self.create_metadata(embeddings, chunks)

        self.chunks = chunks

        if not force and self.load_cached_index(metadata):
            return self.index

        self.build_index(embeddings)

        temporary_metadata = self.metadata_path.with_suffix(".tmp")

        with temporary_metadata.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

        temporary_metadata.replace(self.metadata_path)

        return self.index

    def search(self, query_embedding, top_k=10):
        if self.index is None or self.chunks is None:
            self.prepare()

        if top_k < 1:
            raise ValueError("top_k must be greater than zero.")

        query = np.asarray(
            query_embedding,
            dtype=np.float32
        ).reshape(1, -1)

        if query.shape[1] != self.index.d:
            raise ValueError("Query embedding dimension mismatch.")

        if not np.isfinite(query).all():
            raise ValueError("Query embedding contains invalid values.")

        norm = np.linalg.norm(query)

        if norm == 0:
            raise ValueError("Query embedding cannot be a zero vector.")

        query /= norm

        scores, indices = self.index.search(
            query,
            min(top_k, self.index.ntotal)
        )

        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue

            chunk = self.chunks[idx]

            results.append({
                "rank": len(results) + 1,
                "chunk_id": chunk["chunk_id"],
                "paragraph_ids": chunk["paragraph_ids"],
                "text": chunk["text"],
                "score": float(score)
            })

        return results