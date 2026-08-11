import json
from uuid import uuid4
from pathlib import Path

from backend.app.bulk_judging import judge_candidate_files
from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, JudgeScore, JudgeType


class FakeJudge:
    judge_name = "self-hosted-7b-bulk-v0"

    def __init__(self) -> None:
        self.call_count = 0

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        self.call_count += 1
        return JudgeScore(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            judge_name=self.judge_name,
            judge_type=JudgeType.SELF_HOSTED_7B,
            correctness=1.0,
            faithfulness=1.0 if retrieved_context else 0.5,
            citation_quality=1.0 if retrieved_context else 0.0,
            passed=True,
            explanation="Fake bulk judge score.",
        )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


def make_test_dir() -> Path:
    path = Path("runs/test_bulk_judging") / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_bulk_judging_skips_already_completed_scores():
    tmp_path = make_test_dir()
    dataset_path = tmp_path / "cases.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    candidate_path = tmp_path / "candidate_answers.jsonl"
    output_path = tmp_path / "judge_scores.jsonl"
    status_path = tmp_path / "status.json"

    write_jsonl(
        dataset_path,
        [
            {
                "id": "case_001",
                "question": "What is A?",
                "expected_answer": "A",
                "task_type": "direct_qa",
                "metadata": {},
            },
            {
                "id": "case_002",
                "question": "What is B?",
                "expected_answer": "B",
                "task_type": "direct_qa",
                "metadata": {},
            },
        ],
    )
    write_jsonl(chunks_path, [{"id": "chunk_001", "text": "supporting text"}])
    write_jsonl(
        candidate_path,
        [
            {
                "run_id": "run_001",
                "case_id": "case_001",
                "generated_answer": "A",
                "status": "completed",
                "metadata": {"generation_context_chunk_ids": ["chunk_001"]},
            },
            {
                "run_id": "run_001",
                "case_id": "case_002",
                "generated_answer": "B",
                "status": "completed",
                "metadata": {"generation_context_chunk_ids": ["chunk_001"]},
            },
        ],
    )
    write_jsonl(
        output_path,
        [
            {
                "run_id": "run_001",
                "case_id": "case_001",
                "judge_name": "self-hosted-7b-bulk-v0",
                "judge_type": "self_hosted_7b",
                "correctness": 1.0,
                "faithfulness": 1.0,
                "citation_quality": 1.0,
                "passed": True,
                "explanation": "Already done.",
                "status": "completed",
            }
        ],
    )

    judge = FakeJudge()
    summary = judge_candidate_files(
        candidate_paths=[candidate_path],
        judge=judge,
        judge_model_name="mock-mistral-7b",
        endpoint_url="http://mock/v1/chat/completions",
        bulk_run_id="bulk_test",
        dataset_path=dataset_path,
        chunks_path=chunks_path,
        output_path=output_path,
        status_path=status_path,
        mock_rehearsal=True,
    )

    assert judge.call_count == 1
    assert summary.skipped_already_judged_count == 1
    assert summary.newly_scored_count == 1
    assert summary.latest_completed_judge_score_count == 2
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "completed"


def test_bulk_judging_limit_keeps_rehearsal_small():
    tmp_path = make_test_dir()
    dataset_path = tmp_path / "cases.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    candidate_path = tmp_path / "candidate_answers.jsonl"

    write_jsonl(
        dataset_path,
        [
            {
                "id": f"case_{index:03d}",
                "question": "Question?",
                "expected_answer": "Answer",
                "task_type": TaskType.DIRECT_QA.value,
                "metadata": {},
            }
            for index in range(3)
        ],
    )
    write_jsonl(chunks_path, [{"id": "chunk_001", "text": "supporting text"}])
    write_jsonl(
        candidate_path,
        [
            {
                "run_id": "run_001",
                "case_id": f"case_{index:03d}",
                "generated_answer": "Answer",
                "status": "completed",
                "metadata": {"generation_context_chunk_ids": ["chunk_001"]},
            }
            for index in range(3)
        ],
    )

    judge = FakeJudge()
    summary = judge_candidate_files(
        candidate_paths=[candidate_path],
        judge=judge,
        judge_model_name="mock-mistral-7b",
        endpoint_url="http://mock/v1/chat/completions",
        bulk_run_id="bulk_test_limit",
        dataset_path=dataset_path,
        chunks_path=chunks_path,
        output_path=tmp_path / "scores.jsonl",
        status_path=tmp_path / "status.json",
        limit=2,
        mock_rehearsal=True,
    )

    assert judge.call_count == 2
    assert summary.newly_scored_count == 2
    assert summary.latest_completed_judge_score_count == 2
