import pytest

from backend.app.providers import GenerationRequest, MockProvider, RetrievedChunk, ProviderConfigurationError, get_provider\
    , ProviderGenerationError, OpenAIProvider, AnthropicProvider, SelfHostedProvider


def test_mock_provider_generates_marked_mock_answer():
    provider = MockProvider()

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is retrieval augmented generation?",
        retrieved_chunks=[
            RetrievedChunk(
                chunk_id="chunk_001",
                text="RAG uses retrieved context to help answer questions.",
                score=0.91,
            )
        ],
    )

    response = provider.generate_answer(request)

    assert response.provider_name == "mock"
    assert response.model_name == "mock-provider-v0"
    assert response.is_mock is True
    assert "case_001" in response.answer_text
    assert response.metadata["retrieved_chunk_count"] == 1

def test_get_provider_returns_mock_provider():
    provider = get_provider("mock")

    assert isinstance(provider, MockProvider)


def test_get_provider_rejects_openai_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError):
        get_provider("openai")

def test_get_provider_returns_openai_provider_when_api_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")

    provider = get_provider("openai")

    assert provider.provider_name == "openai"
    assert provider.model_name == "gpt-4o-mini"

def test_openai_provider_builds_prompt_with_retrieved_context(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    provider = get_provider("openai")

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
        retrieved_chunks=[
            RetrievedChunk(
                chunk_id="chunk_001",
                text="RAG uses retrieved context to answer questions.",
                score=0.9,
            )
        ],
    )

    prompt = provider.build_prompt(request)

    assert "What is RAG?" in prompt
    assert "[chunk_001]" in prompt
    assert "RAG uses retrieved context" in prompt
    assert "Cite supporting chunks" in prompt
    assert "context is insufficient" in prompt
    assert "Answer:" in prompt

def test_anthropic_provider_builds_prompt_with_retrieved_context(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    provider = get_provider("anthropic")

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
        retrieved_chunks=[
            RetrievedChunk(
                chunk_id="chunk_001",
                text="RAG uses retrieved context to answer questions.",
                score=0.9,
            )
        ],
    )

    prompt = provider.build_prompt(request)

    assert "What is RAG?" in prompt
    assert "[chunk_001]" in prompt
    assert "RAG uses retrieved context" in prompt
    assert "Cite supporting chunks" in prompt
    assert "context is insufficient" in prompt
    assert "Answer:" in prompt


def test_anthropic_provider_wraps_generation_errors(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")

    class FailingMessages:
        def create(self, **kwargs):
            raise RuntimeError("simulated Anthropic SDK failure")

    class FailingClient:
        messages = FailingMessages()

    monkeypatch.setattr(
        "backend.app.providers.Anthropic",
        lambda api_key: FailingClient(),
    )

    provider = AnthropicProvider()

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
    )

    with pytest.raises(ProviderGenerationError):
        provider.generate_answer(request)

def test_openai_provider_wraps_generation_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")

    class FailingResponses:
        def create(self, **kwargs):
            raise RuntimeError("simulated OpenAI SDK failure")

    class FailingClient:
        responses = FailingResponses()

    monkeypatch.setattr(
        "backend.app.providers.OpenAI",
        lambda api_key: FailingClient(),
    )

    provider = OpenAIProvider()

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
    )

    with pytest.raises(ProviderGenerationError):
        provider.generate_answer(request)

def test_get_provider_rejects_anthropic_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError):
        get_provider("anthropic")


def test_get_provider_returns_anthropic_provider_when_api_key_exists(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")

    provider = get_provider("anthropic")

    assert provider.provider_name == "anthropic"
    assert provider.model_name == "claude-3-5-haiku-latest"


def test_get_provider_rejects_self_hosted_without_endpoint(monkeypatch):
    monkeypatch.delenv("SELF_HOSTED_MODEL_ENDPOINT", raising=False)

    with pytest.raises(ProviderConfigurationError):
        get_provider("self-hosted")


def test_get_provider_returns_self_hosted_provider_when_endpoint_exists(monkeypatch):
    monkeypatch.setenv(
        "SELF_HOSTED_MODEL_ENDPOINT",
        "http://localhost:8000/generate",
    )

    provider = get_provider("self-hosted")

    assert provider.provider_name == "self-hosted"
    assert provider.model_name == "self-hosted-model"

def test_self_hosted_provider_wraps_generation_errors(monkeypatch):
    monkeypatch.setenv(
        "SELF_HOSTED_MODEL_ENDPOINT",
        "http://localhost:8000/generate",
    )

    def failing_urlopen(request, timeout):
        raise RuntimeError("simulated HTTP failure")

    monkeypatch.setattr(
        "backend.app.providers.urlopen",
        failing_urlopen,
    )

    provider = SelfHostedProvider()

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
    )

    with pytest.raises(ProviderGenerationError):
        provider.generate_answer(request)

def test_self_hosted_provider_generates_from_http_response(monkeypatch):
    monkeypatch.setenv(
        "SELF_HOSTED_MODEL_ENDPOINT",
        "http://localhost:8000/generate",
    )

    class FakeHttpResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"answer_text": "RAG uses retrieved context."}'

    def fake_urlopen(request, timeout):
        return FakeHttpResponse()

    monkeypatch.setattr(
        "backend.app.providers.urlopen",
        fake_urlopen,
    )

    provider = SelfHostedProvider()

    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
    )

    response = provider.generate_answer(request)

    assert response.answer_text == "RAG uses retrieved context."
    assert response.provider_name == "self-hosted"
    assert response.model_name == "self-hosted-model"
    assert response.is_mock is False