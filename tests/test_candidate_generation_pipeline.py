from pathlib import Path
from uuid import uuid4

import scripts.run_eval_worker as eval_worker
from backend.app.candidate_generation import (
    build_request_for_case,
    case_requires_retrieval,
    CandidateGenerationRunConfig,
    candidate_answers_path,
    generate_candidate_answers_for_run,
)
from backend.app.eval_case import EvalCase
from backend.app.eval_run import EvalRun
from backend.app.providers import GenerationRequest, GenerationResponse
from backend.app.queue_jobs import EvalRunJobPayload, build_run_key, save_eval_run


class FakeProvider:
    provider_name = "openai"
    model_name = "fake-model"

    def __init__(self):
        self.calls: list[str] = []

    def generate_answer(self, request: GenerationRequest) -> GenerationResponse:
        self.calls.append(request.case_id)
        return GenerationResponse(
            answer_text=f"answer for {request.case_id}",
            provider_name=self.provider_name,
            model_name=self.model_name,
            is_mock=False,
            metadata={"fake": True},
        )


class FakeRedis:
    def __init__(self):
        self.hashes = {}

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.hashes.get(key, {})


def test_candidate_generation_writes_answers_and_resumes_by_skipping_completed_cases():
    run_id = f"test_resume_{uuid4().hex}"
    output_dir = Path("runs/test_candidate_generation_pipeline")
    provider = FakeProvider()
    config = CandidateGenerationRunConfig(
        run_id=run_id,
        dataset_version="golden_agentic_tools_v0.1",
        provider_name="openai",
        model_name="fake-model",
        task_family="agentic_tool_calling",
        retrieval_mode="tool_calling_no_retrieval",
        prompt_version="agentic_prompt_v1",
        repeat_id="repeat_01",
        matrix_id="test_matrix",
        expected_case_count=2,
    )

    first = generate_candidate_answers_for_run(
        config=config,
        output_dir=output_dir,
        provider=provider,
    )
    second = generate_candidate_answers_for_run(
        config=config,
        output_dir=output_dir,
        provider=provider,
    )

    output_path = candidate_answers_path(run_id, output_dir=output_dir)
    rows = [line for line in output_path.read_text(encoding="utf-8").splitlines() if line]

    assert first.status == "completed"
    assert first.generated_count == 2
    assert second.status == "completed"
    assert second.generated_count == 0
    assert second.skipped_count == 2
    assert len(rows) == 2
    assert provider.calls == ["AT-001", "AT-002"]


def test_worker_dispatches_real_provider_payload_to_candidate_generation(monkeypatch):
    client = FakeRedis()
    run = EvalRun(
        run_id="worker_candidate_generation_001",
        dataset_version="golden_agentic_tools_v0.1",
        provider_name="openai",
    )
    save_eval_run(client, run)
    payload = EvalRunJobPayload(
        run_id=run.run_id,
        dataset_version=run.dataset_version,
        provider_name="openai",
        model_name="gpt-4o-mini",
        task_family="agentic_tool_calling",
        retrieval_mode="tool_calling_no_retrieval",
        prompt_version="agentic_prompt_v1",
        repeat_id="repeat_01",
        matrix_id="test_matrix",
        expected_case_count=2,
    )

    def fake_generate(config):
        return type(
            "Summary",
            (),
            {
                "status": "completed",
                "final_completed_count": 2,
                "output_path": "runs/test/file.jsonl",
                "model_dump": lambda self, mode=None: {},
            },
        )()

    monkeypatch.setattr(eval_worker, "generate_candidate_answers_for_run", fake_generate)

    eval_worker.handle_eval_run_job(payload, client)

    stored_run = client.hgetall(build_run_key(run.run_id))
    result = client.hgetall(f"eval_run_result:{run.run_id}")

    assert stored_run["status"] == "completed"
    assert result["candidate_answer_count"] == 2
    assert result["provider_name"] == "openai"


def _case(case_id: str, task_type: str, **metadata):
    return EvalCase(
        id=case_id,
        question="q",
        expected_answer="a",
        task_type=task_type,
        metadata=metadata,
    )


def test_only_retrieval_grounded_cases_receive_retrieved_context():
    """Guard against the Session 44 failure mode.

    A run configured as task_family="rag" used to hand retrieved context to every
    case in the dataset. When the dataset mixed task types that fed support
    runbook chunks to arithmetic questions, so the model refused and every judge
    score collapsed to zero.
    """
    assert case_requires_retrieval(_case("a", "rag_qa")) is True
    assert case_requires_retrieval(_case("b", "direct_qa")) is False
    assert case_requires_retrieval(_case("c", "judge_behavior")) is False
    assert case_requires_retrieval(_case("d", "prompt_comparison")) is False
    assert case_requires_retrieval(_case("e", "regression_stability")) is False


def test_dataset_row_can_override_retrieval_routing():
    assert case_requires_retrieval(_case("a", "direct_qa", requires_retrieval=True)) is True
    assert case_requires_retrieval(_case("b", "rag_qa", requires_retrieval=False)) is False


def test_non_retrieval_case_gets_empty_context_even_when_retriever_present():
    class ExplodingRetriever:
        def retrieve(self, query):  # pragma: no cover - must never be called
            raise AssertionError("retrieval ran for a non-retrieval case")

    config = CandidateGenerationRunConfig(
        run_id="run_routing",
        dataset_version="golden_rag_v0.2",
        provider_name="mock",
        model_name="mock",
        task_family="rag",
    )
    _, citations = build_request_for_case(
        config, _case("MA-001", "direct_qa"), ExplodingRetriever()
    )

    assert citations["retrieved_chunk_ids"] == []
    assert citations["generation_context_chunk_ids"] == []
