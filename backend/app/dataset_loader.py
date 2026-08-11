import json
import sys
import argparse
from pathlib import Path

from pydantic import ValidationError

from backend.app.eval_case import EvalCase


def load_eval_cases(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    dataset_path = Path(path)

    with dataset_path.open("r", encoding="utf-8") as file:
        for row_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                row_data = json.loads(line)
                case = EvalCase(**row_data)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON on row {row_number}: {error.errors()}"
                ) from error
            except ValidationError as error:
                first_error = error.errors()[0]
                field = ".".join(str(part) for part in first_error["loc"])
                message = first_error["msg"]

                raise ValueError(
                    f"Invalid eval case on row {row_number}: field '{field}' - {message}"
                ) from error
            cases.append(case)
        

    return cases

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load and print eval cases from a JSONL file.")
    parser.add_argument("path", help="Path to the eval dataset JSONL file.")
    args = parser.parse_args()

    try:
        cases = load_eval_cases(args.path)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(f"Loaded {len(cases)} eval cases")

    for case in cases:
        print(f"{case.id} | {case.task_type.value} | {case.question}")