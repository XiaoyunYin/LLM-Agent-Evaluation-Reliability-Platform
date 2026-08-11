import pytest

from backend.app.dense_retrieval import to_pgvector_literal
from backend.app.embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingProviderError,
    EmbeddingRequest,
    OpenAIEmbeddingProvider,
)


def test_openai_embedding_provider_returns_embeddings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")

    fake_embedding = [0.1] * EMBEDDING_DIMENSION

    class FakeEmbeddingItem:
        embedding = fake_embedding

    class FakeEmbeddingResponse:
        data = [FakeEmbeddingItem()]

    class FakeEmbeddings:
        def create(self, model, input):
            return FakeEmbeddingResponse()

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(
        "backend.app.embeddings.OpenAI",
        lambda api_key: FakeClient(),
    )

    provider = OpenAIEmbeddingProvider()
    response = provider.embed_texts(
        EmbeddingRequest(texts=["What is dense retrieval?"])
    )

    assert response.provider_name == "openai"
    assert response.model_name == "text-embedding-3-small"
    assert response.dimension == 1536
    assert response.is_mock is False
    assert response.embeddings == [fake_embedding]
    assert response.metadata["input_count"] == 1


def test_openai_embedding_provider_rejects_wrong_dimension(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")

    class FakeEmbeddingItem:
        embedding = [0.1, 0.2, 0.3]

    class FakeEmbeddingResponse:
        data = [FakeEmbeddingItem()]

    class FakeEmbeddings:
        def create(self, model, input):
            return FakeEmbeddingResponse()

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(
        "backend.app.embeddings.OpenAI",
        lambda api_key: FakeClient(),
    )

    provider = OpenAIEmbeddingProvider()

    with pytest.raises(EmbeddingProviderError):
        provider.embed_texts(EmbeddingRequest(texts=["Bad dimension test"]))

def test_to_pgvector_literal_formats_embedding():
    embedding = [0.1] * EMBEDDING_DIMENSION

    literal = to_pgvector_literal(embedding)

    assert literal.startswith("[")
    assert literal.endswith("]")
    assert literal.count(",") == EMBEDDING_DIMENSION - 1


def test_to_pgvector_literal_rejects_wrong_dimension():
    with pytest.raises(ValueError):
        to_pgvector_literal([0.1, 0.2, 0.3])