CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_cosine_idx
ON chunks
USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;