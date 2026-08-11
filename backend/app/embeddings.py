import os
from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536


class EmbeddingRequest(BaseModel):
    texts: list[str]


class EmbeddingResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    embeddings: list[list[float]]
    provider_name: str
    model_name: str
    dimension: int
    is_mock: bool
    metadata: dict[str, object] = Field(default_factory=dict)


class EmbeddingProvider(Protocol):
    def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        ...


class EmbeddingConfigurationError(Exception):
    pass


class EmbeddingProviderError(Exception):
    pass


class OpenAIEmbeddingProvider:
    provider_name = "openai"

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model_name = model_name
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env)

        if not self.api_key:
            raise EmbeddingConfigurationError(
                f"Missing {api_key_env}. Set this environment variable before using OpenAIEmbeddingProvider."
            )

    def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        client = OpenAI(api_key=self.api_key)

        try:
            response = client.embeddings.create(
                model=self.model_name,
                input=request.texts,
            )
        except Exception as exc:
            raise EmbeddingProviderError("OpenAI embedding request failed.") from exc

        embeddings = [item.embedding for item in response.data]

        for embedding in embeddings:
            if len(embedding) != EMBEDDING_DIMENSION:
                raise EmbeddingProviderError(
                    f"Expected embedding dimension {EMBEDDING_DIMENSION}, got {len(embedding)}."
                )

        return EmbeddingResponse(
            embeddings=embeddings,
            provider_name=self.provider_name,
            model_name=self.model_name,
            dimension=EMBEDDING_DIMENSION,
            is_mock=False,
            metadata={
                "input_count": len(request.texts),
            },
        )
