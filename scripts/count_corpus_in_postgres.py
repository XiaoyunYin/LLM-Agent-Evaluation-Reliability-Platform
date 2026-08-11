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
                SELECT COUNT(*)
                FROM documents
                WHERE metadata->>'source' = 'synthetic'
                """
            )
            document_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM chunks
                WHERE metadata->>'category' IS NOT NULL
                  AND metadata->>'chunk_size' = '650'
                  AND metadata->>'chunk_overlap' = '100'
                """
            )
            chunk_count = cursor.fetchone()[0]

    print(f"Corpus documents: {document_count}")
    print(f"Corpus chunks: {chunk_count}")


if __name__ == "__main__":
    main()