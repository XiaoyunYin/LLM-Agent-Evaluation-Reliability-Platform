from dataclasses import dataclass

from backend.app.hybrid_retrieval import HybridRetriever, reciprocal_rank_fusion


@dataclass
class FakeRetrievalResult:
    chunk_id: str
    text: str = ""
    score: float = 0.0
    metadata: dict | None = None


def test_reciprocal_rank_fusion_combines_dense_and_bm25_rankings():
    dense_results = [
        FakeRetrievalResult(chunk_id="A"),
        FakeRetrievalResult(chunk_id="B"),
        FakeRetrievalResult(chunk_id="C"),
    ]
    bm25_results = [
        FakeRetrievalResult(chunk_id="B"),
        FakeRetrievalResult(chunk_id="D"),
        FakeRetrievalResult(chunk_id="A"),
    ]

    fused_results = reciprocal_rank_fusion(
        dense_results=dense_results,
        bm25_results=bm25_results,
        k=60,
        limit=3,
    )

    fused_chunk_ids = [result.chunk_id for result in fused_results]

    assert fused_chunk_ids == ["B", "A", "D"]


class FakeCandidateRetriever:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def retrieve_candidates(self, query: str):
        self.queries.append(query)

        return self.results


def test_hybrid_retriever_fuses_dense_and_bm25_candidates():
    dense_retriever = FakeCandidateRetriever(
        [
            FakeRetrievalResult(chunk_id="A"),
            FakeRetrievalResult(chunk_id="B"),
            FakeRetrievalResult(chunk_id="C"),
        ]
    )
    bm25_retriever = FakeCandidateRetriever(
        [
            FakeRetrievalResult(chunk_id="B"),
            FakeRetrievalResult(chunk_id="D"),
            FakeRetrievalResult(chunk_id="A"),
        ]
    )

    hybrid_retriever = HybridRetriever(
        dense_retriever=dense_retriever,
        bm25_retriever=bm25_retriever,
        rrf_k=60,
        metric_depth=2,
    )

    results = hybrid_retriever.retrieve("reset account password")

    assert [result.chunk_id for result in results] == ["B", "A"]
    assert dense_retriever.queries == ["reset account password"]
    assert bm25_retriever.queries == ["reset account password"]
    assert results[0].dense_rank == 2
    assert results[0].bm25_rank == 1