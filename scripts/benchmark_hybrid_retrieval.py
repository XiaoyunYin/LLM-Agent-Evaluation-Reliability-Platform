import json
import sys
from pathlib import Path

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


def main() -> None:
    labeled_queries = load_labeled_queries(LABEL_PATH)

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
    bm25_retriever = ElasticsearchBm25Retriever()
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
    print(f"label_path: {LABEL_PATH}")
    print(f"label_dataset_version: {LABEL_DATASET_VERSION}")
    print(f"corpus_path: {CORPUS_PATH}")
    print(f"corpus_version: {CORPUS_VERSION}")
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


if __name__ == "__main__":
    main()