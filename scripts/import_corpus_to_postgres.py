import json
import os
from pathlib import Path

import psycopg


DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)

RAW_DIR = Path("datasets/corpus/raw")
CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")


def parse_markdown_document(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("Document is missing front matter")

    _, front_matter, body = text.split("---", 2)

    metadata = {}

    for line in front_matter.strip().splitlines():
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    return metadata, body.strip()


def load_raw_documents() -> list[dict[str, object]]:
    documents = []

    for path in sorted(RAW_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        metadata, body = parse_markdown_document(text)

        doc_id = metadata["doc_id"]

        documents.append(
            {
                "id": doc_id,
                "source_uri": f"file://{path.as_posix()}",
                "title": metadata["title"],
                "metadata": {
                    "category": metadata["category"],
                    "source": metadata["source"],
                    "source_path": str(path),
                    "raw_character_count": len(body),
                },
            }
        )

    return documents


def load_chunks() -> list[dict[str, object]]:
    chunks = []

    with CHUNKS_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))

    return chunks


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    documents = load_raw_documents()
    chunks = load_chunks()

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for document in documents:
                cursor.execute(
                    """
                    INSERT INTO documents (id, source_uri, title, metadata)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET
                        source_uri = EXCLUDED.source_uri,
                        title = EXCLUDED.title,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        document["id"],
                        document["source_uri"],
                        document["title"],
                        json.dumps(document["metadata"]),
                    ),
                )

            for chunk in chunks:
                cursor.execute(
                    """
                    INSERT INTO chunks (id, document_id, chunk_index, text, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET
                        document_id = EXCLUDED.document_id,
                        chunk_index = EXCLUDED.chunk_index,
                        text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        chunk["id"],
                        chunk["document_id"],
                        chunk["chunk_index"],
                        chunk["text"],
                        json.dumps(chunk["metadata"]),
                    ),
                )

            cursor.execute("SELECT COUNT(*) FROM documents")
            database_document_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM chunks")
            database_chunk_count = cursor.fetchone()[0]

    print(f"Imported {len(documents)} documents")
    print(f"Imported {len(chunks)} chunks")
    print(f"Database documents: {database_document_count}")
    print(f"Database chunks: {database_chunk_count}")


if __name__ == "__main__":
    main()