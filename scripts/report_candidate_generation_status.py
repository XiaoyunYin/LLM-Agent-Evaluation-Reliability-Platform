import argparse
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.append(str(PROJECT_ROOT))

from backend.app.candidate_generation import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    summarize_candidate_generation_outputs,
)


DEFAULT_REPORT_PATH = Path("docs/results/candidate-generation.md")


def render_report(summary: dict) -> str:
    by_provider = summary["actual_candidate_answer_count_by_provider"]
    failed_by_provider = summary["failed_candidate_answer_count_by_provider"]
    failure_examples = summary["failure_examples_by_provider"]
    provider_lines = (
        "\n".join(
            f"- {provider}: {count}"
            for provider, count in sorted(by_provider.items())
        )
        if by_provider
        else "- none"
    )
    failed_provider_lines = (
        "\n".join(
            f"- {provider}: {count} ({failure_examples.get(provider, 'unknown error')})"
            for provider, count in sorted(failed_by_provider.items())
        )
        if failed_by_provider
        else "- none"
    )

    execution_state = (
        "No production candidate-generation artifacts exist yet."
        if summary["actual_candidate_answer_count"] == 0
        else "Production candidate-generation artifacts exist on disk."
    )

    return f"""# Candidate Generation Status

Generated at: {datetime.now(timezone.utc).isoformat()}

## Execution State

{execution_state}

## Actual Counts

- Actual run count with candidate-answer artifacts: {summary["actual_run_count"]}
- Actual completed run count: {summary["actual_completed_run_count"]}
- Actual candidate-answer count: {summary["actual_candidate_answer_count"]}
- Failed candidate-answer rows: {summary["failed_candidate_answer_count"]}

## Candidate Answers By Provider

{provider_lines}

## Failed Rows By Provider

{failed_provider_lines}

## Integrity Notes

- These are candidate answers only, not judged answers.
- Do not claim 60+ runs unless actual completed run count is at least 60.
- Do not claim OpenAI/Anthropic API coverage unless both providers have real completed candidate-answer rows.
- Do not claim 8K+ judged answers from this file.
- Resume works by reading existing `*_candidate_answers.jsonl` files and skipping completed case IDs.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize_candidate_generation_outputs(args.output_dir)
    print(f"actual_run_count={summary['actual_run_count']}")
    print(f"actual_completed_run_count={summary['actual_completed_run_count']}")
    print(f"actual_candidate_answer_count={summary['actual_candidate_answer_count']}")
    for provider, count in sorted(
        summary["actual_candidate_answer_count_by_provider"].items()
    ):
        print(f"actual_candidate_answer_count[{provider}]={count}")

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(render_report(summary), encoding="utf-8")
    print(f"report_path={args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
