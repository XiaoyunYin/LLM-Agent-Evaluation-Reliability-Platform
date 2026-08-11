import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.dataset_loader import load_eval_cases
from backend.app.eval_run import CandidateAnswer
from backend.app.rule_based_judge import judge_candidate_answer


DEFAULT_DATASET_PATH = Path("datasets/golden/golden_rag_v0.1.jsonl")


def judge_candidate_file(
    candidate_answers_path: Path,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    output_path: Path | None = None,
) -> Path:
    cases = load_eval_cases(dataset_path)
    cases_by_id = {case.id: case for case in cases}

    if output_path is None:
        output_path = candidate_answers_path.with_name(
            candidate_answers_path.name.replace(
                "_candidate_answers.jsonl",
                "_rule_based_judge_scores.jsonl",
            )
        )

    saved_count = 0

    with candidate_answers_path.open("r", encoding="utf-8") as input_file:
        with output_path.open("w", encoding="utf-8") as output_file:
            for row_number, line in enumerate(input_file, start=1):
                line = line.strip()

                if not line:
                    continue

                row = json.loads(line)
                candidate = CandidateAnswer(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    generated_answer=row["generated_answer"],
                    trace_id=row.get("trace_id"),
                    status=row.get("status", "completed"),
                )

                case = cases_by_id.get(candidate.case_id)
                if case is None:
                    raise ValueError(
                        f"Candidate row {row_number} references unknown case_id: {candidate.case_id}"
                    )

                score = judge_candidate_answer(case=case, candidate=candidate)
                output_file.write(json.dumps(score.model_dump(mode="json")) + "\n")
                saved_count += 1

    print(f"judge_scores_saved={saved_count}")
    print(f"output_path={output_path}")

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_answers_path")
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET_PATH),
        help="Path to the golden eval dataset JSONL file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSONL path for judge scores.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_path = Path(args.output) if args.output else None

    judge_candidate_file(
        candidate_answers_path=Path(args.candidate_answers_path),
        dataset_path=Path(args.dataset),
        output_path=output_path,
    )


if __name__ == "__main__":
    main()