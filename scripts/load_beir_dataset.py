"""Download a BEIR dataset and convert it into this project's corpus and label formats.

Why this exists: the synthetic corpus has two weaknesses no amount of regeneration
fixes. Its relevance labels are derived from facts the generator planted, so they
test whether retrieval finds a string this repository chose; and its queries are
mostly identifier lookups, a shape that favours lexical matching and gives dense
retrieval little to contribute.

BEIR supplies human relevance judgments and natural-language queries, and its
baselines are published, so a reviewer can check whether the BM25 number here
lands where BM25 normally lands on the same dataset. That turns "trust this
fixture" into "compare against the literature".

Each BEIR document becomes exactly one chunk. BEIR evaluates at document level and
its qrels reference document IDs, so keeping the unit identical is what makes these
numbers comparable to published results. No chunking is applied.

Usage:
    python scripts/load_beir_dataset.py --dataset scifact
    python scripts/load_beir_dataset.py --dataset nfcorpus --split test
    python scripts/load_beir_dataset.py --dataset scifact --split train --labels-only
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

BEIR_BASE_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"
DEFAULT_DATASET = "scifact"
DEFAULT_SPLIT = "test"
OUTPUT_ROOT = Path("datasets/beir")

PROTOCOL_VERSION = "beir_qrels_v1"
LABELING_LIMITATIONS = [
    "human_relevance_judgments_from_the_beir_benchmark",
    "labels_not_created_by_this_project",
    "qrels_are_not_exhaustive_over_the_full_corpus",
]


def download_dataset(dataset: str, destination: Path) -> Path:
    """Download and extract the dataset unless it is already present."""
    extracted = destination / dataset
    if (extracted / "corpus.jsonl").exists():
        print(f"already downloaded: {extracted}")
        return extracted

    url = f"{BEIR_BASE_URL}/{dataset}.zip"
    print(f"downloading {url}")
    destination.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as response:  # noqa: S310 - fixed, trusted host
        payload = response.read()
    print(f"  {len(payload):,} bytes")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(destination)
    print(f"extracted to {extracted}")
    return extracted


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_qrels(path: Path) -> dict[str, dict[str, int]]:
    """qrels are TSV: query-id, corpus-id, score, with a header row."""
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{path} is empty")
        for row in reader:
            if len(row) < 3:
                continue
            query_id, corpus_id, score = row[0], row[1], int(row[2])
            if score > 0:
                qrels[query_id][corpus_id] = score
    return dict(qrels)


def build_chunks(corpus_rows: list[dict], dataset: str) -> list[dict]:
    chunks = []
    for row in corpus_rows:
        title = (row.get("title") or "").strip()
        body = (row.get("text") or "").strip()
        # Title carries real signal in BEIR and is part of the standard indexed
        # text, so it is prepended rather than kept only as metadata.
        text = f"{title}\n\n{body}".strip() if title else body
        if not text:
            continue
        chunks.append(
            {
                "id": row["_id"],
                "document_id": row["_id"],
                "chunk_index": 0,
                "text": text,
                "metadata": {
                    "source_path": f"beir:{dataset}",
                    "title": title or row["_id"],
                    "category": dataset,
                    "chunk_size": len(text),
                    "chunk_overlap": 0,
                },
            }
        )
    return chunks


def build_labels(
    query_rows: list[dict],
    qrels: dict[str, dict[str, int]],
    known_chunk_ids: set[str],
    dataset: str,
    split: str,
) -> list[dict]:
    queries_by_id = {row["_id"]: row["text"] for row in query_rows}
    labels = []
    missing_chunks = 0

    for query_id, relevant in sorted(qrels.items()):
        query_text = queries_by_id.get(query_id)
        if not query_text:
            continue

        relevant_chunks = []
        for chunk_id, score in sorted(relevant.items()):
            if chunk_id not in known_chunk_ids:
                missing_chunks += 1
                continue
            relevant_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "relevance": score,
                    "note": f"BEIR {dataset} {split} qrel, graded {score}.",
                }
            )
        if not relevant_chunks:
            continue

        labels.append(
            {
                "id": f"{dataset}-{query_id}",
                "query": query_text,
                "split": "heldout",
                "labeling_protocol_version": PROTOCOL_VERSION,
                "labels_created_blind_to_judge_outputs": True,
                "categories": {
                    "domain": dataset,
                    "hop_type": "single-hop",
                    "match_type": "semantic/paraphrase",
                    "difficulty": "hard" if len(relevant_chunks) > 1 else "easy",
                },
                "relevant_chunks": relevant_chunks,
                "labeling_limitations": LABELING_LIMITATIONS,
            }
        )

    if missing_chunks:
        print(f"  warning: {missing_chunks} qrel entries referenced absent documents")
    return labels


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--download-dir", type=Path, default=OUTPUT_ROOT / "_download")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--labels-only",
        action="store_true",
        help="Skip writing chunks.jsonl. A second split of the same dataset shares "
             "one corpus, so writing it again is a byte-identical duplicate.",
    )
    args = parser.parse_args()

    output_dir = args.output_dir or OUTPUT_ROOT / args.dataset
    source = download_dataset(args.dataset, args.download_dir)

    qrels_path = source / "qrels" / f"{args.split}.tsv"
    if not qrels_path.exists():
        available = sorted(p.stem for p in (source / "qrels").glob("*.tsv"))
        print(f"split {args.split!r} not found; available: {available}", file=sys.stderr)
        return 1

    corpus_rows = read_jsonl(source / "corpus.jsonl")
    query_rows = read_jsonl(source / "queries.jsonl")
    qrels = read_qrels(qrels_path)

    chunks = build_chunks(corpus_rows, args.dataset)
    known_chunk_ids = {chunk["id"] for chunk in chunks}
    labels = build_labels(query_rows, qrels, known_chunk_ids, args.dataset, args.split)

    if not args.labels_only:
        write_jsonl(output_dir / "chunks.jsonl", chunks)
    write_jsonl(output_dir / "labels.jsonl", labels)

    grades: dict[int, int] = defaultdict(int)
    for label in labels:
        for relevant in label["relevant_chunks"]:
            grades[relevant["relevance"]] += 1

    print()
    print(f"dataset:              {args.dataset} ({args.split})")
    print(f"documents / chunks:   {len(chunks):,}")
    print(f"queries with qrels:   {len(labels):,}")
    print(f"relevance references: {sum(grades.values()):,}")
    for grade in sorted(grades, reverse=True):
        print(f"  relevance {grade}: {grades[grade]:,}")
    mean_relevant = sum(len(x["relevant_chunks"]) for x in labels) / max(1, len(labels))
    print(f"mean relevant per query: {mean_relevant:.2f}")
    print()
    if not args.labels_only:
        print(f"wrote {output_dir / 'chunks.jsonl'}")
    print(f"wrote {output_dir / 'labels.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
