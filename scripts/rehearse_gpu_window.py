import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.bulk_judging import (  # noqa: E402
    DEFAULT_CHUNKS_PATH,
    DEFAULT_DATASET_PATH,
    create_bulk_run_id,
    judge_candidate_files,
    render_scale_runs_report,
    render_vllm_benchmark_placeholder,
)
from backend.app.dataset_loader import load_eval_cases  # noqa: E402
from backend.app.dual_judge_validation import (  # noqa: E402
    DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    run_dual_judge_validation,
    save_validation_artifacts,
)
from scripts.bulk_self_hosted_judge_answers import (  # noqa: E402
    build_judge,
    resolve_candidate_paths,
)
from scripts.rehearse_judge_validation import (  # noqa: E402
    build_judge_a,
    build_mock_7b_judge,
    create_validation_slice_artifacts,
    load_candidate_answers,
)


DEFAULT_OUTPUT_DIR = Path("runs/gpu_window_rehearsal")
DEFAULT_SCALE_REPORT_PATH = Path("docs/results/scale-runs.md")
DEFAULT_VLLM_BENCHMARK_REPORT_PATH = Path("docs/results/vllm-benchmark.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-glob",
        action="append",
        default=[
            "runs/candidate_generation/cgen__candidate_answer_run_matrix_v0_1__*_candidate_answers.jsonl"
        ],
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument(
        "--heldout-labels",
        default="datasets/labels/retrieval_heldout_120_v0.2.jsonl",
    )
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--validation-limit", type=int, default=12)
    parser.add_argument("--bulk-limit", type=int, default=24)
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    )
    parser.add_argument("--scale-report-path", default=str(DEFAULT_SCALE_REPORT_PATH))
    parser.add_argument(
        "--vllm-benchmark-report-path",
        default=str(DEFAULT_VLLM_BENCHMARK_REPORT_PATH),
    )
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--self-hosted-url", default="http://in-process-mock-7b/v1/chat/completions")
    parser.add_argument("--self-hosted-model", default="mock-mistral-7b")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.0)
    parser.add_argument("--use-mock-7b", action="store_true", default=True)
    return parser.parse_args()


def run_validation_rehearsal(args: argparse.Namespace, output_dir: Path) -> tuple[Path, Path]:
    eval_cases_path, candidate_answers_path, contexts_by_case_id, run_id = (
        create_validation_slice_artifacts(
            heldout_labels_path=Path(args.heldout_labels),
            chunks_path=Path(args.chunks),
            output_dir=output_dir,
            limit=args.validation_limit,
            run_id=f"gpu_window_validation_mock_{args.validation_limit}",
        )
    )
    cases = load_eval_cases(eval_cases_path)
    candidates = load_candidate_answers(candidate_answers_path)
    judge_a = build_judge_a(use_gpt4o_mini=False)
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
            "pipeline_stage": "gpu_window_local_rehearsal",
            "judge_b_is_mock_7b": True,
            "judge_a_is_rehearsal_standin": True,
            "agreement_numbers_are_final": False,
            "mock_numbers_are_resume_metrics": False,
        },
    )
    report_path = output_dir / f"{run_id}_validation_report.json"
    review_queue_path = output_dir / f"{run_id}_manual_review_queue.jsonl"
    save_validation_artifacts(
        result=result,
        report_path=report_path,
        manual_review_queue_path=review_queue_path,
    )
    return report_path, review_queue_path


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    validation_report_path, manual_review_queue_path = run_validation_rehearsal(
        args=args,
        output_dir=output_dir,
    )

    bulk_run_id = create_bulk_run_id("gpu_window_bulk_mock")
    candidate_paths = resolve_candidate_paths(args.candidate_glob)
    judge = build_judge(args)
    bulk_summary = judge_candidate_files(
        candidate_paths=candidate_paths,
        judge=judge,
        judge_model_name=args.self_hosted_model,
        endpoint_url=args.self_hosted_url,
        bulk_run_id=bulk_run_id,
        dataset_path=Path(args.dataset),
        chunks_path=Path(args.chunks),
        output_path=output_dir / f"{bulk_run_id}_judge_scores.jsonl",
        status_path=output_dir / f"{bulk_run_id}_status.json",
        limit=args.bulk_limit,
        mock_rehearsal=True,
        progress_every=args.progress_every,
    )

    scale_report_path = Path(args.scale_report_path)
    scale_report_path.parent.mkdir(parents=True, exist_ok=True)
    scale_report_path.write_text(
        render_scale_runs_report(bulk_summary),
        encoding="utf-8",
    )

    vllm_report_path = Path(args.vllm_benchmark_report_path)
    vllm_report_path.parent.mkdir(parents=True, exist_ok=True)
    vllm_report_path.write_text(
        render_vllm_benchmark_placeholder(),
        encoding="utf-8",
    )

    print("gpu_window_rehearsal_completed=true")
    print(f"validation_report_path={validation_report_path}")
    print(f"manual_review_queue_path={manual_review_queue_path}")
    print(f"bulk_judge_scores_path={bulk_summary.output_path}")
    print(f"bulk_status_path={bulk_summary.status_path}")
    print(f"scale_report_path={scale_report_path}")
    print(f"vllm_benchmark_report_path={vllm_report_path}")
    print(f"mock_bulk_newly_scored_count={bulk_summary.newly_scored_count}")
    print("mock_7b_numbers_are_not_final=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
