import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.dataset_loader import load_eval_cases
from backend.app.eval_run import CandidateAnswer
from backend.app.gpt4o_mini_judge import GPT4oMiniJudge


DEFAULT_DATASET_PATH = Path("datasets/golden/golden_rag_v0.1.jsonl")
DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_LIMIT = 3
MAX_GPT4O_MINI_VALIDATION_LIMIT = 120


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


def build_retrieved_context(
    candidate_row: dict,
    chunks_by_id: dict[str, str],
) -> list[str]:
    chunk_ids = candidate_row.get("metadata", {}).get("generation_context_chunk_ids", [])

    context_lines: list[str] = []

    for chunk_id in chunk_ids:
        chunk_text = chunks_by_id.get(chunk_id)

        if chunk_text is None:
            context_lines.append(f"[{chunk_id}] Chunk text was not found locally.")
        else:
            context_lines.append(f"[{chunk_id}] {chunk_text}")

    return context_lines


def judge_candidate_file(
    candidate_answers_path: Path,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    limit: int = DEFAULT_LIMIT,
    output_path: Path | None = None,
) -> Path:
    if limit > MAX_GPT4O_MINI_VALIDATION_LIMIT:
        raise ValueError(
            "GPT-4o-mini is only for the validation slice. "
            f"Use a limit <= {MAX_GPT4O_MINI_VALIDATION_LIMIT}."
        )

    cases = load_eval_cases(dataset_path)
    cases_by_id = {case.id: case for case in cases}
    chunks_by_id = load_chunks_by_id(chunks_path)
    judge = GPT4oMiniJudge()

    if output_path is None:
        output_path = candidate_answers_path.with_name(
            candidate_answers_path.name.replace(
                "_candidate_answers.jsonl",
                "_gpt4o_mini_judge_scores.jsonl",
            )
        )

    saved_count = 0

    with candidate_answers_path.open("r", encoding="utf-8") as input_file:
        with output_path.open("w", encoding="utf-8") as output_file:
            for row_number, line in enumerate(input_file, start=1):
                if saved_count >= limit:
                    break

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

                retrieved_context = build_retrieved_context(
                    candidate_row=row,
                    chunks_by_id=chunks_by_id,
                )

                score = judge.judge_candidate_answer(
                    case=case,
                    candidate=candidate,
                    retrieved_context=retrieved_context,
                )

                output_file.write(json.dumps(score.model_dump(mode="json")) + "\n")
                saved_count += 1

    print(f"gpt4o_mini_judge_scores_saved={saved_count}")
    print(f"output_path={output_path}")

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_answers_path")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_path = Path(args.output) if args.output else None

    judge_candidate_file(
        candidate_answers_path=Path(args.candidate_answers_path),
        dataset_path=Path(args.dataset),
        chunks_path=Path(args.chunks),
        limit=args.limit,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()