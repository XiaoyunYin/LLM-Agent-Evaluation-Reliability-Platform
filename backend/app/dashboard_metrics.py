import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


MetricStatus = Literal["measured", "non_final", "not_measured"]
MetricUnit = Literal["count", "percentage", "ratio"]


class DashboardMetric(BaseModel):
    key: str
    label: str
    value: float | int | None
    unit: MetricUnit
    status: MetricStatus
    source: str | None = None
    measured_at: str | None = None
    command: str | None = None
    note: str


class MetricsSummaryResponse(BaseModel):
    metrics: list[DashboardMetric]


METRIC_KEYS = [
    "recall_at_10",
    "ndcg_at_10",
    "judge_agreement_percentage",
    "disagreement_percentage",
    "judged_answer_count",
    "eval_run_count",
    "trace_count",
]


def build_metrics_summary(project_root: Path | None = None) -> MetricsSummaryResponse:
    root = project_root or Path.cwd()
    runs_dir = root / "runs"

    latest_report = latest_rehearsal_report(runs_dir)
    retrieval_summary = latest_retrieval_summary(runs_dir)

    metrics_by_key = {
        "recall_at_10": retrieval_metric(
            key="recall_at_10",
            label="recall@10",
            field_names=["hybrid_mean_recall_at_10", "mean_recall_at_10"],
            summary=retrieval_summary,
            command="python scripts/benchmark_hybrid_retrieval.py",
            note="Run and save a machine-readable retrieval benchmark before showing this as measured.",
        ),
        "ndcg_at_10": retrieval_metric(
            key="ndcg_at_10",
            label="nDCG@10",
            field_names=["hybrid_mean_ndcg_at_10", "mean_ndcg_at_10"],
            summary=retrieval_summary,
            command="python scripts/benchmark_hybrid_retrieval.py",
            note="Run and save a machine-readable retrieval benchmark before showing this as measured.",
        ),
        "judge_agreement_percentage": judge_agreement_metric(latest_report),
        "disagreement_percentage": judge_disagreement_metric(latest_report),
        "judged_answer_count": judged_answer_count_metric(runs_dir),
        "eval_run_count": eval_run_count_metric(runs_dir),
        "trace_count": trace_count_metric(runs_dir),
    }

    return MetricsSummaryResponse(
        metrics=[metrics_by_key[key] for key in METRIC_KEYS],
    )


def latest_rehearsal_report(runs_dir: Path) -> tuple[Path, dict] | None:
    reports = list_artifact_files(runs_dir, "*_rehearsal_report.json")
    reports.extend(list_artifact_files(runs_dir, "validation_report.json"))

    loaded = []
    for path in reports:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "pass_fail_agreement_percentage" in data:
            loaded.append((path, data))

    if not loaded:
        return None

    return max(loaded, key=lambda item: item[0].stat().st_mtime)


def latest_retrieval_summary(runs_dir: Path) -> tuple[Path, dict] | None:
    candidates = []
    for pattern in (
        "*retrieval*summary*.json",
        "*retrieval*benchmark*.json",
        "*retrieval*metrics*.json",
    ):
        candidates.extend(list_artifact_files(runs_dir, pattern))

    loaded = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if any(key.endswith("recall_at_10") or key.endswith("ndcg_at_10") for key in data):
            loaded.append((path, data))

    if not loaded:
        return None

    return max(loaded, key=lambda item: item[0].stat().st_mtime)


def retrieval_metric(
    key: str,
    label: str,
    field_names: list[str],
    summary: tuple[Path, dict] | None,
    command: str,
    note: str,
) -> DashboardMetric:
    if summary is None:
        return DashboardMetric(
            key=key,
            label=label,
            value=None,
            unit="ratio",
            status="not_measured",
            command=command,
            note=note,
        )

    path, data = summary
    for field_name in field_names:
        if isinstance(data.get(field_name), int | float):
            return DashboardMetric(
                key=key,
                label=label,
                value=data[field_name],
                unit="ratio",
                status="measured",
                source=relative_source(path),
                measured_at=data.get("created_at") or data.get("measured_at"),
                command=data.get("exact_command") or command,
                note="Loaded from a saved retrieval benchmark artifact.",
            )

    return DashboardMetric(
        key=key,
        label=label,
        value=None,
        unit="ratio",
        status="not_measured",
        source=relative_source(path),
        command=command,
        note=f"The latest retrieval artifact does not contain {label}.",
    )


def judge_agreement_metric(report: tuple[Path, dict] | None) -> DashboardMetric:
    if report is None:
        return DashboardMetric(
            key="judge_agreement_percentage",
            label="Judge agreement",
            value=None,
            unit="percentage",
            status="not_measured",
            command="python scripts/rehearse_judge_validation.py --limit 120",
            note="No saved dual-judge validation report was found.",
        )

    path, data = report
    return DashboardMetric(
        key="judge_agreement_percentage",
        label="Judge agreement",
        value=data.get("pass_fail_agreement_percentage"),
        unit="percentage",
        status=judge_report_status(data),
        source=relative_source(path),
        measured_at=data.get("created_at"),
        command="python scripts/rehearse_judge_validation.py --limit 120",
        note=judge_report_note(data),
    )


