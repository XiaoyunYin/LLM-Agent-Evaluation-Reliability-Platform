import json
from pathlib import Path


RAW_DIR = Path("datasets/corpus/raw")
OUTPUT_PATH = Path("datasets/corpus/chunks.jsonl")

CHUNK_SIZE = 650
CHUNK_OVERLAP = 100


def parse_markdown_document(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("Document is missing front matter")

    _, front_matter, body = text.split("---", 2)

    metadata = {}

    for line in front_matter.strip().splitlines():
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    return metadata, body.strip()


def chunk_text(text: str) -> list[str]:
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP

    for start in range(0, len(text), step):
        chunk = text[start : start + CHUNK_SIZE].strip()

        if chunk:
            chunks.append(chunk)

        if start + CHUNK_SIZE >= len(text):
            break

    return chunks


def main() -> None:
    document_count = 0
    chunk_count = 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as output_file:
        for path in sorted(RAW_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            metadata, body = parse_markdown_document(text)

            doc_id = metadata["doc_id"]
            title = metadata["title"]
            category = metadata["category"]

            document_count += 1

            for chunk_index, chunk in enumerate(chunk_text(body)):
                chunk_id = f"{doc_id}_chunk_{chunk_index:04d}"

                row = {
                    "id": chunk_id,
                    "document_id": doc_id,
                    "chunk_index": chunk_index,
                    "text": chunk,
                    "metadata": {
                        "source_path": str(path),
                        "title": title,
                        "category": category,
                        "chunk_size": CHUNK_SIZE,
                        "chunk_overlap": CHUNK_OVERLAP,
                    },
                }

                output_file.write(json.dumps(row) + "\n")
                chunk_count += 1

    print(f"Read {document_count} documents")
    print(f"Wrote {chunk_count} chunks to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()