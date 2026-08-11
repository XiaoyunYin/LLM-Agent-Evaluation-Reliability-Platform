from backend.app.generation import (
    build_citation_fields,
    build_rag_generation_request,
    generate_answer,
    retrieve_context_and_build_rag_request,
    select_generation_context,
)
from backend.app.providers import GenerationRequest, MockProvider, RetrievedChunk


def test_generate_answer_uses_provider_interface():
    request = GenerationRequest(
        run_id="run_001",
        case_id="case_001",
        question="What is RAG?",
    )

    response = generate_answer(MockProvider(), request)

    assert response.provider_name == "mock"
    assert response.is_mock is True
    assert "case_001" in response.answer_text

def test_select_generation_context_keeps_top_chunks_within_limits():
    chunks = [
        RetrievedChunk(chunk_id="chunk_001", text="short context"),
        RetrievedChunk(chunk_id="chunk_002", text="more short context"),
        RetrievedChunk(
            chunk_id="chunk_003",
            text="this chunk is intentionally very long " * 20,
        ),
        RetrievedChunk(chunk_id="chunk_004", text="final useful context"),
        RetrievedChunk(chunk_id="chunk_005", text="extra context"),
    ]

    selected_chunks = select_generation_context(
        retrieved_chunks=chunks,
        max_chunks=4,
        context_token_budget=20,
    )

    selected_chunk_ids = [chunk.chunk_id for chunk in selected_chunks]

    assert len(selected_chunks) <= 4
    assert selected_chunk_ids == ["chunk_001", "chunk_002", "chunk_004", "chunk_005"]
    assert "chunk_003" not in selected_chunk_ids

def test_build_citation_fields_tracks_retrieved_and_generation_context_ids():
    retrieved_chunks = [
        RetrievedChunk(
            chunk_id="chunk_001",
            text="first",
            metadata={
                "source_path": "datasets/corpus/raw/doc_001.md",
                "title": "Doc 001",
                "category": "accounts",
            },
        ),
        RetrievedChunk(chunk_id="chunk_002", text="second"),
        RetrievedChunk(chunk_id="chunk_003", text="third"),
    ]
    generation_context_chunks = retrieved_chunks[:2]

    citation_fields = build_citation_fields(
        retrieved_chunks=retrieved_chunks,
        generation_context_chunks=generation_context_chunks,
    )
    assert citation_fields["generation_context_citations"][0] == {
        "chunk_id": "chunk_001",
        "source_path": "datasets/corpus/raw/doc_001.md",
        "title": "Doc 001",
        "category": "accounts",
    }
    assert citation_fields["retrieved_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
        "chunk_003",
    ]
    assert citation_fields["generation_context_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
    ]

def test_build_rag_generation_request_uses_selected_context_and_tracks_all_ids():
    retrieved_chunks = [
        RetrievedChunk(chunk_id="chunk_001", text="short context"),
        RetrievedChunk(chunk_id="chunk_002", text="more short context"),
        RetrievedChunk(
            chunk_id="chunk_003",
            text="this chunk is intentionally very long " * 20,
        ),
        RetrievedChunk(chunk_id="chunk_004", text="final useful context"),
    ]

    request, citation_fields = build_rag_generation_request(
        run_id="run_001",
        case_id="case_001",
        question="What does the policy say?",
        retrieved_chunks=retrieved_chunks,
        max_context_chunks=4,
        context_token_budget=20,
    )

    assert request.run_id == "run_001"
    assert request.case_id == "case_001"
    assert request.question == "What does the policy say?"
    assert [chunk.chunk_id for chunk in request.retrieved_chunks] == [
        "chunk_001",
        "chunk_002",
        "chunk_004",
    ]
    assert citation_fields["retrieved_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
        "chunk_003",
        "chunk_004",
    ]
    assert citation_fields["generation_context_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
        "chunk_004",
    ]

class FakeRetriever:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def retrieve(self, query: str):
        self.queries.append(query)
        return self.results


def test_retrieve_context_and_build_rag_request_uses_retriever_results():
    chunks = [
        RetrievedChunk(chunk_id="chunk_001", text="short context", score=0.9),
        RetrievedChunk(chunk_id="chunk_002", text="more short context", score=0.8),
        RetrievedChunk(
            chunk_id="chunk_003",
            text="this chunk is intentionally very long " * 20,
            score=0.7,
        ),
    ]
    retriever = FakeRetriever(chunks)

    request, citation_fields = retrieve_context_and_build_rag_request(
        retriever=retriever,
        run_id="run_001",
        case_id="case_001",
        question="What does the policy say?",
        context_token_budget=20,
    )

    assert retriever.queries == ["What does the policy say?"]
    assert [chunk.chunk_id for chunk in request.retrieved_chunks] == [
        "chunk_001",
        "chunk_002",
    ]
    assert citation_fields["retrieved_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
        "chunk_003",
    ]