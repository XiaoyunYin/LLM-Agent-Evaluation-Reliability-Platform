import os
import threading

import requests
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
    # Selects the wording variant. Carried on the request so every provider builds
    # the same prompt for a given run, rather than each implementing its own.
    prompt_version: str = "rag_prompt_v1"
    # Sampling temperature. Defaults to 0 so existing runs stay deterministic.
    # Repeats of one configuration are only meaningful above 0: at temperature 0
    # the same config produces byte-identical answers, so counting them as separate
    # runs would inflate the run count without evaluating anything. Above 0 a repeat
    # is a genuine regression-stability sample.
    temperature: float = 0.0


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

# Prompt variants. These must differ in wording, not only in name: a run matrix that
# varies a label while sending identical text produces byte-identical answers at
# temperature 0, which inflates the run count without evaluating anything.
#
# v1 is the original baseline. v2 hardens abstention, which is the failure mode the
# SQuAD unanswerable cases target. v3 constrains answer length, to test whether
# brevity costs correctness or citation quality.
RAG_PROMPT_INSTRUCTIONS: dict[str, str] = {
    "rag_prompt_v1": (
        "Answer the question using only the retrieved context when it contains enough information.\n"
        "Cite supporting chunks with their chunk IDs in square brackets, like [chunk_001].\n"
        "If the retrieved context is not enough, say that the context is insufficient."
    ),
    "rag_prompt_v2": (
        "Answer strictly from the retrieved context below. Do not use outside knowledge.\n"
        "Cite every supporting chunk by its chunk ID in square brackets, like [chunk_001].\n"
        "Before answering, check whether the context actually states the answer. If it does\n"
        "not, reply exactly: The context is insufficient to answer this question.\n"
        "Do not guess, infer beyond the text, or fill gaps from memory."
    ),
    "rag_prompt_v3": (
        "Answer the question in at most two sentences, using only the retrieved context.\n"
        "Cite supporting chunks with their chunk IDs in square brackets, like [chunk_001].\n"
        "Prefer the shortest complete answer. If the context is not enough, say that the\n"
        "context is insufficient."
    ),
}

DEFAULT_RAG_PROMPT_VERSION = "rag_prompt_v1"


class UnknownPromptVersionError(Exception):
    pass


def build_generation_prompt(
    request: GenerationRequest,
    prompt_version: str = DEFAULT_RAG_PROMPT_VERSION,
) -> str:
    instructions = RAG_PROMPT_INSTRUCTIONS.get(prompt_version)
    if instructions is None:
        raise UnknownPromptVersionError(
            f"Unknown prompt_version {prompt_version!r}. "
            f"Known: {sorted(RAG_PROMPT_INSTRUCTIONS)}"
        )

    chunk_texts = [
        f"[{chunk.chunk_id}] {chunk.text}"
        for chunk in request.retrieved_chunks
    ]

    context_block = "\n\n".join(chunk_texts) if chunk_texts else "No retrieved context."

    return (
        f"{instructions}\n\n"
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
        return build_generation_prompt(request, request.prompt_version)

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        prompt = self.build_prompt(request)
        client = OpenAI(api_key=self.api_key)

        try:
            response = client.responses.create(
                model=self.model_name,
                input=prompt,
                temperature=request.temperature,
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
        return build_generation_prompt(request, request.prompt_version)

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        prompt = self.build_prompt(request)
        client = Anthropic(api_key=self.api_key)

        try:
            response = client.messages.create(
                model=self.model_name,
                max_tokens=512,
                temperature=request.temperature,
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
        self._usage_lock = threading.Lock()
        self.total_completion_tokens = 0
        self.total_prompt_tokens = 0

        if not self.endpoint:
            raise ProviderConfigurationError(
                f"Missing {endpoint_env}. Set this environment variable before using SelfHostedProvider."
            )
        
    def build_prompt(self, request: GenerationRequest) -> str:
        return build_generation_prompt(request, request.prompt_version)
    
    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        """Call an OpenAI-compatible chat-completions endpoint.

        vLLM serves the OpenAI schema, so this posts `messages` and reads
        `choices[0].message.content`. The previous implementation posted a bespoke
        {"prompt": ...} body and expected {"answer_text": ...} back, which no vLLM
        deployment answers -- it had never been run against a real endpoint.

        Token usage is accumulated so generation throughput can be measured from the
        workload itself rather than from a separate benchmark.
        """
        prompt = self.build_prompt(request)

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": request.temperature,
            "max_tokens": 512,
        }
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("SELF_HOSTED_MODEL_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            response = requests.post(
                self.endpoint, json=payload, headers=headers, timeout=180
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ProviderGenerationError(
                f"Self-hosted generation failed: {exc}"
            ) from exc

        try:
            answer_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderGenerationError(
                "Self-hosted endpoint did not return OpenAI chat-completions JSON; "
                f"got keys {sorted(data)[:6]}"
            ) from exc

        usage = data.get("usage") or {}
        with self._usage_lock:
            self.total_completion_tokens += int(usage.get("completion_tokens") or 0)
            self.total_prompt_tokens += int(usage.get("prompt_tokens") or 0)

        return GenerationResponse(
            answer_text=answer_text,
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=False,
            metadata={
                "run_id": request.run_id,
                "case_id": request.case_id,
                "retrieved_chunk_count": len(request.retrieved_chunks),
                "endpoint": self.endpoint,
                "prompt_version": request.prompt_version,
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
