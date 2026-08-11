import argparse
import json
from datetime import datetime, timezone
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever
from backend.app.dense_retrieval import PostgresDenseRetriever
from backend.app.embeddings import EmbeddingConfigurationError, OpenAIEmbeddingProvider
from backend.app.hybrid_retrieval import HybridRetriever, RRF_K
from backend.app.retrieval_metrics import ndcg_at_k, recall_at_k


LABEL_PATH = Path("datasets/labels/retrieval_heldout_120_v0.2.jsonl")
LABEL_DATASET_VERSION = "retrieval_heldout_120_v0.2"
CORPUS_PATH = Path("datasets/corpus/chunks.jsonl")
CORPUS_VERSION = "synthetic_support_corpus_chunks_v0.2"
# A machine-readable artifact so the dashboard and metrics endpoint can read a
# measured retrieval result instead of reporting "not measured".
RESULT_PATH = Path("runs/retrieval_benchmark/hybrid_retrieval_benchmark.json")


def load_labeled_queries(path: Path) -> list[dict]:
    rows = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            rows.append(json.loads(line))

    return rows


def relevant_chunks_by_id(row: dict) -> dict[str, int]:
    return {
        item["chunk_id"]: item["relevance"]
        for item in row["relevant_chunks"]
    }


def summarize_scores(
    retrieval_results_by_query: list[list[str]],
    labeled_queries: list[dict],
) -> dict[str, float]:
    recall_scores = []
    ndcg_scores = []

    for retrieved_chunk_ids, row in zip(
        retrieval_results_by_query,
        labeled_queries,
        strict=True,
    ):
        relevant_by_chunk_id = relevant_chunks_by_id(row)

        recall_scores.append(
            recall_at_k(
                retrieved_chunk_ids=retrieved_chunk_ids,
                relevant_by_chunk_id=relevant_by_chunk_id,
                k=10,
            )
        )
        ndcg_scores.append(
            ndcg_at_k(
                retrieved_chunk_ids=retrieved_chunk_ids,
                relevant_by_chunk_id=relevant_by_chunk_id,
                k=10,
            )
        )

    return {
        "mean_recall_at_10": sum(recall_scores) / len(recall_scores),
        "mean_ndcg_at_10": sum(ndcg_scores) / len(ndcg_scores),
    }


def chunk_ids(results: list) -> list[str]:
    return [result.chunk_id for result in results]


