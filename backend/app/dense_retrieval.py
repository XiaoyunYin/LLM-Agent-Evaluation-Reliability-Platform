import json
import os
from typing import Any

import psycopg
from pydantic import BaseModel, Field

from backend.app.embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingProvider,
    EmbeddingRequest,
)


DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)

DENSE_CANDIDATE_DEPTH = 50
DENSE_METRIC_DEPTH = 10


class DenseRetrievalResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


def to_pgvector_literal(embedding: list[float]) -> str:
    if len(embedding) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Expected embedding dimension {EMBEDDING_DIMENSION}, got {len(embedding)}."
        )

    return "[" + ",".join(str(value) for value in embedding) + "]"


class PostgresDenseRetriever:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        database_url: str | None = None,
        candidate_depth: int = DENSE_CANDIDATE_DEPTH,
        metric_depth: int = DENSE_METRIC_DEPTH,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            DEFAULT_DATABASE_URL,
        )
        self.candidate_depth = candidate_depth
        self.metric_depth = metric_depth

    def retrieve_candidates(self, query: str) -> list[DenseRetrievalResult]:
        embedding_response = self.embedding_provider.embed_texts(
            EmbeddingRequest(texts=[query])
        )
        query_embedding = embedding_response.embeddings[0]
        query_vector = to_pgvector_literal(query_embedding)

        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        text,
                        1 - (embedding <=> %s::vector) AS score,
                        metadata
                    FROM chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_vector,
                        query_vector,
                        self.candidate_depth,
                    ),
                )
                rows = cursor.fetchall()

        return [
            DenseRetrievalResult(
                chunk_id=row[0],
                text=row[1],
                score=float(row[2]),
                metadata=row[3] if isinstance(row[3], dict) else json.loads(row[3]),
            )
            for row in rows
        ]

    def retrieve(self, query: str) -> list[DenseRetrievalResult]:
        candidates = self.retrieve_candidates(query)

        return candidates[: self.metric_depth]