def judge_disagreement_metric(report: tuple[Path, dict] | None) -> DashboardMetric:
    if report is None:
        return DashboardMetric(
            key="disagreement_percentage",
            label="Disagreement",
            value=None,
            unit="percentage",
            status="not_measured",
            command="python scripts/rehearse_judge_validation.py --limit 120",
            note="No saved dual-judge validation report was found.",
        )

    path, data = report
    total = data.get("total_cases")
    disagreements = data.get("pass_fail_disagreements")
    value = None
    if isinstance(total, int) and total > 0 and isinstance(disagreements, int):
        value = (disagreements / total) * 100.0

    return DashboardMetric(
        key="disagreement_percentage",
        label="Disagreement",
        value=value,
        unit="percentage",
        status=judge_report_status(data),
        source=relative_source(path),
        measured_at=data.get("created_at"),
        command="python scripts/rehearse_judge_validation.py --limit 120",
        note=judge_report_note(data),
    )


def judge_report_status(data: dict) -> MetricStatus:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if metadata.get("agreement_numbers_are_final") is False:
        return "non_final"
    if metadata.get("judge_b_is_mock_7b") is True:
        return "non_final"
    if metadata.get("judge_a_is_rehearsal_standin") is True:
        return "non_final"
    return "measured"


def judge_report_note(data: dict) -> str:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if metadata.get("agreement_numbers_are_final") is False:
        return (
            "Mock rehearsal only. This tests the harness and review routing, "
            "not final judge validation."
        )
    return "Measured from a saved dual-judge validation report."


def judged_answer_count_metric(runs_dir: Path) -> DashboardMetric:
    files = list_artifact_files(runs_dir, "*_judge_scores.jsonl")
    count = sum(count_jsonl_rows(path) for path in files)

    if not files:
        return DashboardMetric(
            key="judged_answer_count",
            label="Judged answers",
            value=None,
            unit="count",
            status="not_measured",
            note="No persisted judge-score JSONL files were found.",
        )

    return DashboardMetric(
        key="judged_answer_count",
        label="Judged answers",
        value=count,
        unit="count",
        status="measured",
        source="runs/**/*_judge_scores.jsonl",
        note=(
            "Counted persisted judge-score rows. This is not the self-hosted "
            "bulk judge count unless those rows came from that run."
        ),
    )


def eval_run_count_metric(runs_dir: Path) -> DashboardMetric:
    run_ids = set()
    for path in list_artifact_files(runs_dir, "*_candidate_answers.jsonl"):
        first_row = first_jsonl_object(path)
        if isinstance(first_row, dict) and isinstance(first_row.get("run_id"), str):
            run_ids.add(first_row["run_id"])
        else:
            run_ids.add(path.stem.replace("_candidate_answers", ""))

    return DashboardMetric(
        key="eval_run_count",
        label="Eval runs",
        value=len(run_ids),
        unit="count",
        status="measured",
        source="runs/**/*_candidate_answers.jsonl",
        note="Counted unique run IDs from saved candidate-answer artifacts.",
    )


def trace_count_metric(runs_dir: Path) -> DashboardMetric:
    summary = latest_trace_summary(runs_dir)
    if summary is None:
        return DashboardMetric(
            key="trace_count",
            label="Trace count",
            value=None,
            unit="count",
            status="not_measured",
            command="python scripts/count_trace_documents.py",
            note=(
                "No saved Elasticsearch trace-count artifact was found. Count "
                "unique traces after Elasticsearch is running."
            ),
        )

    path, data = summary
    return DashboardMetric(
        key="trace_count",
        label="Trace count",
        value=data.get("unique_trace_count"),
        unit="count",
        status="measured",
        source=relative_source(path),
        measured_at=data.get("created_at") or data.get("measured_at"),
        command=data.get("exact_command") or "python scripts/count_trace_documents.py",
        note="Unique trace count, not span document count.",
    )


def latest_trace_summary(runs_dir: Path) -> tuple[Path, dict] | None:
    candidates = []
    for pattern in ("*trace*summary*.json", "*trace*count*.json"):
        candidates.extend(list_artifact_files(runs_dir, pattern))

    loaded = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data.get("unique_trace_count"), int):
            loaded.append((path, data))

    if not loaded:
        return None

    return max(loaded, key=lambda item: item[0].stat().st_mtime)


def load_review_cases_from_artifacts(runs_dir: Path) -> list[dict]:
    cases: list[dict] = []

    for path in list_artifact_files(runs_dir, "*manual_review_queue.jsonl"):
        for row in iter_jsonl_objects(path):
            if not isinstance(row, dict):
                continue
            run_id = row.get("run_id")
            case_id = row.get("case_id")
            if not isinstance(run_id, str) or not isinstance(case_id, str):
                continue
            row = dict(row)
            row["id"] = row.get("id") or f"{run_id}:{case_id}"
            cases.append(row)

    cases.sort(key=lambda row: (row.get("run_id", ""), row.get("case_id", "")))
    return cases


def list_artifact_files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []

    matches: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root, onerror=lambda _: None):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith("pytest")
            and not name.startswith("test_")
            and name != "__pycache__"
        ]
        directory_path = Path(directory)
        for filename in filenames:
            path = directory_path / filename
            if path.match(pattern):
                matches.append(path)

    return matches


def count_jsonl_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as file:
            return sum(1 for line in file if line.strip())
    except OSError:
        return 0


def first_jsonl_object(path: Path) -> dict | None:
    for row in iter_jsonl_objects(path):
        return row if isinstance(row, dict) else None
    return None


def iter_jsonl_objects(path: Path):
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def relative_source(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
