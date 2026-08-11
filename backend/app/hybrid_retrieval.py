from typing import Any, Protocol

from pydantic import BaseModel, Field


RRF_K = 60
HYBRID_METRIC_DEPTH = 10


class CandidateRetriever(Protocol):
    def retrieve_candidates(self, query: str) -> list[Any]:
        ...


class HybridRetrievalResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def reciprocal_rank_fusion(
    dense_results: list[Any],
    bm25_results: list[Any],
    k: int = RRF_K,
    limit: int = HYBRID_METRIC_DEPTH,
) -> list[HybridRetrievalResult]:
    scores_by_chunk_id: dict[str, float] = {}
    result_by_chunk_id: dict[str, Any] = {}
    dense_rank_by_chunk_id: dict[str, int] = {}
    bm25_rank_by_chunk_id: dict[str, int] = {}

    for index, result in enumerate(dense_results):
        rank = index + 1
        chunk_id = result.chunk_id

        scores_by_chunk_id[chunk_id] = scores_by_chunk_id.get(
            chunk_id,
            0.0,
        ) + (1 / (k + rank))

        result_by_chunk_id.setdefault(chunk_id, result)
        dense_rank_by_chunk_id[chunk_id] = rank

    for index, result in enumerate(bm25_results):
        rank = index + 1
        chunk_id = result.chunk_id

        scores_by_chunk_id[chunk_id] = scores_by_chunk_id.get(
            chunk_id,
            0.0,
        ) + (1 / (k + rank))

        result_by_chunk_id.setdefault(chunk_id, result)
        bm25_rank_by_chunk_id[chunk_id] = rank

    sorted_chunk_ids = sorted(
        scores_by_chunk_id,
        key=lambda chunk_id: scores_by_chunk_id[chunk_id],
        reverse=True,
    )

    fused_results = []

    for chunk_id in sorted_chunk_ids[:limit]:
        original_result = result_by_chunk_id[chunk_id]

        fused_results.append(
            HybridRetrievalResult(
                chunk_id=chunk_id,
                text=original_result.text,
                score=scores_by_chunk_id[chunk_id],
                dense_rank=dense_rank_by_chunk_id.get(chunk_id),
                bm25_rank=bm25_rank_by_chunk_id.get(chunk_id),
                metadata=original_result.metadata or {},
            )
        )

    return fused_results


class HybridRetriever:
    def __init__(
        self,
        dense_retriever: CandidateRetriever,
        bm25_retriever: CandidateRetriever,
        rrf_k: int = RRF_K,
        metric_depth: int = HYBRID_METRIC_DEPTH,
    ) -> None:
        self.dense_retriever = dense_retriever
        self.bm25_retriever = bm25_retriever
        self.rrf_k = rrf_k
        self.metric_depth = metric_depth

    def retrieve(self, query: str) -> list[HybridRetrievalResult]:
        dense_candidates = self.dense_retriever.retrieve_candidates(query)
        bm25_candidates = self.bm25_retriever.retrieve_candidates(query)

        return reciprocal_rank_fusion(
            dense_results=dense_candidates,
            bm25_results=bm25_candidates,
            k=self.rrf_k,
            limit=self.metric_depth,
        )