import os
from typing import Any, Protocol
from openai import OpenAI
from anthropic import Anthropic
from pydantic import BaseModel, ConfigDict, Field
import json
from urllib.request import Request, urlopen


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationRequest(BaseModel):
    run_id: str
    case_id: str
    question: str
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)


class GenerationResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    answer_text: str
    provider_name: str
    model_name: str
    is_mock: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(Protocol):
    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        ...

class ProviderConfigurationError(Exception):
    pass


class ProviderGenerationError(Exception):
    pass

def build_generation_prompt(request: GenerationRequest) -> str:
    chunk_texts = [
        f"[{chunk.chunk_id}] {chunk.text}"
        for chunk in request.retrieved_chunks
    ]

    context_block = "\n\n".join(chunk_texts) if chunk_texts else "No retrieved context."

    return (
        "Answer the question using only the retrieved context when it contains enough information.\n"
        "Cite supporting chunks with their chunk IDs in square brackets, like [chunk_001].\n"
        "If the retrieved context is not enough, say that the context is insufficient.\n\n"
        f"Question:\n{request.question}\n\n"
        f"Retrieved context:\n{context_block}\n\n"
        "Answer:"
    )

class MockProvider:
    provider_name = "mock"
    model_name = "mock-provider-v0"

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        chunk_count = len(request.retrieved_chunks)

        return GenerationResponse(
            answer_text=(
                f"[MOCK ANSWER] case={request.case_id}; "
                f"question={request.question}; "
                f"retrieved_chunks={chunk_count}"
            ),
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=True,
            metadata={
                "run_id": request.run_id,
                "case_id": request.case_id,
                "retrieved_chunk_count": chunk_count,
            },
        )

class OpenAIProvider:
    provider_name = "openai"

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model_name = model_name
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env)

        if not self.api_key:
            raise ProviderConfigurationError(
                f"Missing {api_key_env}. Set this environment variable before using OpenAIProvider."
            )

    def build_prompt(self, request: GenerationRequest) -> str:
        return build_generation_prompt(request)

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        prompt = self.build_prompt(request)
        client = OpenAI(api_key=self.api_key)

        try:
            response = client.responses.create(
                model=self.model_name,
                input=prompt,
                temperature=0,
            )
        except Exception as exc:
            raise ProviderGenerationError("OpenAI generation failed.") from exc

        return GenerationResponse(
            answer_text=response.output_text,
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=False,
            metadata={
                "run_id": request.run_id,
                "case_id": request.case_id,
                "retrieved_chunk_count": len(request.retrieved_chunks),
            },
        )

class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(
        self,
        model_name: str = "claude-3-5-haiku-latest",
        api_key_env: str = "ANTHROPIC_API_KEY",
    ) -> None:
        self.model_name = model_name
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env)

        if not self.api_key:
            raise ProviderConfigurationError(
                f"Missing {api_key_env}. Set this environment variable before using AnthropicProvider."
            )

    def build_prompt(self, request: GenerationRequest) -> str:
        return build_generation_prompt(request)

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        prompt = self.build_prompt(request)
        client = Anthropic(api_key=self.api_key)

        try:
            response = client.messages.create(
                model=self.model_name,
                max_tokens=512,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
        except Exception as exc:
            raise ProviderGenerationError("Anthropic generation failed.") from exc

        answer_text = response.content[0].text

        return GenerationResponse(
            answer_text=answer_text,
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=False,
            metadata={
                "run_id": request.run_id,
                "case_id": request.case_id,
                "retrieved_chunk_count": len(request.retrieved_chunks),
            },
        )

class SelfHostedProvider:
    provider_name = "self-hosted"

    def __init__(
        self,
        model_name: str = "self-hosted-model",
        endpoint_env: str = "SELF_HOSTED_MODEL_ENDPOINT",
    ) -> None:
        self.model_name = model_name
        self.endpoint_env = endpoint_env
        self.endpoint = os.environ.get(endpoint_env)

        if not self.endpoint:
            raise ProviderConfigurationError(
                f"Missing {endpoint_env}. Set this environment variable before using SelfHostedProvider."
            )
        
    def build_prompt(self, request: GenerationRequest) -> str:
        return build_generation_prompt(request)
    
    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        prompt = self.build_prompt(request)

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "temperature": 0,
        }

        http_request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(http_request, timeout=60) as response:
                response_body = response.read().decode("utf-8")
                response_data = json.loads(response_body)
        except Exception as exc:
            raise ProviderGenerationError("Self-hosted generation failed.") from exc

        return GenerationResponse(
            answer_text=response_data["answer_text"],
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=False,
            metadata={
                "run_id": request.run_id,
                "case_id": request.case_id,
                "retrieved_chunk_count": len(request.retrieved_chunks),
                "endpoint": self.endpoint,
            },
        )
    
def get_provider(name: str) -> LLMProvider:
    normalized_name = name.strip().lower()

    if normalized_name == "mock":
        return MockProvider()

    if normalized_name == "openai":
        return OpenAIProvider()

    if normalized_name == "anthropic":
        return AnthropicProvider()

    if normalized_name == "self-hosted":
        return SelfHostedProvider()

    raise ProviderConfigurationError(f"Unknown provider: {name}")
