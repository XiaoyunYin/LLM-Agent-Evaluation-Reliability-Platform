import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backend.app.dataset_loader import load_eval_cases
from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer, JudgeScore, RunStatus


DEFAULT_DATASET_PATH = Path("datasets/golden/golden_rag_v0.1.jsonl")
DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_OUTPUT_DIR = Path("runs/self_hosted_bulk_judging")


class Judge(Protocol):
    judge_name: str

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        ...


class BulkJudgingSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    bulk_run_id: str
    judge_name: str
    judge_model_name: str
    endpoint_url: str
    mock_rehearsal: bool
    candidate_file_count: int
    candidate_answer_rows_seen: int
    eligible_candidate_answer_count: int
    skipped_already_judged_count: int
    newly_scored_count: int
    latest_completed_judge_score_count: int
    latest_failed_judge_score_count: int
    output_path: str
    status_path: str
    started_at: str
    finished_at: str
    status: str


def create_bulk_run_id(prefix: str = "self_hosted_7b_bulk") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    return rows


def load_chunks_by_id(chunks_path: Path) -> dict[str, str]:
    chunks_by_id: dict[str, str] = {}

    for row in load_jsonl(chunks_path):
        chunks_by_id[row["id"]] = row["text"]

    return chunks_by_id


def build_retrieved_context(candidate_row: dict, chunks_by_id: dict[str, str]) -> list[str]:
    context_lines: list[str] = []
    chunk_ids = candidate_row.get("metadata", {}).get("generation_context_chunk_ids", [])

    for chunk_id in chunk_ids:
        chunk_text = chunks_by_id.get(chunk_id)
        if chunk_text is None:
            context_lines.append(f"[{chunk_id}] Chunk text was not found locally.")
        else:
            context_lines.append(f"[{chunk_id}] {chunk_text}")

    return context_lines


def make_score_key(row: dict) -> str:
    return f"{row.get('run_id')}::{row.get('case_id')}::{row.get('judge_name')}"


