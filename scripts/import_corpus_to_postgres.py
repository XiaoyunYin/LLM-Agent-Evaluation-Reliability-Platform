import argparse
import json
import os
from pathlib import Path

import psycopg


DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)

RAW_DIR = Path("datasets/corpus/raw")
DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")


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


def documents_from_chunks(chunks: list[dict]) -> list[dict[str, object]]:
    """Derive one document row per distinct document_id.

    Corpora that arrive as chunk files (BEIR, for example) have no raw markdown
    to parse, but the documents table still needs a row per document because
    chunks reference it by foreign key.
    """
    documents: dict[str, dict[str, object]] = {}
    for chunk in chunks:
        document_id = chunk["document_id"]
        if document_id in documents:
            continue
        metadata = chunk.get("metadata", {})
        documents[document_id] = {
            "id": document_id,
            "source_uri": str(metadata.get("source_path", "unknown")),
            "title": str(metadata.get("title", document_id)),
            "metadata": {
                "category": metadata.get("category", "unknown"),
                "source": "chunk_file",
            },
        }
    return list(documents.values())


def load_chunks(path: Path) -> list[dict[str, object]]:
    chunks = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a corpus into Postgres for dense retrieval."
    )
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument(
        "--from-chunks-only",
        action="store_true",
        help="Derive documents from the chunk file instead of parsing raw "
             "markdown. Required for corpora that ship as chunk files.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Clear documents and chunks first. Dense retrieval scans the whole "
             "chunks table, so two corpora sharing it would pollute each other.",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    chunks = load_chunks(args.chunks)
    documents = (
        documents_from_chunks(chunks)
        if args.from_chunks_only
        else load_raw_documents()
    )

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            if args.truncate:
                cursor.execute("TRUNCATE chunks, documents CASCADE")
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