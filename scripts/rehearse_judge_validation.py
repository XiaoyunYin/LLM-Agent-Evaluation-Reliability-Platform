import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.dataset_loader import load_eval_cases
from backend.app.dual_judge_validation import (
    DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    run_dual_judge_validation,
    save_validation_artifacts,
)
from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, JudgeScore, JudgeType
from backend.app.gpt4o_mini_judge import GPT4oMiniJudge
from backend.app.mock_self_hosted_judge_server import create_mock_self_hosted_judge_app
from backend.app.self_hosted_judge import SelfHostedJudge, SelfHostedJudgeConfig


DEFAULT_HELDOUT_LABELS_PATH = Path("datasets/labels/retrieval_heldout_120_v0.2.jsonl")
DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_OUTPUT_DIR = Path("runs/judge_validation_rehearsal")
DEFAULT_LIMIT = 120


class InProcessMockJudgeSession:
    def __init__(self) -> None:
        self.client = TestClient(create_mock_self_hosted_judge_app())

    def post(self, url: str, **kwargs):
        return self.client.post(
            "/v1/chat/completions",
            json=kwargs.get("json"),
            headers=kwargs.get("headers"),
        )


class DeterministicRehearsalGptJudge:
    judge_name = "rehearsal-gpt4o-mini-standin-v0"
    judge_type = JudgeType.GPT4O_MINI

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        has_expected_marker = "label-derived answer" in candidate.generated_answer.lower()
        has_context = bool(retrieved_context)
        correctness = 0.9 if has_expected_marker else 0.4
        faithfulness = 0.9 if has_context else 0.5
        citation_quality = 0.8 if "[" in candidate.generated_answer else 0.0
        passed = correctness >= 0.8 and faithfulness >= 0.8

        return JudgeScore(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            judge_name=self.judge_name,
            judge_type=self.judge_type,
            correctness=correctness,
            faithfulness=faithfulness,
            citation_quality=citation_quality,
            passed=passed,
            explanation=(
                "Deterministic rehearsal stand-in. This is not a GPT-4o-mini "
                "measurement."
            ),
            trace_id=candidate.trace_id,
        )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    return rows


def load_chunks_by_id(path: Path) -> dict[str, str]:
    chunks_by_id: dict[str, str] = {}

    for row in load_jsonl(path):
        chunks_by_id[row["id"]] = row["text"]

    return chunks_by_id


def validate_heldout_rows(rows: list[dict[str, Any]], limit: int) -> None:
    if len(rows) < limit:
        raise ValueError(f"Need {limit} held-out rows, found {len(rows)}.")

    for row in rows[:limit]:
        if row.get("split") != "heldout":
            raise ValueError(f"{row.get('id')} is not marked split=heldout.")

        if row.get("labels_created_blind_to_judge_outputs") is not True:
            raise ValueError(
                f"{row.get('id')} labels must be blind to judge outputs before rehearsal."
            )

        if not row.get("relevant_chunks"):
            raise ValueError(f"{row.get('id')} must include at least one relevant chunk.")


def build_expected_answer(row: dict[str, Any], chunks_by_id: dict[str, str]) -> str:
    evidence_lines: list[str] = []

    for relevant_chunk in row["relevant_chunks"]:
        chunk_id = relevant_chunk["chunk_id"]
        chunk_text = chunks_by_id.get(chunk_id)
        note = relevant_chunk.get("note", "")

        if chunk_text:
            evidence_lines.append(f"[{chunk_id}] {chunk_text}")
        else:
            evidence_lines.append(f"[{chunk_id}] {note}")

    return "\n".join(evidence_lines)


def build_candidate_answer(row: dict[str, Any]) -> str:
    notes = [
        f"[{chunk['chunk_id']}] {chunk.get('note', '').strip()}"
        for chunk in row["relevant_chunks"]
    ]
    joined_notes = " ".join(notes)

    return (
        f"Label-derived answer for {row['id']}: {joined_notes} "
        "This rehearsal answer is generated from pre-existing held-out relevance "
        "labels, not from a real candidate model."
    )


def create_validation_slice_artifacts(
    heldout_labels_path: Path,
    chunks_path: Path,
    output_dir: Path,
    limit: int = DEFAULT_LIMIT,
    run_id: str | None = None,
) -> tuple[Path, Path, dict[str, list[str]], str]:
    rows = load_jsonl(heldout_labels_path)
    validate_heldout_rows(rows, limit)
    chunks_by_id = load_chunks_by_id(chunks_path)
    selected_rows = rows[:limit]
    run_id = run_id or create_rehearsal_run_id()

    output_dir.mkdir(parents=True, exist_ok=True)
    eval_cases_path = output_dir / f"{run_id}_heldout_120_eval_cases.jsonl"
    candidate_answers_path = output_dir / f"{run_id}_candidate_answers.jsonl"
    contexts_by_case_id: dict[str, list[str]] = {}

    with eval_cases_path.open("w", encoding="utf-8") as cases_file:
        with candidate_answers_path.open("w", encoding="utf-8") as candidates_file:
            for row in selected_rows:
                expected_answer = build_expected_answer(row, chunks_by_id)
                case = EvalCase(
                    id=row["id"],
                    question=row["query"],
                    expected_answer=expected_answer,
                    task_type=TaskType.RAG_QA,
                    metadata={
                        "source": "retrieval_heldout_120_v0.2",
                        "labels_created_blind_to_judge_outputs": row[
                            "labels_created_blind_to_judge_outputs"
                        ],
                        "labeling_protocol_version": row[
                            "labeling_protocol_version"
                        ],
                        "categories": row.get("categories", {}),
                        "relevant_chunk_ids": [
                            chunk["chunk_id"] for chunk in row["relevant_chunks"]
                        ],
                        "rehearsal_only": True,
                    },
                )
                candidate = CandidateAnswer(
                    run_id=run_id,
                    case_id=row["id"],
                    generated_answer=build_candidate_answer(row),
                )
                context_lines = expected_answer.splitlines()
                contexts_by_case_id[row["id"]] = context_lines

                cases_file.write(json.dumps(case.model_dump(mode="json")) + "\n")
                candidates_file.write(
                    json.dumps(
                        {
                            "run_id": candidate.run_id,
                            "case_id": candidate.case_id,
                            "generated_answer": candidate.generated_answer,
                            "status": candidate.status.value,
                            "provider_name": "rehearsal-label-derived-placeholder",
                            "model_name": "not-a-real-candidate-model",
                            "is_mock": True,
                            "metadata": {
                                "source": "retrieval_heldout_120_v0.2",
                                "candidate_answer_is_final": False,
                                "judge_validation_rehearsal_only": True,
                                "generation_context_chunk_ids": [
                                    chunk["chunk_id"]
                                    for chunk in row["relevant_chunks"]
                                ],
                            },
                        }
                    )
                    + "\n"
                )

    return eval_cases_path, candidate_answers_path, contexts_by_case_id, run_id


