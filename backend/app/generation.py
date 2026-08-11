from backend.app.providers import GenerationRequest, GenerationResponse, LLMProvider, RetrievedChunk
from typing import Protocol

APPROX_CHARS_PER_TOKEN = 4


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // APPROX_CHARS_PER_TOKEN)


def select_generation_context(
    retrieved_chunks: list[RetrievedChunk],
    max_chunks: int = 4,
    context_token_budget: int = 2_000,
) -> list[RetrievedChunk]:
    selected_chunks = []
    used_tokens = 0

    for chunk in retrieved_chunks:
        if len(selected_chunks) >= max_chunks:
            break

        chunk_tokens = estimate_token_count(chunk.text)

        if used_tokens + chunk_tokens > context_token_budget:
            continue

        selected_chunks.append(chunk)
        used_tokens += chunk_tokens

    return selected_chunks

def build_citation_fields(
    retrieved_chunks: list[RetrievedChunk],
    generation_context_chunks: list[RetrievedChunk],
) -> dict[str, list[str]]:
    return {
        "retrieved_chunk_ids": [
            chunk.chunk_id
            for chunk in retrieved_chunks
        ],
        "generation_context_chunk_ids": [
            chunk.chunk_id
            for chunk in generation_context_chunks
        ],
        "generation_context_citations": [
            {
                "chunk_id": chunk.chunk_id,
                "source_path": chunk.metadata.get("source_path"),
                "title": chunk.metadata.get("title"),
                "category": chunk.metadata.get("category"),
            }
            for chunk in generation_context_chunks
        ],
    }

def build_rag_generation_request(
    run_id: str,
    case_id: str,
    question: str,
    retrieved_chunks: list[RetrievedChunk],
    max_context_chunks: int = 4,
    context_token_budget: int = 2_000,
) -> tuple[GenerationRequest, dict[str, list[str]]]:
    generation_context_chunks = select_generation_context(
        retrieved_chunks=retrieved_chunks,
        max_chunks=max_context_chunks,
        context_token_budget=context_token_budget,
    )

    request = GenerationRequest(
        run_id=run_id,
        case_id=case_id,
        question=question,
        retrieved_chunks=generation_context_chunks,
    )

    citation_fields = build_citation_fields(
        retrieved_chunks=retrieved_chunks,
        generation_context_chunks=generation_context_chunks,
    )

    return request, citation_fields

class Retriever(Protocol):
    def retrieve(self, query: str) -> list:
        ...


def retrieve_context_and_build_rag_request(
    retriever: Retriever,
    run_id: str,
    case_id: str,
    question: str,
    max_context_chunks: int = 4,
    context_token_budget: int = 2_000,
) -> tuple[GenerationRequest, dict]:
    retrieved_chunks = [
        RetrievedChunk(
            chunk_id=result.chunk_id,
            text=result.text,
            score=result.score,
            metadata=result.metadata,
        )
        for result in retriever.retrieve(question)
    ]

    return build_rag_generation_request(
        run_id=run_id,
        case_id=case_id,
        question=question,
        retrieved_chunks=retrieved_chunks,
        max_context_chunks=max_context_chunks,
        context_token_budget=context_token_budget,
    )


def generate_answer(
    provider: LLMProvider,
    request: GenerationRequest,
) -> GenerationResponse:
    return provider.generate_answer(request)