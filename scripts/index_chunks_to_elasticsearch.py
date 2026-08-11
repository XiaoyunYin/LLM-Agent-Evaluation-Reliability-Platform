import json
import os
from pathlib import Path

import requests


DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"
DEFAULT_INDEX_NAME = "llm_eval_chunks"
CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
BULK_BATCH_SIZE = 500


def load_chunks(path: Path) -> list[dict]:
    chunks = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))

    return chunks


def ensure_index(elasticsearch_url: str, index_name: str) -> None:
    index_url = f"{elasticsearch_url}/{index_name}"

    response = requests.head(index_url, timeout=10)
    if response.status_code == 200:
        return

    response.raise_for_status() if response.status_code != 404 else None

    mapping = {
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "text": {"type": "text"},
                "metadata": {"type": "object", "enabled": True},
            }
        }
    }

    response = requests.put(index_url, json=mapping, timeout=10)
    response.raise_for_status()


def bulk_index_chunks(
    elasticsearch_url: str,
    index_name: str,
    chunks: list[dict],
) -> None:
    bulk_url = f"{elasticsearch_url}/_bulk?refresh=true"

    for start in range(0, len(chunks), BULK_BATCH_SIZE):
        batch = chunks[start : start + BULK_BATCH_SIZE]
        lines = []

        for chunk in batch:
            chunk_id = chunk["id"]

            lines.append(
                json.dumps(
                    {
                        "index": {
                            "_index": index_name,
                            "_id": chunk_id,
                        }
                    }
                )
            )
            lines.append(
                json.dumps(
                    {
                        "chunk_id": chunk_id,
                        "document_id": chunk["document_id"],
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["text"],
                        "metadata": chunk["metadata"],
                    }
                )
            )

        payload = "\n".join(lines) + "\n"

        response = requests.post(
            bulk_url,
            data=payload,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        if result.get("errors"):
            raise RuntimeError("Elasticsearch bulk indexing reported errors")


def count_indexed_chunks(elasticsearch_url: str, index_name: str) -> int:
    response = requests.get(
        f"{elasticsearch_url}/{index_name}/_count",
        timeout=10,
    )
    response.raise_for_status()

    return int(response.json()["count"])


def main() -> None:
    elasticsearch_url = os.getenv(
        "ELASTICSEARCH_URL",
        DEFAULT_ELASTICSEARCH_URL,
    )
    index_name = os.getenv("ELASTICSEARCH_INDEX", DEFAULT_INDEX_NAME)

    chunks = load_chunks(CHUNKS_PATH)

    ensure_index(elasticsearch_url, index_name)
    bulk_index_chunks(elasticsearch_url, index_name, chunks)

    indexed_count = count_indexed_chunks(elasticsearch_url, index_name)

    print(f"Loaded chunks from file: {len(chunks)}")
    print(f"Elasticsearch index: {index_name}")
    print(f"Indexed chunks in Elasticsearch: {indexed_count}")


if __name__ == "__main__":
    main()