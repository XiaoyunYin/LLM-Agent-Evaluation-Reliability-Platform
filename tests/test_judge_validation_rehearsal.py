import json
from pathlib import Path

from backend.app.dataset_loader import load_eval_cases
from backend.app.dual_judge_validation import run_dual_judge_validation
from scripts.rehearse_judge_validation import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_HELDOUT_LABELS_PATH,
    DeterministicRehearsalGptJudge,
    build_mock_7b_judge,
    create_validation_slice_artifacts,
    load_candidate_answers,
)


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rehearsal_builds_120_answer_slice_from_heldout_queries():
    output_dir = Path("runs/test_judge_validation_rehearsal")

    eval_cases_path, candidate_answers_path, contexts_by_case_id, run_id = (
        create_validation_slice_artifacts(
            heldout_labels_path=DEFAULT_HELDOUT_LABELS_PATH,
            chunks_path=DEFAULT_CHUNKS_PATH,
            output_dir=output_dir,
            limit=120,
            run_id="test_rehearsal_120",
        )
    )

    cases = load_eval_cases(eval_cases_path)
    candidate_rows = read_jsonl(candidate_answers_path)

    assert run_id == "test_rehearsal_120"
    assert len(cases) == 120
    assert len(candidate_rows) == 120
    assert cases[0].id == "RH-001"
    assert candidate_rows[0]["case_id"] == "RH-001"
    assert cases[0].metadata["labels_created_blind_to_judge_outputs"] is True
    assert candidate_rows[0]["is_mock"] is True
    assert candidate_rows[0]["metadata"]["candidate_answer_is_final"] is False
    assert len(contexts_by_case_id) == 120
    assert contexts_by_case_id["RH-001"][0].startswith(
        "[doc_support_accounts_0001_chunk_0001]"
    )


def test_rehearsal_runs_same_slice_through_standin_gpt_and_mock_7b():
    output_dir = Path("runs/test_judge_validation_rehearsal")
    eval_cases_path, candidate_answers_path, contexts_by_case_id, _ = (
        create_validation_slice_artifacts(
            heldout_labels_path=DEFAULT_HELDOUT_LABELS_PATH,
            chunks_path=DEFAULT_CHUNKS_PATH,
            output_dir=output_dir,
            limit=3,
            run_id="test_rehearsal_pipeline",
        )
    )
    cases = load_eval_cases(eval_cases_path)
    candidates = load_candidate_answers(candidate_answers_path)

    result = run_dual_judge_validation(
        cases=cases,
        candidates=candidates,
        judge_a=DeterministicRehearsalGptJudge(),
        judge_b=build_mock_7b_judge(),
        retrieved_context_by_case_id=contexts_by_case_id,
        validation_run_id="test_rehearsal_pipeline",
        report_metadata={
            "pipeline_stage": "pre_gpu_rehearsal",
            "agreement_numbers_are_final": False,
            "judge_b_is_mock_7b": True,
            "mock_numbers_are_resume_metrics": False,
        },
    )

    assert result.report.total_cases == 3
    assert result.report.validation_run_id == "test_rehearsal_pipeline"
    assert result.report.metadata["pipeline_stage"] == "pre_gpu_rehearsal"
    assert result.report.metadata["agreement_numbers_are_final"] is False
    assert result.report.metadata["judge_b_is_mock_7b"] is True
    assert result.report.metadata["mock_numbers_are_resume_metrics"] is False
    assert len(result.report.results) == 3
    assert result.report.results[0].case_id == "RH-001"
