import os

import psycopg


DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documents (id, source_uri, title, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    "doc_test_001",
                    "local://test-document",
                    "Test Document",
                    "{}",
                ),
            )

            cursor.execute(
                """
                INSERT INTO chunks (id, document_id, chunk_index, text, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET text = EXCLUDED.text
                """,
                (
                    "chunk_test_001",
                    "doc_test_001",
                    0,
                    "This is a test chunk stored in PostgreSQL.",
                    "{}",
                ),
            )

            cursor.execute(
                """
                SELECT id, document_id, chunk_index, text
                FROM chunks
                WHERE id = %s
                """,
                ("chunk_test_001",),
            )
            row = cursor.fetchone()

    print(row)


if __name__ == "__main__":
    main()