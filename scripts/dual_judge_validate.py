import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.dataset_loader import load_eval_cases
from backend.app.dual_judge_validation import (
    DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    run_dual_judge_validation,
    save_validation_artifacts,
)
from backend.app.eval_run import CandidateAnswer
from backend.app.gpt4o_mini_judge import GPT4oMiniJudge
from backend.app.self_hosted_judge import SelfHostedJudge, SelfHostedJudgeConfig


DEFAULT_DATASET_PATH = Path("datasets/golden/golden_rag_v0.1.jsonl")
DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_LIMIT = 3
MAX_VALIDATION_LIMIT = 120


def load_candidate_answers(
    candidate_answers_path: Path,
    limit: int,
) -> tuple[list[CandidateAnswer], list[dict]]:
    candidates: list[CandidateAnswer] = []
    rows: list[dict] = []

    with candidate_answers_path.open("r", encoding="utf-8") as file:
        for line in file:
            if len(candidates) >= limit:
                break

            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            rows.append(row)
            candidates.append(
                CandidateAnswer(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    generated_answer=row["generated_answer"],
                    trace_id=row.get("trace_id"),
                    status=row.get("status", "completed"),
                )
            )

    return candidates, rows


def load_chunks_by_id(chunks_path: Path) -> dict[str, str]:
    chunks_by_id: dict[str, str] = {}

    with chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            chunks_by_id[row["id"]] = row["text"]

    return chunks_by_id


def build_contexts_by_case_id(
    candidate_rows: list[dict],
    chunks_by_id: dict[str, str],
) -> dict[str, list[str]]:
    contexts_by_case_id: dict[str, list[str]] = {}

    for row in candidate_rows:
        context_lines: list[str] = []
        chunk_ids = row.get("metadata", {}).get("generation_context_chunk_ids", [])

        for chunk_id in chunk_ids:
            chunk_text = chunks_by_id.get(chunk_id)
            if chunk_text is None:
                context_lines.append(f"[{chunk_id}] Chunk text was not found locally.")
            else:
                context_lines.append(f"[{chunk_id}] {chunk_text}")

        contexts_by_case_id[row["case_id"]] = context_lines

    return contexts_by_case_id


def load_human_labels(path: Path | None) -> dict[str, bool] | None:
    if path is None:
        return None

    labels: dict[str, bool] = {}

    with path.open("r", encoding="utf-8") as file:
        for row_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            case_id = row.get("case_id") or row.get("id")

            if "human_passed" in row:
                human_passed = row["human_passed"]
            else:
                human_passed = row.get("passed")

            if case_id is None or human_passed is None:
                raise ValueError(
                    f"Human label row {row_number} must include case_id/id and human_passed/passed."
                )

            labels[str(case_id)] = bool(human_passed)

    return labels


def default_output_paths(candidate_answers_path: Path) -> tuple[Path, Path]:
    stem = candidate_answers_path.name.replace("_candidate_answers.jsonl", "")
    report_path = candidate_answers_path.with_name(
        f"{stem}_dual_judge_validation_report.json"
    )
    review_queue_path = candidate_answers_path.with_name(
        f"{stem}_manual_review_queue.jsonl"
    )
    return report_path, review_queue_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_answers_path")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--self-hosted-url", default=None)
    parser.add_argument("--self-hosted-model", default=None)
    parser.add_argument("--human-labels", default=None)
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    )
    parser.add_argument("--report-output", default=None)
    parser.add_argument("--review-output", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.limit > MAX_VALIDATION_LIMIT:
        raise ValueError(
            "Dual judge validation uses the validation slice. "
            f"Use --limit <= {MAX_VALIDATION_LIMIT}."
        )

    candidate_answers_path = Path(args.candidate_answers_path)
    default_report_path, default_review_path = default_output_paths(candidate_answers_path)
    report_path = Path(args.report_output) if args.report_output else default_report_path
    review_path = Path(args.review_output) if args.review_output else default_review_path

    cases = load_eval_cases(Path(args.dataset))
    candidates, candidate_rows = load_candidate_answers(
        candidate_answers_path=candidate_answers_path,
        limit=args.limit,
    )
    chunks_by_id = load_chunks_by_id(Path(args.chunks))
    contexts_by_case_id = build_contexts_by_case_id(candidate_rows, chunks_by_id)
    human_labels = load_human_labels(Path(args.human_labels) if args.human_labels else None)

    judge_a = GPT4oMiniJudge()
    judge_b_config = SelfHostedJudgeConfig.from_env()

    if args.self_hosted_url:
        judge_b_config.endpoint_url = args.self_hosted_url

    if args.self_hosted_model:
        judge_b_config.model_name = args.self_hosted_model

    judge_b = SelfHostedJudge(config=judge_b_config)

    result = run_dual_judge_validation(
        cases=cases,
        candidates=candidates,
        judge_a=judge_a,
        judge_b=judge_b,
        retrieved_context_by_case_id=contexts_by_case_id,
        human_labels_by_case_id=human_labels,
        score_disagreement_threshold=args.score_threshold,
    )
    save_validation_artifacts(
        result=result,
        report_path=report_path,
        manual_review_queue_path=review_path,
    )

    report = result.report
    print(f"validated_cases={report.total_cases}")
    print(
        "pass_fail_agreement_percentage="
        f"{report.pass_fail_agreement_percentage:.2f}"
    )
    print(f"manual_review_case_count={report.manual_review_case_count}")
    print(f"report_path={report_path}")
    print(f"manual_review_queue_path={review_path}")
    print(report.mock_7b_warning)


if __name__ == "__main__":
    main()
