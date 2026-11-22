from backend.services.embeddings import EmbeddingEngine

engine = EmbeddingEngine()

query = "Experience with Python, SQL and data analysis."

embedding = engine.encode_query(query)

print("Shape:", embedding.shape)
print("Data type:", embedding.dtype)
print("Norm:", float((embedding ** 2).sum() ** 0.5))

assert embedding.shape == (768,)
assert embedding.dtype == "float32"
assert abs(float((embedding ** 2).sum() ** 0.5) - 1.0) < 0.001

print("Query embedding test passed!")