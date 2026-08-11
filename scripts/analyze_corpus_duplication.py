"""Measure how much of the corpus is duplicated text, and what that implies
for the retrieval label set.

The corpus was generated from templates, so many chunks in different documents
may carry byte-identical text. When that happens a retriever has no signal to
prefer the one chunk ID named in the label file over its identical siblings, so
recall@10 is capped by the size of the duplicate cluster rather than by
retrieval quality.

This script measures that cap. It writes no metrics anywhere and makes no
claims; it only reports what is in the files.

Usage:
    python scripts/analyze_corpus_duplication.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_LABELS_PATH = Path("datasets/labels/retrieval_heldout_120_v0.1.jsonl")
METRIC_DEPTH = 10


def normalize(text: str) -> str:
    """Collapse all runs of whitespace so formatting noise does not hide a duplicate."""
    return " ".join(text.split()).strip()


def text_key(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
    return rows


def build_clusters(chunks: list[dict]) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Group chunk IDs by identical normalized text.

    Returns (cluster_key -> [chunk_id, ...], chunk_id -> cluster_key).
    """
    clusters: dict[str, list[str]] = defaultdict(list)
    chunk_to_cluster: dict[str, str] = {}
    for chunk in chunks:
        key = text_key(chunk["text"])
        clusters[key].append(chunk["id"])
        chunk_to_cluster[chunk["id"]] = key
    return dict(clusters), chunk_to_cluster


def labeled_chunk_ids(labels: list[dict]) -> list[str]:
    ids: list[str] = []
    for record in labels:
        for relevant in record.get("relevant_chunks", []):
            ids.append(relevant["chunk_id"])
    return ids


def report_corpus_shape(chunks: list[dict], clusters: dict[str, list[str]]) -> None:
    sizes = sorted((len(members) for members in clusters.values()), reverse=True)
    total = len(chunks)
    distinct = len(clusters)

    print("=" * 62)
    print("BLOCK 1 - CORPUS SHAPE")
    print("=" * 62)
    print(f"total chunks:               {total:,}")
    print(f"distinct normalized texts:  {distinct:,}")
    print(f"duplication factor:         {total / distinct:.2f}x" if distinct else "n/a")
    print(f"unique (cluster size 1):    {sum(1 for s in sizes if s == 1):,}")
    print(f"largest cluster:            {sizes[0]:,}" if sizes else "n/a")
    print(f"median cluster size:        {statistics.median(sizes):.1f}" if sizes else "n/a")
    print()
    print("top 5 largest duplicate clusters:")
    for key, members in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:5]:
        print(f"  size {len(members):>5,}  e.g. {members[0]}")
    print()


def report_recall_ceiling(
    labels: list[dict],
    clusters: dict[str, list[str]],
    chunk_to_cluster: dict[str, str],
) -> None:
    ids = labeled_chunk_ids(labels)
    missing = [cid for cid in ids if cid not in chunk_to_cluster]
    known = [cid for cid in ids if cid in chunk_to_cluster]

    cluster_sizes = [len(clusters[chunk_to_cluster[cid]]) for cid in known]

    print("=" * 62)
    print("BLOCK 2 - RECALL CEILING IMPLIED BY THE LABELS")
    print("=" * 62)
    print(f"labeled queries:            {len(labels):,}")
    print(f"labeled chunk references:   {len(ids):,}")
    if missing:
        print(f"labeled IDs not in corpus:  {len(missing)}  (first: {missing[0]})")
    if not cluster_sizes:
        print("no resolvable labeled chunks; nothing further to report")
        return

    print(f"cluster size of labeled chunks:")
    print(f"  min:                      {min(cluster_sizes):,}")
    print(f"  median:                   {statistics.median(cluster_sizes):.1f}")
    print(f"  max:                      {max(cluster_sizes):,}")
    print(f"  labels in a cluster > 1:  {sum(1 for s in cluster_sizes if s > 1):,}"
          f" of {len(cluster_sizes):,}")
    print()

    # Per query: best achievable recall@10 is (labeled chunks a perfect retriever
    # could surface) / (labeled chunks for that query). A perfect retriever fills
    # the top 10 with members of the duplicate cluster, so the chance of surfacing
    # the exact labeled ID is min(1, METRIC_DEPTH / cluster_size).
    per_query_ceiling: list[float] = []
    for record in labels:
        relevant = [r["chunk_id"] for r in record.get("relevant_chunks", [])]
        relevant = [cid for cid in relevant if cid in chunk_to_cluster]
        if not relevant:
            continue
        expected_hits = sum(
            min(1.0, METRIC_DEPTH / len(clusters[chunk_to_cluster[cid]]))
            for cid in relevant
        )
        per_query_ceiling.append(expected_hits / len(relevant))

    ceiling = statistics.mean(per_query_ceiling)
    print(f"theoretical max recall@{METRIC_DEPTH} given these labels: {ceiling:.4f}")
    print()
    print("Compare against the measured BM25 recall@10 of 0.0667 (Session 24).")
    print("If they are close, retrieval is behaving and the fixture is the problem.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    args = parser.parse_args()

    chunks = load_jsonl(args.chunks)
    labels = load_jsonl(args.labels)
    clusters, chunk_to_cluster = build_clusters(chunks)

    report_corpus_shape(chunks, clusters)
    report_recall_ceiling(labels, clusters, chunk_to_cluster)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
