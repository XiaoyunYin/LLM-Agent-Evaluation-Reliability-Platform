import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.candidate_generation import (  # noqa: E402
    build_run_id,
    candidate_status_path,
)
from scripts.summarize_candidate_run_matrix import (  # noqa: E402
    DEFAULT_MATRIX_PATH,
    expand_run_matrix,
    load_matrix,
)


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


def completed_on_disk(run_id: str) -> bool:
    status_path = candidate_status_path(run_id)
    if not status_path.exists():
        return False
    try:
        return '"status": "completed"' in status_path.read_text(encoding="utf-8")
    except OSError:
        return False


def submit_run(api_base_url: str, body: dict) -> dict:
    response = requests.post(
        f"{api_base_url.rstrip('/')}/runs",
        json=body,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--mini-balanced", action="store_true")
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--include-completed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")

    if not args.allow_paid_api:
        print(
            "Refusing to submit real OpenAI/Anthropic generation jobs without "
            "--allow-paid-api.",
            file=sys.stderr,
        )
        return 2

    missing_keys = [
        name
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        if not os.getenv(name)
    ]
    if missing_keys:
        print(
            "Missing required API key environment variables: "
            + ", ".join(missing_keys),
            file=sys.stderr,
        )
        return 2

    matrix = load_matrix(args.matrix)
    rows = expand_run_matrix(matrix)
    if args.mini_balanced:
        rows = build_mini_balanced_rows(rows)
    if args.provider:
        rows = [row for row in rows if row.provider == args.provider]
    if args.limit is not None:
        rows = rows[: args.limit]

    submitted = 0
    skipped_completed = 0

    for row in rows:
        run_id = build_run_id(
            matrix_id=matrix["matrix_id"],
            provider=row.provider,
            model=row.model,
            dataset_version=row.dataset_version,
            retrieval_mode=row.retrieval_mode,
            prompt_version=row.prompt_version,
            repeat_id=row.repeat_id,
        )

        if not args.include_completed and completed_on_disk(run_id):
            skipped_completed += 1
            continue

        submit_run(
            args.api_base_url,
            {
                "run_id": run_id,
                "dataset_version": row.dataset_version,
                "provider_name": row.provider,
                "model_name": row.model,
                "task_family": row.task_family,
                "retrieval_mode": row.retrieval_mode,
                "prompt_version": row.prompt_version,
                "repeat_id": row.repeat_id,
                "matrix_id": matrix["matrix_id"],
                "expected_case_count": row.case_count,
            },
        )
        submitted += 1
        print(f"submitted run_id={run_id}")

    print(f"submitted_run_count={submitted}")
    print(f"skipped_completed_run_count={skipped_completed}")
    return 0


def build_mini_balanced_rows(rows: list) -> list:
    selected = []
    target_retrieval_modes = {
        "bm25_top50_context4",
        "hybrid_rrf_k60_top10_context4",
    }
    target_prompt_versions = {
        "rag_prompt_v1",
        "rag_prompt_v2",
    }

    for row in rows:
        if row.task_family != "rag":
            continue
        if row.repeat_id != "repeat_01":
            continue
        if row.retrieval_mode not in target_retrieval_modes:
            continue
        if row.prompt_version not in target_prompt_versions:
            continue
        selected.append(row)

    providers = {row.provider for row in selected}
    if providers != {"openai", "anthropic"} or len(selected) != 8:
        raise RuntimeError(
            "Mini-balanced selection must produce 8 rows across OpenAI and Anthropic."
        )

    return selected


if __name__ == "__main__":
    raise SystemExit(main())
