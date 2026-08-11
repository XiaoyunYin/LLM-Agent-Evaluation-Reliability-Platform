import argparse
import glob
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.bulk_judging import (  # noqa: E402
    DEFAULT_CHUNKS_PATH,
    DEFAULT_DATASET_PATH,
    DEFAULT_OUTPUT_DIR,
    create_bulk_run_id,
    judge_candidate_files,
    render_scale_runs_report,
)
from backend.app.mock_self_hosted_judge_server import (  # noqa: E402
    create_mock_self_hosted_judge_app,
)
from backend.app.self_hosted_judge import (  # noqa: E402
    DEFAULT_SELF_HOSTED_JUDGE_ENDPOINT,
    DEFAULT_SELF_HOSTED_JUDGE_MODEL,
    SelfHostedJudge,
    SelfHostedJudgeConfig,
)


DEFAULT_SCALE_REPORT_PATH = Path("docs/results/scale-runs.md")


class InProcessMockJudgeSession:
    def __init__(self) -> None:
        self.client = TestClient(create_mock_self_hosted_judge_app())

    def post(self, url: str, **kwargs):
        return self.client.post(
            "/v1/chat/completions",
            json=kwargs.get("json"),
            headers=kwargs.get("headers"),
        )


def resolve_candidate_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []

    for pattern in patterns:
        matched = sorted(Path(match) for match in glob.glob(pattern))
        if matched:
            paths.extend(matched)
            continue

        path = Path(pattern)
        if path.exists():
            paths.append(path)

    unique_paths = sorted(set(paths))
    if not unique_paths:
        raise ValueError(f"No candidate-answer files matched: {patterns}")

    return unique_paths


def build_judge(args: argparse.Namespace) -> SelfHostedJudge:
    config = SelfHostedJudgeConfig(
        endpoint_url=args.self_hosted_url,
        model_name=args.self_hosted_model,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
    )

    if args.use_mock_7b:
        return SelfHostedJudge(
            config=config,
            session=InProcessMockJudgeSession(),
            sleep=lambda seconds: None,
        )

    return SelfHostedJudge(config=config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-glob",
        action="append",
        required=True,
        help="Candidate-answer JSONL path or glob. Repeat to include multiple sets.",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output", default=None)
    parser.add_argument("--status-output", default=None)
    parser.add_argument("--scale-report-path", default=str(DEFAULT_SCALE_REPORT_PATH))
    parser.add_argument("--bulk-run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument(
        "--self-hosted-url",
        default=DEFAULT_SELF_HOSTED_JUDGE_ENDPOINT,
    )
    parser.add_argument(
        "--self-hosted-model",
        default=DEFAULT_SELF_HOSTED_JUDGE_MODEL,
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    parser.add_argument(
        "--use-mock-7b",
        action="store_true",
        help="Use the in-process mock 7B endpoint for local rehearsal.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_paths = resolve_candidate_paths(args.candidate_glob)
    bulk_run_id = args.bulk_run_id or create_bulk_run_id(
        "mock_self_hosted_7b_bulk" if args.use_mock_7b else "self_hosted_7b_bulk"
    )
    output_dir = Path(args.output_dir)
    output_path = (
        Path(args.output)
        if args.output
        else output_dir / f"{bulk_run_id}_judge_scores.jsonl"
    )
    status_path = (
        Path(args.status_output)
        if args.status_output
        else output_dir / f"{bulk_run_id}_status.json"
    )
    judge = build_judge(args)

    summary = judge_candidate_files(
        candidate_paths=candidate_paths,
        judge=judge,
        judge_model_name=args.self_hosted_model,
        endpoint_url=args.self_hosted_url,
        bulk_run_id=bulk_run_id,
        dataset_path=Path(args.dataset),
        chunks_path=Path(args.chunks),
        output_path=output_path,
        status_path=status_path,
        limit=args.limit,
        mock_rehearsal=args.use_mock_7b,
        progress_every=args.progress_every,
    )

    scale_report_path = Path(args.scale_report_path)
    scale_report_path.parent.mkdir(parents=True, exist_ok=True)
    scale_report_path.write_text(render_scale_runs_report(summary), encoding="utf-8")

    print(f"bulk_run_id={summary.bulk_run_id}")
    print(f"candidate_file_count={summary.candidate_file_count}")
    print(f"newly_scored_count={summary.newly_scored_count}")
    print(
        "latest_completed_judge_score_count="
        f"{summary.latest_completed_judge_score_count}"
    )
    print(f"latest_failed_judge_score_count={summary.latest_failed_judge_score_count}")
    print(f"output_path={summary.output_path}")
    print(f"status_path={summary.status_path}")
    print(f"scale_report_path={scale_report_path}")
    if summary.mock_rehearsal:
        print("mock_7b_numbers_are_not_final=true")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
