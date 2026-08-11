import json
import os

import psycopg

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.dense_retrieval import PostgresDenseRetriever
from backend.app.embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingRequest,
    EmbeddingResponse,
)




DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)


class FakeEmbeddingProvider:
    provider_name = "fake"

    def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            embeddings=[[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)],
            provider_name=self.provider_name,
            model_name="fake-embedding-model",
            dimension=EMBEDDING_DIMENSION,
            is_mock=True,
            metadata={"input_count": len(request.texts)},
        )


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    matching = [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
    somewhat_close = [0.8, 0.2] + [0.0] * (EMBEDDING_DIMENSION - 2)
    unrelated = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSION - 2)

    chunks = [
        (
            "chunk_dense_smoke_match",
            "Password reset instructions are available in account settings.",
            matching,
        ),
        (
            "chunk_dense_smoke_close",
            "Account recovery includes email verification and support review.",
            somewhat_close,
        ),
        (
            "chunk_dense_smoke_unrelated",
            "Billing exports can be downloaded from the invoices page.",
            unrelated,
        ),
    ]

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documents (id, source_uri, title, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET title = EXCLUDED.title,
                    metadata = EXCLUDED.metadata
                """,
                (
                    "doc_dense_smoke",
                    "file://dense-smoke-test",
                    "Dense retrieval smoke test",
                    json.dumps({"purpose": "dense_retrieval_smoke_test"}),
                ),
            )

            for index, (chunk_id, text, embedding) in enumerate(chunks):
                cursor.execute(
                    """
                    INSERT INTO chunks (
                        id,
                        document_id,
                        chunk_index,
                        text,
                        embedding,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s::vector, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET text = EXCLUDED.text,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        chunk_id,
                        "doc_dense_smoke",
                        index,
                        text,
                        to_vector_literal(embedding),
                        json.dumps({"purpose": "dense_retrieval_smoke_test"}),
                    ),
                )

    retriever = PostgresDenseRetriever(
        embedding_provider=FakeEmbeddingProvider(),
        database_url=database_url,
    )
    results = retriever.retrieve("How do I reset my password?")

    print(f"results_returned: {len(results)}")
    print(f"top_chunk_id: {results[0].chunk_id}")
    print(f"top_score: {results[0].score:.3f}")


if __name__ == "__main__":
    main()