import pytest

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever


class FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        hits = []

        for index in range(50):
            hits.append(
                {
                    "_score": 50 - index,
                    "_source": {
                        "chunk_id": f"chunk_{index}",
                        "text": f"Chunk text {index}",
                        "metadata": {
                            "category": "test",
                        },
                    },
                }
            )

        return {
            "hits": {
                "hits": hits,
            }
        }


def test_bm25_retriever_returns_candidates_and_metric_results(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "backend.app.bm25_retrieval.requests.get",
        fake_get,
    )

    retriever = ElasticsearchBm25Retriever(
        elasticsearch_url="http://example.test:9200",
        index_name="test_chunks",
    )

    candidates = retriever.retrieve_candidates("workspace owner access")
    results = retriever.retrieve("workspace owner access")

    assert len(candidates) == 50
    assert len(results) == 10

    assert results[0].chunk_id == "chunk_0"
    assert results[0].text == "Chunk text 0"
    assert results[0].score == pytest.approx(50.0)
    assert results[0].metadata == {
        "category": "test",
    }