import json

from backend.app.providers import GenerationResponse
from backend.app.providers import RetrievedChunk
from scripts import mock_generate_answers
from scripts.mock_generate_answers import run_local_mock_generation


def test_mock_generate_answers_writes_one_candidate_per_case(tmp_path):
    dataset_path = tmp_path / "tiny_dataset.jsonl"
    output_dir = tmp_path / "runs"

    cases = [
        {
            "id": "case_001",
            "question": "What is 2 + 2?",
            "expected_answer": "4",
            "task_type": "direct_qa",
            "metadata": {},
        },
        {
            "id": "case_002",
            "question": "What is RAG?",
            "expected_answer": "Retrieval augmented generation.",
            "task_type": "direct_qa",
            "metadata": {},
        },
    ]

    with dataset_path.open("w", encoding="utf-8") as file:
        for case in cases:
            file.write(json.dumps(case) + "\n")

    summary = mock_generate_answers.run_local_mock_generation(
        dataset_path=dataset_path,
        output_dir=output_dir,
        run_id="test_run_001",
    )

    rows = [
        json.loads(line)
        for line in summary.output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert len(rows) == 2
    assert rows[0]["run_id"] == "test_run_001"
    assert rows[0]["case_id"] == "case_001"
    assert rows[0]["provider_name"] == "mock"
    assert rows[0]["is_mock"] is True
    assert rows[0]["generated_answer"].strip()


def test_run_local_mock_generation_uses_selected_provider(
    tmp_path,
    monkeypatch,
):
    dataset_path = tmp_path / "tiny_dataset.jsonl"

    case = {
        "id": "case_001",
        "question": "What is 2 + 2?",
        "expected_answer": "4",
        "task_type": "direct_qa",
        "metadata": {},
    }

    dataset_path.write_text(json.dumps(case) + "\n", encoding="utf-8")
    selected_provider_names = []

    class ScriptTestProvider:
        provider_name = "script-test"
        model_name = "script-test-model"

        def generate_answer(self, request):
            selected_provider_names.append("script-test")
            return GenerationResponse(
                answer_text=f"script answer for {request.case_id}",
                provider_name=self.provider_name,
                model_name=self.model_name,
                is_mock=True,
                metadata={"case_id": request.case_id},
            )

    monkeypatch.setattr(
        "scripts.mock_generate_answers.get_provider",
        lambda provider_name: ScriptTestProvider(),
    )

    summary = run_local_mock_generation(
        dataset_path=dataset_path,
        output_dir=tmp_path,
        provider_name="script-test",
    )

    assert summary.candidate_answers_saved == 1
    assert selected_provider_names == ["script-test"]

def test_run_local_mock_generation_saves_retrieval_and_context_metadata(tmp_path):
    dataset_path = tmp_path / "tiny_dataset.jsonl"
    output_dir = tmp_path / "runs"

    case = {
        "id": "case_001",
        "question": "What does the policy say?",
        "expected_answer": "Use the retrieved policy context.",
        "task_type": "rag_qa",
        "metadata": {},
    }

    dataset_path.write_text(json.dumps(case) + "\n", encoding="utf-8")

    retrieved_chunks_by_case_id = {
        "case_001": [
            RetrievedChunk(chunk_id="chunk_001", text="short context"),
            RetrievedChunk(chunk_id="chunk_002", text="more short context"),
            RetrievedChunk(
                chunk_id="chunk_003",
                text="this chunk is intentionally very long " * 20,
            ),
            RetrievedChunk(chunk_id="chunk_004", text="final useful context"),
        ]
    }

    summary = run_local_mock_generation(
        dataset_path=dataset_path,
        output_dir=output_dir,
        run_id="test_run_001",
        retrieved_chunks_by_case_id=retrieved_chunks_by_case_id,
        context_token_budget=20,
    )

    rows = [
        json.loads(line)
        for line in summary.output_path.read_text(encoding="utf-8").splitlines()
    ]

    metadata = rows[0]["metadata"]

    assert summary.candidate_answers_saved == 1
    assert metadata["retrieved_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
        "chunk_003",
        "chunk_004",
    ]
    assert metadata["generation_context_chunk_ids"] == [
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


def test_run_local_mock_generation_can_use_retriever(tmp_path):
    dataset_path = tmp_path / "tiny_dataset.jsonl"

    case = {
        "id": "case_001",
        "question": "What does the policy say?",
        "expected_answer": "Use the retrieved policy context.",
        "task_type": "rag_qa",
        "metadata": {},
    }

    dataset_path.write_text(json.dumps(case) + "\n", encoding="utf-8")

    retriever = FakeRetriever(
        [
            RetrievedChunk(chunk_id="chunk_001", text="short context", score=0.9),
            RetrievedChunk(chunk_id="chunk_002", text="more short context", score=0.8),
        ]
    )

    summary = run_local_mock_generation(
        dataset_path=dataset_path,
        output_dir=tmp_path,
        run_id="test_run_001",
        retriever=retriever,
    )

    rows = [
        json.loads(line)
        for line in summary.output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert retriever.queries == ["What does the policy say?"]
    assert rows[0]["metadata"]["retrieved_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
    ]
    assert rows[0]["metadata"]["generation_context_chunk_ids"] == [
        "chunk_001",
        "chunk_002",
    ]

def test_build_hybrid_retriever_wires_dense_bm25_and_embedding(monkeypatch):
    created = {}

    class FakeEmbeddingProvider:
        pass

    class FakeDenseRetriever:
        def __init__(self, embedding_provider):
            created["embedding_provider"] = embedding_provider

    class FakeBm25Retriever:
        pass

    class FakeHybridRetriever:
        def __init__(self, dense_retriever, bm25_retriever):
            created["dense_retriever"] = dense_retriever
            created["bm25_retriever"] = bm25_retriever

    monkeypatch.setattr(
        "scripts.mock_generate_answers.OpenAIEmbeddingProvider",
        FakeEmbeddingProvider,
    )
    monkeypatch.setattr(
        "scripts.mock_generate_answers.PostgresDenseRetriever",
        FakeDenseRetriever,
    )
    monkeypatch.setattr(
        "scripts.mock_generate_answers.ElasticsearchBm25Retriever",
        FakeBm25Retriever,
    )
    monkeypatch.setattr(
        "scripts.mock_generate_answers.HybridRetriever",
        FakeHybridRetriever,
    )

    retriever = mock_generate_answers.build_hybrid_retriever()

    assert isinstance(retriever, FakeHybridRetriever)
    assert isinstance(created["embedding_provider"], FakeEmbeddingProvider)
    assert isinstance(created["dense_retriever"], FakeDenseRetriever)
    assert isinstance(created["bm25_retriever"], FakeBm25Retriever)


def test_main_uses_hybrid_retriever_when_flag_is_set(monkeypatch):
    calls = {}

    class FakeSummary:
        run_id = "run_001"
        dataset_path = "dataset.jsonl"
        cases_loaded = 1
        candidate_answers_saved = 1
        output_path = "answers.jsonl"

    fake_retriever = object()

    monkeypatch.setattr(
        "scripts.mock_generate_answers.parse_args",
        lambda: type(
            "Args",
            (),
            {
                "provider": "mock",
                "use_hybrid_retrieval": True,
                "limit": None,
            },
        )(),
    )
    monkeypatch.setattr(
        "scripts.mock_generate_answers.build_hybrid_retriever",
        lambda: fake_retriever,
    )

    def fake_run_local_mock_generation(provider_name, retriever, case_limit):
        calls["provider_name"] = provider_name
        calls["retriever"] = retriever
        calls["case_limit"] = case_limit
        return FakeSummary()

    monkeypatch.setattr(
        "scripts.mock_generate_answers.run_local_mock_generation",
        fake_run_local_mock_generation,
    )

    mock_generate_answers.main()

    assert calls["provider_name"] == "mock"
    assert calls["retriever"] is fake_retriever
    assert calls["case_limit"] is None

def test_run_local_mock_generation_can_limit_cases(tmp_path):
    dataset_path = tmp_path / "tiny_dataset.jsonl"

    cases = [
        {
            "id": "case_001",
            "question": "Question 1?",
            "expected_answer": "Answer 1.",
            "task_type": "direct_qa",
            "metadata": {},
        },
        {
            "id": "case_002",
            "question": "Question 2?",
            "expected_answer": "Answer 2.",
            "task_type": "direct_qa",
            "metadata": {},
        },
    ]

    dataset_path.write_text(
        "\n".join(json.dumps(case) for case in cases) + "\n",
        encoding="utf-8",
    )

    summary = run_local_mock_generation(
        dataset_path=dataset_path,
        output_dir=tmp_path,
        run_id="test_run_001",
        case_limit=1,
    )

    rows = [
        json.loads(line)
        for line in summary.output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert summary.cases_loaded == 1
    assert summary.candidate_answers_saved == 1
    assert len(rows) == 1
    assert rows[0]["case_id"] == "case_001"