def load_latest_score_statuses(output_path: Path) -> dict[str, str]:
    latest: dict[str, str] = {}

    if not output_path.exists():
        return latest

    for row in load_jsonl(output_path):
        latest[make_score_key(row)] = str(row.get("status", "completed"))

    return latest


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_status(path: Path, summary: BulkJudgingSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")


def summarize_latest_scores(output_path: Path) -> tuple[int, int]:
    latest = load_latest_score_statuses(output_path)
    completed = sum(1 for status in latest.values() if status == RunStatus.COMPLETED.value)
    failed = sum(1 for status in latest.values() if status == RunStatus.FAILED.value)
    return completed, failed


def default_output_path(bulk_run_id: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{bulk_run_id}_judge_scores.jsonl"


def default_status_path(bulk_run_id: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{bulk_run_id}_status.json"


def judge_candidate_files(
    candidate_paths: list[Path],
    judge: Judge,
    judge_model_name: str,
    endpoint_url: str,
    bulk_run_id: str | None = None,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    output_path: Path | None = None,
    status_path: Path | None = None,
    limit: int | None = None,
    mock_rehearsal: bool = False,
    progress_every: int = 25,
) -> BulkJudgingSummary:
    if not candidate_paths:
        raise ValueError("At least one candidate-answer file is required.")

    bulk_run_id = bulk_run_id or create_bulk_run_id()
    output_path = output_path or default_output_path(bulk_run_id)
    status_path = status_path or default_status_path(bulk_run_id)
    started_at = datetime.now(timezone.utc).isoformat()

    cases = load_eval_cases(dataset_path)
    cases_by_id = {case.id: case for case in cases}
    chunks_by_id = load_chunks_by_id(chunks_path)
    latest_statuses = load_latest_score_statuses(output_path)
    completed_score_keys = {
        key
        for key, status in latest_statuses.items()
        if status == RunStatus.COMPLETED.value
    }

    rows_seen = 0
    eligible = 0
    skipped = 0
    newly_scored = 0

    for candidate_path in candidate_paths:
        for row in load_jsonl(candidate_path):
            rows_seen += 1

            if limit is not None and newly_scored >= limit:
                break

            if row.get("status", "completed") != RunStatus.COMPLETED.value:
                continue

            eligible += 1
            score_key = (
                f"{row.get('run_id')}::{row.get('case_id')}::{judge.judge_name}"
            )

            if score_key in completed_score_keys:
                skipped += 1
                continue

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
                    f"{candidate_path} references unknown case_id={candidate.case_id}"
                )

            score = judge.judge_candidate_answer(
                case=case,
                candidate=candidate,
                retrieved_context=build_retrieved_context(row, chunks_by_id),
            )
            score_row = score.model_dump(mode="json")
            score_row.update(
                {
                    "bulk_run_id": bulk_run_id,
                    "judge_model_name": judge_model_name,
                    "judge_endpoint_url": endpoint_url,
                    "mock_rehearsal": mock_rehearsal,
                    "judged_at": datetime.now(timezone.utc).isoformat(),
                    "candidate_provider_name": row.get("provider_name"),
                    "candidate_model_name": row.get("model_name"),
                    "candidate_matrix_id": row.get("matrix_id"),
                    "candidate_retrieval_mode": row.get("retrieval_mode"),
                    "candidate_prompt_version": row.get("prompt_version"),
                }
            )
            append_jsonl(output_path, score_row)
            newly_scored += 1

            if score.status == RunStatus.COMPLETED:
                completed_score_keys.add(score_key)

            summary = build_summary(
                bulk_run_id=bulk_run_id,
                judge=judge,
                judge_model_name=judge_model_name,
                endpoint_url=endpoint_url,
                mock_rehearsal=mock_rehearsal,
                candidate_file_count=len(candidate_paths),
                rows_seen=rows_seen,
                eligible=eligible,
                skipped=skipped,
                newly_scored=newly_scored,
                output_path=output_path,
                status_path=status_path,
                started_at=started_at,
            )
            write_status(status_path, summary)

            if progress_every > 0 and newly_scored % progress_every == 0:
                print(
                    "bulk_judging_progress "
                    f"newly_scored={newly_scored} skipped={skipped} "
                    f"rows_seen={rows_seen}"
                )

        if limit is not None and newly_scored >= limit:
            break

    summary = build_summary(
        bulk_run_id=bulk_run_id,
        judge=judge,
        judge_model_name=judge_model_name,
        endpoint_url=endpoint_url,
        mock_rehearsal=mock_rehearsal,
        candidate_file_count=len(candidate_paths),
        rows_seen=rows_seen,
        eligible=eligible,
        skipped=skipped,
        newly_scored=newly_scored,
        output_path=output_path,
        status_path=status_path,
        started_at=started_at,
    )
    write_status(status_path, summary)
    return summary


def build_summary(
    bulk_run_id: str,
    judge: Judge,
    judge_model_name: str,
    endpoint_url: str,
    mock_rehearsal: bool,
    candidate_file_count: int,
    rows_seen: int,
    eligible: int,
    skipped: int,
    newly_scored: int,
    output_path: Path,
    status_path: Path,
    started_at: str,
) -> BulkJudgingSummary:
    completed, failed = summarize_latest_scores(output_path)
    status = "completed" if failed == 0 else "completed_with_failures"

    return BulkJudgingSummary(
        bulk_run_id=bulk_run_id,
        judge_name=judge.judge_name,
        judge_model_name=judge_model_name,
        endpoint_url=endpoint_url,
        mock_rehearsal=mock_rehearsal,
        candidate_file_count=candidate_file_count,
        candidate_answer_rows_seen=rows_seen,
        eligible_candidate_answer_count=eligible,
        skipped_already_judged_count=skipped,
        newly_scored_count=newly_scored,
        latest_completed_judge_score_count=completed,
        latest_failed_judge_score_count=failed,
        output_path=str(output_path),
        status_path=str(status_path),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
        status=status,
    )


def render_scale_runs_report(summary: BulkJudgingSummary) -> str:
    finality = "NON-FINAL MOCK REHEARSAL" if summary.mock_rehearsal else "REAL GPU RUN"
    sustained_tok_s = "not measured by this bulk script"

    return f"""# Scale Runs

Generated at: {datetime.now(timezone.utc).isoformat()}

## Status

- Run type: {finality}
- Bulk run ID: `{summary.bulk_run_id}`
- Judge: `{summary.judge_name}`
- Judge model: `{summary.judge_model_name}`
- Endpoint: `{summary.endpoint_url}`

## Judged-Answer Counts

- Candidate files scanned: {summary.candidate_file_count}
- Candidate rows seen during this invocation: {summary.candidate_answer_rows_seen}
- Eligible completed candidate answers seen: {summary.eligible_candidate_answer_count}
- Skipped already judged answers: {summary.skipped_already_judged_count}
- Newly scored answers in this invocation: {summary.newly_scored_count}
- Latest completed judge-score count in output: {summary.latest_completed_judge_score_count}
- Latest failed judge-score count in output: {summary.latest_failed_judge_score_count}

## Output Files

- Judge scores: `{summary.output_path}`
- Status checkpoint: `{summary.status_path}`

## Measurement Boundary

- Bulk judged-answer count and vLLM throughput benchmark are separate measurements.
- Bulk sustained output tok/s: {sustained_tok_s}
- Use semicolon wording unless the bulk run is explicitly instrumented to report sustained output tok/s over the whole run.
"""


def render_vllm_benchmark_placeholder() -> str:
    return f"""# vLLM Benchmark

Generated at: {datetime.now(timezone.utc).isoformat()}

## Status

- Benchmark status: not measured yet
- Model target: `Mistral-7B-Instruct-v0.3-AWQ`
- Quantization: `AWQ`
- Hardware target: `AWS g4dn.xlarge`
- GPU target: `T4 16 GB`
- Benchmark concurrency target: `16`

## Result

- Output tokens/sec at concurrency 16: not measured
- Benchmark JSON artifact: not written yet

## Measurement Boundary

- This file is reserved for the dedicated vLLM throughput benchmark.
- Do not copy mock rehearsal counts into this file as throughput.
- Do not phrase throughput as applying across the full bulk-judging run unless the bulk script also records sustained output tok/s over that whole run.
"""
