import math


def recall_at_k(
    retrieved_chunk_ids: list[str],
    relevant_by_chunk_id: dict[str, int],
    k: int,
) -> float:
    relevant_ids = {
        chunk_id
        for chunk_id, relevance in relevant_by_chunk_id.items()
        if relevance > 0
    }

    if not relevant_ids:
        return 0.0

    retrieved_at_k = set(retrieved_chunk_ids[:k])
    hits = relevant_ids.intersection(retrieved_at_k)

    return len(hits) / len(relevant_ids)


def ndcg_at_k(
    retrieved_chunk_ids: list[str],
    relevant_by_chunk_id: dict[str, int],
    k: int,
) -> float:
    def gain(relevance: int) -> float:
        return (2**relevance) - 1

    def discounted_gain(relevance: int, rank: int) -> float:
        return gain(relevance) / math.log2(rank + 1)

    dcg = 0.0
    for index, chunk_id in enumerate(retrieved_chunk_ids[:k]):
        rank = index + 1
        relevance = relevant_by_chunk_id.get(chunk_id, 0)
        dcg += discounted_gain(relevance, rank)

    ideal_relevances = sorted(
        relevant_by_chunk_id.values(),
        reverse=True,
    )[:k]

    idcg = 0.0
    for index, relevance in enumerate(ideal_relevances):
        rank = index + 1
        idcg += discounted_gain(relevance, rank)

    if idcg == 0:
        return 0.0

    return dcg / idcg