def breakdown_by_category(
    results_by_strategy: dict[str, list[list[str]]],
    labeled_queries: list[dict],
    facet: str,
) -> dict[str, dict[str, dict[str, float]]]:
    """Score each strategy within one label facet.

    A single mean hides the dense/lexical tradeoff: embeddings and BM25 fail on
    different query shapes, so an aggregate can make a retriever look uniformly
    weak when it is strong on half the set.
    """
    buckets: dict[str, list[int]] = {}
    for index, row in enumerate(labeled_queries):
        value = row.get("categories", {}).get(facet, "unspecified")
        buckets.setdefault(value, []).append(index)

    out: dict[str, dict[str, dict[str, float]]] = {}
    for value, indexes in sorted(buckets.items()):
        subset = [labeled_queries[i] for i in indexes]
        out[value] = {
            strategy: summarize_scores(
                retrieval_results_by_query=[results[i] for i in indexes],
                labeled_queries=subset,
            )
            for strategy, results in results_by_strategy.items()
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score dense, BM25, and hybrid RRF on the same labeled queries."
    )
    parser.add_argument("--labels", type=Path, default=LABEL_PATH)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--index", default=None, help="Elasticsearch index to search.")
    parser.add_argument("--label-version", default=LABEL_DATASET_VERSION)
    parser.add_argument("--corpus-version", default=CORPUS_VERSION)
    parser.add_argument(
        "--result",
        type=Path,
        default=RESULT_PATH,
        help="Artifact path. Use a distinct name per dataset so one benchmark "
             "does not overwrite another's measured result.",
    )
    args = parser.parse_args()

    label_path = args.labels
    corpus_path = args.corpus
    label_version = args.label_version
    corpus_version = args.corpus_version
    result_path = args.result

    labeled_queries = load_labeled_queries(label_path)

    try:
        embedding_provider = OpenAIEmbeddingProvider()
    except EmbeddingConfigurationError as error:
        print("hybrid_retrieval_benchmark")
        print("status: not_run")
        print(f"reason: {error}")
        print("dense_mean_recall_at_10: not_measured")
        print("dense_mean_ndcg_at_10: not_measured")
        print("bm25_mean_recall_at_10: not_measured")
        print("bm25_mean_ndcg_at_10: not_measured")
        print("hybrid_mean_recall_at_10: not_measured")
        print("hybrid_mean_ndcg_at_10: not_measured")
        return

    dense_retriever = PostgresDenseRetriever(
        embedding_provider=embedding_provider,
    )
    bm25_retriever = (
        ElasticsearchBm25Retriever(index_name=args.index)
        if args.index
        else ElasticsearchBm25Retriever()
    )
    hybrid_retriever = HybridRetriever(
        dense_retriever=dense_retriever,
        bm25_retriever=bm25_retriever,
        rrf_k=RRF_K,
        metric_depth=10,
    )

    dense_results_by_query = []
    bm25_results_by_query = []
    hybrid_results_by_query = []

    for row in labeled_queries:
        query = row["query"]

        dense_results_by_query.append(
            chunk_ids(dense_retriever.retrieve(query))
        )
        bm25_results_by_query.append(
            chunk_ids(bm25_retriever.retrieve(query))
        )
        hybrid_results_by_query.append(
            chunk_ids(hybrid_retriever.retrieve(query))
        )

    dense_scores = summarize_scores(
        retrieval_results_by_query=dense_results_by_query,
        labeled_queries=labeled_queries,
    )
    bm25_scores = summarize_scores(
        retrieval_results_by_query=bm25_results_by_query,
        labeled_queries=labeled_queries,
    )
    hybrid_scores = summarize_scores(
        retrieval_results_by_query=hybrid_results_by_query,
        labeled_queries=labeled_queries,
    )

    print("hybrid_retrieval_benchmark")
    print("status: measured")
    print("exact_command: python scripts/benchmark_hybrid_retrieval.py")
    print(f"label_path: {label_path}")
    print(f"label_dataset_version: {label_version}")
    print(f"corpus_path: {corpus_path}")
    print(f"corpus_version: {corpus_version}")
    print(f"queries_evaluated: {len(labeled_queries)}")
    print(f"dense_candidate_depth: {dense_retriever.candidate_depth}")
    print(f"dense_metric_depth: {dense_retriever.metric_depth}")
    print(f"bm25_candidate_depth: {bm25_retriever.candidate_depth}")
    print(f"bm25_metric_depth: {bm25_retriever.metric_depth}")
    print(f"rrf_k: {hybrid_retriever.rrf_k}")
    print(f"hybrid_metric_depth: {hybrid_retriever.metric_depth}")
    print(f"dense_mean_recall_at_10: {dense_scores['mean_recall_at_10']:.4f}")
    print(f"dense_mean_ndcg_at_10: {dense_scores['mean_ndcg_at_10']:.4f}")
    print(f"bm25_mean_recall_at_10: {bm25_scores['mean_recall_at_10']:.4f}")
    print(f"bm25_mean_ndcg_at_10: {bm25_scores['mean_ndcg_at_10']:.4f}")
    print(f"hybrid_mean_recall_at_10: {hybrid_scores['mean_recall_at_10']:.4f}")
    print(f"hybrid_mean_ndcg_at_10: {hybrid_scores['mean_ndcg_at_10']:.4f}")

    results_by_strategy = {
        "dense": dense_results_by_query,
        "bm25": bm25_results_by_query,
        "hybrid": hybrid_results_by_query,
    }
    breakdowns = {
        facet: breakdown_by_category(results_by_strategy, labeled_queries, facet)
        for facet in ("match_type", "hop_type", "difficulty")
    }

    for facet, values in breakdowns.items():
        print(f"\n-- recall@10 by {facet} --")
        for value, strategies in values.items():
            scores = "  ".join(
                f"{name}={data['mean_recall_at_10']:.4f}"
                for name, data in strategies.items()
            )
            print(f"  {value:24s} {scores}")
    print()

    artifact = {
        "benchmark": "hybrid_retrieval_benchmark",
        "breakdowns": breakdowns,
        "status": "measured",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "exact_command": "python scripts/benchmark_hybrid_retrieval.py",
        "label_path": str(label_path),
        "label_dataset_version": label_version,
        "corpus_path": str(corpus_path),
        "corpus_version": corpus_version,
        "queries_evaluated": len(labeled_queries),
        "embedding_model": embedding_provider.model_name,
        "config": {
            "dense_candidate_depth": dense_retriever.candidate_depth,
            "bm25_candidate_depth": bm25_retriever.candidate_depth,
            "rrf_k": hybrid_retriever.rrf_k,
            "metric_depth": hybrid_retriever.metric_depth,
        },
        "strategies": {
            "dense": dense_scores,
            "bm25": bm25_scores,
            "hybrid": hybrid_scores,
        },
        # Flat mirrors of the nested scores. dashboard_metrics.retrieval_metric
        # detects an artifact by scanning top-level keys ending in recall_at_10 /
        # ndcg_at_10, so the nested form alone would read as "not measured".
        "dense_mean_recall_at_10": dense_scores["mean_recall_at_10"],
        "dense_mean_ndcg_at_10": dense_scores["mean_ndcg_at_10"],
        "bm25_mean_recall_at_10": bm25_scores["mean_recall_at_10"],
        "bm25_mean_ndcg_at_10": bm25_scores["mean_ndcg_at_10"],
        "hybrid_mean_recall_at_10": hybrid_scores["mean_recall_at_10"],
        "hybrid_mean_ndcg_at_10": hybrid_scores["mean_ndcg_at_10"],
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"saved_artifact: {result_path}")


if __name__ == "__main__":
    main()