import pytest

from backend.app.retrieval_metrics import ndcg_at_k, recall_at_k


def test_recall_at_10_counts_relevant_chunks_anywhere_in_top_10():
    retrieved_chunk_ids = ["X", "A", "Y", "C", "Z"]
    relevant_by_chunk_id = {
        "A": 2,
        "B": 1,
        "C": 2,
    }

    score = recall_at_k(
        retrieved_chunk_ids=retrieved_chunk_ids,
        relevant_by_chunk_id=relevant_by_chunk_id,
        k=10,
    )

    assert score == pytest.approx(2 / 3)


def test_ndcg_at_10_rewards_better_ranking_with_graded_relevance():
    retrieved_chunk_ids = ["X", "A", "Y", "C", "Z"]
    relevant_by_chunk_id = {
        "A": 2,
        "B": 1,
        "C": 2,
    }

    score = ndcg_at_k(
        retrieved_chunk_ids=retrieved_chunk_ids,
        relevant_by_chunk_id=relevant_by_chunk_id,
        k=10,
    )

    assert score == pytest.approx(0.59057, abs=0.00001)