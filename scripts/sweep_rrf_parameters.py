"""Sweep RRF k and candidate depth over a labeled query set.

Reciprocal rank fusion is a pure function of two ranked lists, so the expensive
part - embedding each query, querying pgvector, querying Elasticsearch - only has
to happen once. Candidates are fetched at the deepest configuration under test,
then every (k, depth) combination is scored in memory. A full grid therefore costs
one pass of query embeddings rather than one pass per configuration.

The point is to find out whether fusion has a configuration that beats both of its
inputs, and if so where. Every configuration evaluated is written to the artifact,
not only the best one, so the grid can be read as a whole.

Usage:
    python scripts/sweep_rrf_parameters.py \
        --labels datasets/beir/scifact/labels.jsonl \
        --index beir_scifact_chunks \
        --result runs/retrieval_benchmark/scifact_rrf_sweep.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever  # noqa: E402
from backend.app.dense_retrieval import PostgresDenseRetriever  # noqa: E402
from backend.app.embeddings import OpenAIEmbeddingProvider  # noqa: E402
from backend.app.hybrid_retrieval import reciprocal_rank_fusion  # noqa: E402
from backend.app.retrieval_metrics import ndcg_at_k, recall_at_k  # noqa: E402

DEFAULT_K_VALUES = [1, 5, 10, 20, 40, 60, 100, 200, 500]
DEFAULT_DEPTHS = [10, 20, 50, 100]
METRIC_DEPTH = 10


def load_labels(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def relevant_by_chunk_id(row: dict) -> dict[str, int]:
    return {item["chunk_id"]: item["relevance"] for item in row["relevant_chunks"]}


def score(ranked_ids_by_query: list[list[str]], labels: list[dict]) -> dict[str, float]:
    recalls, ndcgs = [], []
    for ranked_ids, row in zip(ranked_ids_by_query, labels, strict=True):
        relevant = relevant_by_chunk_id(row)
        recalls.append(recall_at_k(ranked_ids, relevant, METRIC_DEPTH))
        ndcgs.append(ndcg_at_k(ranked_ids, relevant, METRIC_DEPTH))
    return {
        "mean_recall_at_10": sum(recalls) / len(recalls),
        "mean_ndcg_at_10": sum(ndcgs) / len(ndcgs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--index", default=None)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--k-values", type=int, nargs="+", default=DEFAULT_K_VALUES)
    parser.add_argument("--depths", type=int, nargs="+", default=DEFAULT_DEPTHS)
    args = parser.parse_args()

    labels = load_labels(args.labels)
    max_depth = max(args.depths)

    embedding_provider = OpenAIEmbeddingProvider()
    dense = PostgresDenseRetriever(
        embedding_provider=embedding_provider, candidate_depth=max_depth
    )
    bm25 = (
        ElasticsearchBm25Retriever(index_name=args.index, candidate_depth=max_depth)
        if args.index
        else ElasticsearchBm25Retriever(candidate_depth=max_depth)
    )

    print(f"fetching candidates at depth {max_depth} for {len(labels)} queries...")
    dense_candidates, bm25_candidates = [], []
    for position, row in enumerate(labels, start=1):
        dense_candidates.append(dense.retrieve_candidates(row["query"]))
        bm25_candidates.append(bm25.retrieve_candidates(row["query"]))
        if position % 50 == 0:
            print(f"  {position}/{len(labels)}")

    # Baselines use the same candidate lists, truncated to the metric depth.
    dense_only = score(
        [[r.chunk_id for r in c[:METRIC_DEPTH]] for c in dense_candidates], labels
    )
    bm25_only = score(
        [[r.chunk_id for r in c[:METRIC_DEPTH]] for c in bm25_candidates], labels
    )

    print()
    print(f"dense-only  recall@10={dense_only['mean_recall_at_10']:.4f}  "
          f"nDCG@10={dense_only['mean_ndcg_at_10']:.4f}")
    print(f"bm25-only   recall@10={bm25_only['mean_recall_at_10']:.4f}  "
          f"nDCG@10={bm25_only['mean_ndcg_at_10']:.4f}")
    best_single_recall = max(
        dense_only["mean_recall_at_10"], bm25_only["mean_recall_at_10"]
    )
    best_single_ndcg = max(dense_only["mean_ndcg_at_10"], bm25_only["mean_ndcg_at_10"])
    print()

    grid = []
    for depth in args.depths:
        for k in args.k_values:
            fused_by_query = []
            for dense_list, bm25_list in zip(
                dense_candidates, bm25_candidates, strict=True
            ):
                fused = reciprocal_rank_fusion(
                    dense_results=dense_list[:depth],
                    bm25_results=bm25_list[:depth],
                    k=k,
                    limit=METRIC_DEPTH,
                )
                fused_by_query.append([r.chunk_id for r in fused])
            scores = score(fused_by_query, labels)
            grid.append(
                {
                    "rrf_k": k,
                    "candidate_depth": depth,
                    **scores,
                    "beats_both_on_recall": scores["mean_recall_at_10"]
                    > best_single_recall,
                    "beats_both_on_ndcg": scores["mean_ndcg_at_10"] > best_single_ndcg,
                }
            )

    header = f"{'depth':>6} {'k':>5} {'recall@10':>10} {'nDCG@10':>9}  beats both"
    print(header)
    print("-" * len(header))
    for row in grid:
        flags = []
        if row["beats_both_on_recall"]:
            flags.append("recall")
        if row["beats_both_on_ndcg"]:
            flags.append("nDCG")
        print(
            f"{row['candidate_depth']:>6} {row['rrf_k']:>5} "
            f"{row['mean_recall_at_10']:>10.4f} {row['mean_ndcg_at_10']:>9.4f}  "
            f"{','.join(flags) if flags else '-'}"
        )

    best_recall = max(grid, key=lambda r: r["mean_recall_at_10"])
    best_ndcg = max(grid, key=lambda r: r["mean_ndcg_at_10"])
    print()
    print(f"best hybrid recall@10: {best_recall['mean_recall_at_10']:.4f} "
          f"(k={best_recall['rrf_k']}, depth={best_recall['candidate_depth']}) "
          f"vs best single {best_single_recall:.4f}")
    print(f"best hybrid nDCG@10:   {best_ndcg['mean_ndcg_at_10']:.4f} "
          f"(k={best_ndcg['rrf_k']}, depth={best_ndcg['candidate_depth']}) "
          f"vs best single {best_single_ndcg:.4f}")
    print()
    print("Configurations are selected on the same queries they are scored on, so a "
          "winning cell is an upper bound, not a held-out result.")

    artifact = {
        "benchmark": "rrf_parameter_sweep",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "labels_path": str(args.labels),
        "elasticsearch_index": args.index,
        "queries_evaluated": len(labels),
        "metric_depth": METRIC_DEPTH,
        "baselines": {"dense": dense_only, "bm25": bm25_only},
        "grid": grid,
        "selection_caveat": (
            "Every cell is scored on the same queries used to pick the best cell. "
            "Treat a winning configuration as an upper bound until it is confirmed "
            "on a held-out query set."
        ),
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"saved_artifact: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
