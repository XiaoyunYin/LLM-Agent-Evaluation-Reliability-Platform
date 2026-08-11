import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever
from backend.app.retrieval_metrics import ndcg_at_k, recall_at_k


LABEL_PATH = Path("datasets/labels/retrieval_heldout_120_v0.1.jsonl")


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


def main() -> None:
    labeled_queries = load_labeled_queries(LABEL_PATH)

    retriever = ElasticsearchBm25Retriever()

    recall_scores = []
    ndcg_scores = []

    for row in labeled_queries:
        query = row["query"]
        relevant_by_chunk_id = relevant_chunks_by_id(row)

        results = retriever.retrieve(query)
        retrieved_chunk_ids = [result.chunk_id for result in results]

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

    mean_recall = sum(recall_scores) / len(recall_scores)
    mean_ndcg = sum(ndcg_scores) / len(ndcg_scores)

    print("bm25_retrieval_benchmark")
    print(f"label_path: {LABEL_PATH}")
    print(f"queries_evaluated: {len(labeled_queries)}")
    print(f"bm25_candidate_depth: {retriever.candidate_depth}")
    print(f"bm25_metric_depth: {retriever.metric_depth}")
    print(f"mean_recall_at_10: {mean_recall:.4f}")
    print(f"mean_ndcg_at_10: {mean_ndcg:.4f}")


if __name__ == "__main__":
    main()