def load_candidate_answers(path: Path) -> list[CandidateAnswer]:
    candidates: list[CandidateAnswer] = []

    for row in load_jsonl(path):
        candidates.append(
            CandidateAnswer(
                run_id=row["run_id"],
                case_id=row["case_id"],
                generated_answer=row["generated_answer"],
                trace_id=row.get("trace_id"),
                status=row.get("status", "completed"),
            )
        )

    return candidates


def build_judge_a(use_gpt4o_mini: bool):
    if use_gpt4o_mini:
        return GPT4oMiniJudge()

    return DeterministicRehearsalGptJudge()


def build_mock_7b_judge() -> SelfHostedJudge:
    return SelfHostedJudge(
        config=SelfHostedJudgeConfig(
            endpoint_url="http://in-process-mock-7b/v1/chat/completions",
            model_name="mock-mistral-7b",
            timeout_seconds=5.0,
            max_retries=1,
            retry_backoff_seconds=0.0,
        ),
        session=InProcessMockJudgeSession(),
        sleep=lambda seconds: None,
    )


def create_rehearsal_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"judge_validation_rehearsal_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heldout-labels", default=str(DEFAULT_HELDOUT_LABELS_PATH))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--use-gpt4o-mini",
        action="store_true",
        help="Intentionally spend OpenAI API calls for judge A.",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)

    eval_cases_path, candidate_answers_path, contexts_by_case_id, run_id = (
        create_validation_slice_artifacts(
            heldout_labels_path=Path(args.heldout_labels),
            chunks_path=Path(args.chunks),
            output_dir=output_dir,
            limit=args.limit,
        )
    )

    cases = load_eval_cases(eval_cases_path)
    candidates = load_candidate_answers(candidate_answers_path)
    judge_a = build_judge_a(use_gpt4o_mini=args.use_gpt4o_mini)
    judge_b = build_mock_7b_judge()

    result = run_dual_judge_validation(
        cases=cases,
        candidates=candidates,
        judge_a=judge_a,
        judge_b=judge_b,
        retrieved_context_by_case_id=contexts_by_case_id,
        score_disagreement_threshold=args.score_threshold,
        validation_run_id=run_id,
        report_metadata={
            "pipeline_stage": "pre_gpu_rehearsal",
            "validation_slice_size_target": args.limit,
            "validation_slice_source": str(Path(args.heldout_labels)),
            "validation_slice_is_real": True,
            "validation_slice_purpose": "judge agreement rehearsal, not retrieval-label creation",
            "candidate_answer_source": "label-derived rehearsal placeholders",
            "candidate_answers_are_final": False,
            "judge_a_name": judge_a.judge_name,
            "judge_a_is_real_gpt4o_mini": args.use_gpt4o_mini,
            "judge_a_is_rehearsal_standin": not args.use_gpt4o_mini,
            "judge_b_name": judge_b.judge_name,
            "judge_b_is_mock_7b": True,
            "agreement_numbers_are_final": False,
            "mock_numbers_are_reportable": False,
            "non_final_number_fields": [
                "pass_fail_agreement_percentage",
                "score_agreement_percentage",
                "inter_judge_kappa",
                "manual_review_case_count",
            ],
            "final_gpu_window_requirement": (
                "Swap judge B to the real self-hosted 7B vLLM endpoint and score "
                "the same 120 validation answers before reporting final agreement."
            ),
            "labels_created_before_judge_outputs": True,
        },
    )

    report_path = output_dir / f"{run_id}_rehearsal_report.json"
    review_queue_path = output_dir / f"{run_id}_manual_review_queue.jsonl"
    save_validation_artifacts(
        result=result,
        report_path=report_path,
        manual_review_queue_path=review_queue_path,
    )

    print(f"validation_slice_cases={len(cases)}")
    print(f"candidate_answers={len(candidates)}")
    print(f"judge_a={judge_a.judge_name}")
    print(f"judge_b={judge_b.judge_name}")
    print(
        "pass_fail_agreement_percentage="
        f"{result.report.pass_fail_agreement_percentage:.2f} (NON-FINAL)"
    )
    print(
        "manual_review_case_count="
        f"{result.report.manual_review_case_count} (NON-FINAL with mock 7B)"
    )
    print(f"eval_cases_path={eval_cases_path}")
    print(f"candidate_answers_path={candidate_answers_path}")
    print(f"report_path={report_path}")
    print(f"manual_review_queue_path={review_queue_path}")
    print("Mock 7B agreement is not a reportable result.")


if __name__ == "__main__":
    main()
