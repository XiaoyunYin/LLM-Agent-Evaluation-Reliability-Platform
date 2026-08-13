"""Check the P0 completion criteria against real artifacts (plan, Step 18).

The plan's Step 18 is a checklist of 24 boxes. A checklist ticked by hand is an
assertion; this script turns each box into a check against a file on disk, a
persisted run, or a live probe, and prints the evidence next to the verdict.

Anything it cannot verify is reported as UNVERIFIED, never as passing.

Usage:
    python scripts/verify_p0_completion.py --run-id spider_full__p0_v1
    python scripts/verify_p0_completion.py --run-id ... --check-traces
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    TrajectoryStore,
    jsonl_exists,
    open_jsonl,
)


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | UNVERIFIED
    evidence: str


class P0Verifier:
    def __init__(self, run_id: str, root: Path, trace_report: dict | None) -> None:
        self.run_id = run_id
        self.store = TrajectoryStore(run_id, root)
        self.trace_report = trace_report

        self.config: dict[str, Any] = (
            json.loads(self.store.config_path.read_text(encoding="utf-8"))
            if self.store.config_path.exists()
            else {}
        )
        self.episodes = list(self.store.iter_episodes())
        self.steps = list(self.store.iter_steps())
        self.qa = self._load_json(
            REPO_ROOT / "runs" / "spider_verifier_qa" / "verifier_qa_dev.json"
        )
        self.metrics = self._load_json(self.store.run_dir / "p0_metrics.json")

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    # -- individual checks -------------------------------------------------

    def spider_runs_through_the_runner(self) -> Check:
        if not self.episodes:
            return Check("Spider dev tasks run through the evaluation runner", "FAIL",
                         "no episodes persisted")
        splits = {self.config.get("split")}
        return Check(
            "Spider dev tasks run through the evaluation runner",
            "PASS" if splits == {"dev"} and self.episodes else "FAIL",
            f"{len(self.episodes):,} episodes on split={self.config.get('split')}",
        )

    def versions_are_pinned(self) -> Check:
        required = ("archive_sha256", "dev_json_sha256", "dataset_version")
        missing = [key for key in required if not self.config.get(key)]
        return Check(
            "Dataset and benchmark versions are pinned",
            "PASS" if not missing else "FAIL",
            f"dataset_version={self.config.get('dataset_version')} "
            f"archive_sha256={str(self.config.get('archive_sha256'))[:12]}"
            + (f" missing={missing}" if missing else ""),
        )

    def exclusion_list_is_frozen(self) -> Check:
        path = REPO_ROOT / "docs" / "LOCKED_INPUTS.md"
        if not path.exists():
            return Check("A frozen verifier exclusion list exists", "FAIL", "no LOCKED_INPUTS.md")
        excluded = self.config.get("excluded_task_ids", [])
        return Check(
            "A frozen verifier exclusion list exists",
            "PASS",
            f"docs/LOCKED_INPUTS.md, {len(excluded)} excluded task(s)",
        )

    def episodes_are_isolated(self) -> Check:
        """Probed live rather than inferred: copy, confirm separate paths, clean up."""
        from backend.app.spider.environment import EpisodeDatabase

        source = REPO_ROOT / "datasets" / "spider" / "database" / "concert_singer" / "concert_singer.sqlite"
        if not source.exists():
            return Check("Every episode uses an isolated SQLite database", "UNVERIFIED",
                         "Spider database not present")

        with EpisodeDatabase(source, "p0_verify_a") as first:
            with EpisodeDatabase(source, "p0_verify_b") as second:
                distinct = first.episode_path != second.episode_path != source
                one_per_dir = list(first.episode_dir.glob("*.sqlite")) == [first.episode_path]
                paths = (first.episode_dir, second.episode_dir)
        removed = not any(path.exists() for path in paths)

        ok = distinct and one_per_dir and removed
        return Check(
            "Every episode uses an isolated SQLite database",
            "PASS" if ok else "FAIL",
            f"separate copies={distinct}, one db per episode dir={one_per_dir}, "
            f"cleaned up={removed}",
        )

    def sql_access_is_read_only(self) -> Check:
        from backend.app.spider.environment import EpisodeDatabase, ReadOnlyViolation

        source = REPO_ROOT / "datasets" / "spider" / "database" / "concert_singer" / "concert_singer.sqlite"
        if not source.exists():
            return Check("Agent SQL access is read-only", "UNVERIFIED", "Spider database not present")

        guard_blocked = 0
        sqlite_blocked = 0
        statements = [
            "INSERT INTO singer VALUES (1)",
            "UPDATE singer SET Name='x'",
            "DELETE FROM singer",
            "DROP TABLE singer",
            "ALTER TABLE singer ADD c INT",
        ]
        with EpisodeDatabase(source, "p0_verify_ro") as database:
            for statement in statements:
                try:
                    database.execute(statement)
                except ReadOnlyViolation:
                    guard_blocked += 1
                except sqlite3.Error:
                    sqlite_blocked += 1
            # Second layer, with the guard bypassed entirely.
            connection = database.connect()
            for statement in statements:
                try:
                    connection.execute(statement)
                except sqlite3.Error:
                    sqlite_blocked += 1

        ok = guard_blocked == len(statements) and sqlite_blocked == len(statements)
        return Check(
            "Agent SQL access is read-only",
            "PASS" if ok else "FAIL",
            f"guard blocked {guard_blocked}/{len(statements)}, "
            f"SQLite mode=ro blocked {sqlite_blocked}/{len(statements)} with guard bypassed",
        )

    def inspect_schema_works(self) -> Check:
        used = sum(
            1 for step in self.steps
            if step.get("tool_name") == "inspect_schema" and step.get("tool_success")
        )
        return Check(
            "inspect_schema works",
            "PASS" if used else "FAIL",
            f"{used:,} successful inspect_schema calls in the run",
        )

    def execute_sql_works(self) -> Check:
        used = sum(
            1 for step in self.steps
            if step.get("tool_name") == "execute_sql" and step.get("tool_success")
        )
        return Check(
            "execute_sql works",
            "PASS" if used else "FAIL",
            f"{used:,} successful execute_sql calls in the run",
        )

    def model_visible_rows_are_capped(self) -> Check:
        from backend.app.spider.tools import MAX_VISIBLE_ROWS

        payloads_path = self.store.payloads_path
        if not jsonl_exists(payloads_path):
            return Check("SQL results shown to the model are capped", "UNVERIFIED", "no payloads")

        largest_full = 0
        largest_visible = 0
        over_cap = 0
        checked_visible = 0

        with open_jsonl(payloads_path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = record.get("kind")

                if kind == "tool_result":
                    rows = (record.get("data") or {}).get("rows")
                    if isinstance(rows, list):
                        largest_full = max(largest_full, len(rows))

                elif kind == "model_input":
                    # What the model actually received. The cap is a claim about
                    # this, not about the persisted copy, so it must be measured
                    # on the conversation the model was sent.
                    for message in record.get("data") or []:
                        if not isinstance(message, dict) or message.get("role") != "tool":
                            continue
                        try:
                            payload = json.loads(message.get("content") or "{}")
                        except (json.JSONDecodeError, TypeError):
                            continue
                        rows = payload.get("rows")
                        if not isinstance(rows, list):
                            continue
                        checked_visible += 1
                        largest_visible = max(largest_visible, len(rows))
                        if len(rows) > MAX_VISIBLE_ROWS:
                            over_cap += 1

        ok = checked_visible > 0 and over_cap == 0 and largest_full > largest_visible
        return Check(
            "SQL results shown to the model are capped",
            "PASS" if ok else "FAIL",
            f"cap={MAX_VISIBLE_ROWS}; {checked_visible:,} model-visible results checked, "
            f"largest shown={largest_visible:,} rows, over cap={over_cap}; "
            f"largest full result persisted={largest_full:,} rows "
            f"(proves truncation actually happened)",
        )

    def full_results_are_persisted(self) -> Check:
        refs = 0
        with open_jsonl(self.store.payloads_path) as handle:
            for line in handle:
                if '"tool_result"' in line:
                    refs += 1
        linked = sum(1 for step in self.steps if step.get("tool_result_ref"))
        return Check(
            "Full SQL results are persisted separately from model context",
            "PASS" if refs and linked else "FAIL",
            f"{refs:,} tool_result payloads, {linked:,} steps referencing them",
        )

    def sut_is_a_langgraph_agent(self) -> Check:
        try:
            from backend.app.spider.agent import build_graph

            graph = build_graph()
            nodes = set(getattr(graph, "nodes", {}))
        except Exception as error:  # noqa: BLE001
            return Check("The SUT is a LangGraph tool-using agent", "FAIL", str(error))

        expected = {"model", "tool", "finish", "max_steps"}
        multi_tool_episodes = sum(1 for e in self.episodes if e.get("tool_steps", 0) > 1)
        ok = expected <= nodes and multi_tool_episodes > 0
        return Check(
            "The SUT is a LangGraph tool-using agent",
            "PASS" if ok else "FAIL",
            f"compiled LangGraph nodes={sorted(nodes & expected)}; "
            f"{multi_tool_episodes:,} episodes made more than one tool call",
        )

    def verification_is_execution_based(self) -> Check:
        from backend.app.spider.evaluator import (
            EVALUATOR_METRIC_DISPLAY_NAME,
            EVALUATOR_NAME,
            KNOWN_EVALUATOR_METRIC_IDS,
            LEGACY_EVALUATOR_METRIC_IDS,
        )

        metrics = {
            (e.get("verification_result") or {}).get("metric")
            for e in self.episodes
            if e.get("verification_result")
        }
        recorded = {m for m in metrics if m}
        # A run must use exactly one metric. Legacy IDs are accepted because a
        # frozen artifact is immutable and the rename did not change semantics -
        # but never a *mix*, which would mean two metrics in one run.
        ok = len(recorded) == 1 and recorded <= KNOWN_EVALUATOR_METRIC_IDS
        legacy = recorded & LEGACY_EVALUATOR_METRIC_IDS
        note = " (pre-rename identifier)" if legacy else ""
        return Check(
            "SQL correctness uses execution-based verification",
            "PASS" if ok else "FAIL",
            f"evaluator={EVALUATOR_NAME}, metric={EVALUATOR_METRIC_DISPLAY_NAME}, "
            f"recorded id(s)={sorted(recorded)}{note}",
        )

    def gold_qa_passes(self) -> Check:
        gold = self.qa.get("gold_pass") or {}
        if not gold:
            return Check("Gold/reference QA passes for all non-excluded tasks", "UNVERIFIED",
                         "no verifier QA artifact")
        ok = gold["checked"] == gold["passed"] and gold["checked"] > 0
        return Check(
            "Gold/reference QA passes for all non-excluded tasks",
            "PASS" if ok else "FAIL",
            f"{gold['passed']:,}/{gold['checked']:,} gold queries pass",
        )

    def known_bad_qa_fails(self) -> Check:
        known_bad = self.qa.get("known_bad") or {}
        if not known_bad:
            return Check("Known-bad verifier QA fails as expected", "UNVERIFIED",
                         "no verifier QA artifact")
        ok = known_bad["checked"] > 0 and not known_bad["leaked"]
        return Check(
            "Known-bad verifier QA fails as expected",
            "PASS" if ok else "FAIL",
            f"{known_bad['rejected']:,}/{known_bad['checked']:,} rejected, "
            f"{len(known_bad['leaked'])} leaked, "
            f"{known_bad.get('skipped_denotationally_equivalent', 0)} discarded as equivalent",
        )

    def trajectories_are_complete(self) -> Check:
        by_episode: dict[str, int] = {}
        for step in self.steps:
            by_episode[step["episode_id"]] = by_episode.get(step["episode_id"], 0) + 1
        disagreements = [
            e["episode_id"] for e in self.episodes
            if by_episode.get(e["episode_id"], 0) != e["total_steps"]
        ]
        selected = set(self.config.get("selected_task_ids") or [])
        measured = {e["task_id"] for e in self.episodes}
        missing = selected - measured
        duplicates = self.store.duplicate_task_ids()

        ok = not disagreements and not missing and not duplicates
        return Check(
            "Complete trajectories are persisted",
            "PASS" if ok else "FAIL",
            f"{len(self.episodes):,} episodes, {len(self.steps):,} steps; "
            f"missing={len(missing)}, duplicates={len(duplicates)}, "
            f"step-count disagreements={len(disagreements)}",
        )

    def spans_are_emitted(self) -> Check:
        without = sum(1 for step in self.steps if not step.get("trace_id"))
        episodes_without = sum(1 for e in self.episodes if not e.get("trace_id"))
        ok = self.steps and without == 0 and episodes_without == 0
        return Check(
            "Model/tool/verifier steps emit OTel spans",
            "PASS" if ok else "FAIL",
            f"{len(self.steps):,} steps carry trace IDs "
            f"({without} without), {episodes_without} episodes without",
        )

    def traces_match_trajectories(self) -> Check:
        check = (self.trace_report or {}).get("trace_check") or {}
        if not check.get("available"):
            return Check(
                "Trace data matches persisted trajectory data",
                "UNVERIFIED",
                f"Elasticsearch unavailable: {check.get('error', 'not checked')}",
            )
        reconciliation = check.get("reconciliation", {})
        lines = ", ".join(
            f"{name} {entry['found']}/{entry['expected']}"
            for name, entry in reconciliation.items()
        )
        return Check(
            "Trace data matches persisted trajectory data",
            "PASS" if check.get("matches_trajectory") else "FAIL",
            f"{check.get('span_documents', 0):,} spans indexed; {lines}",
        )

    def no_unexplained_infrastructure_failures(self) -> Check:
        infra = (self.metrics or {}).get("infrastructure_correctness") or {}
        if not infra:
            return Check("Benchmark completes without unexplained infrastructure failures",
                         "UNVERIFIED", "run scripts/report_spider_metrics.py first")
        failures = (
            infra["generation_infrastructure_failures"]
            + infra["tool_infrastructure_failures"]
            + infra["evaluator_infrastructure_failures"]
            + infra["gold_query_failures"]
            + infra["missing_trajectories"]
        )
        return Check(
            "Benchmark completes without unexplained infrastructure failures",
            "PASS" if failures == 0 else "FAIL",
            f"generation={infra['generation_infrastructure_failures']}, "
            f"tool={infra['tool_infrastructure_failures']}, "
            f"evaluator={infra['evaluator_infrastructure_failures']}, "
            f"gold={infra['gold_query_failures']}, "
            f"missing trajectories={infra['missing_trajectories']}",
        )

    def _measured(self, label: str, section: str, keys: tuple[str, ...]) -> Check:
        block = (self.metrics or {}).get(section) or {}
        if not block:
            return Check(label, "UNVERIFIED", "run scripts/report_spider_metrics.py first")
        values = {key: block.get(key) for key in keys}
        missing = [key for key, value in values.items() if value is None]
        rendered = ", ".join(
            f"{key}={value:.4f}" if isinstance(value, float) else f"{key}={value}"
            for key, value in values.items()
        )
        return Check(label, "PASS" if not missing else "FAIL", rendered)

    def task_success_measured(self) -> Check:
        return self._measured(
            "Task success is measured", "primary", ("passed", "episodes_measured", "task_success_rate")
        )

    def steps_measured(self) -> Check:
        return self._measured(
            "Steps per successful task are measured",
            "agent_efficiency",
            ("mean_steps_per_successful_task", "median_steps_per_successful_task"),
        )

    def sql_error_rate_measured(self) -> Check:
        return self._measured(
            "SQL execution-error rate is measured",
            "tool_behavior",
            ("sql_executions_total", "sql_execution_errors_total", "sql_execution_error_rate"),
        )

    def tokens_and_cost_measured(self) -> Check:
        return self._measured(
            "Token and cost metrics are measured",
            "economics",
            (
                "mean_input_tokens_per_successful_task",
                "mean_output_tokens_per_successful_task",
                "mean_estimated_cost_per_successful_task",
            ),
        )

    def failure_categories_measured(self) -> Check:
        block = (self.metrics or {}).get("failure_breakdown") or {}
        if not block:
            return Check("Failure categories are measured", "UNVERIFIED",
                         "run scripts/report_spider_metrics.py first")
        counts = block.get("termination_counts", {})
        return Check(
            "Failure categories are measured",
            "PASS" if counts else "FAIL",
            ", ".join(f"{name}={count}" for name, count in sorted(counts.items())),
        )

    def configuration_is_saved(self) -> Check:
        required = (
            "dataset_version", "valid_task_ids", "excluded_task_ids",
            "agent_version", "prompt_version", "tool_schema_version",
            "model_version", "max_steps", "code_commit_sha", "run_id",
        )
        missing = [key for key in required if self.config.get(key) in (None, "")]
        return Check(
            "The exact benchmark configuration is saved",
            "PASS" if not missing else "FAIL",
            f"config.json has {len(required) - len(missing)}/{len(required)} required fields"
            + (f", missing={missing}" if missing else ""),
        )

    def protocol_limitation_documented(self) -> Check:
        path = REPO_ROOT / "docs" / "benchmark-protocol.md"
        if not path.exists():
            return Check("The benchmark protocol limitation is documented", "FAIL",
                         "docs/benchmark-protocol.md missing")
        text = path.read_text(encoding="utf-8").lower()
        required_points = {
            "schema discovered via tools": "not serialized into the initial prompt" in text
            or "does not" in text,
            "not leaderboard-comparable": "leaderboard" in text,
            "controlled deltas": "delta" in text,
        }
        missing = [name for name, present in required_points.items() if not present]
        return Check(
            "The benchmark protocol limitation is documented",
            "PASS" if not missing else "FAIL",
            f"docs/benchmark-protocol.md covers {len(required_points) - len(missing)}"
            f"/{len(required_points)} required points",
        )

    def metrics_are_reproducible(self) -> Check:
        """Recompute the headline number straight from episodes.jsonl.

        If the stored report disagrees with a fresh recount of the raw records,
        the report is not reproducible and nothing else in it can be trusted.
        """
        if not self.metrics:
            return Check("Metrics are reproducible from the stored run", "UNVERIFIED",
                         "run scripts/report_spider_metrics.py first")

        recomputed_passed = sum(
            1 for e in self.episodes if e["termination_reason"] == "SUCCESS"
        )
        recomputed_rate = recomputed_passed / len(self.episodes) if self.episodes else None
        stored_rate = (self.metrics.get("primary") or {}).get("task_success_rate")
        recomputed_tokens = sum(e["input_tokens"] for e in self.episodes)
        stored_tokens = (self.metrics.get("economics") or {}).get("total_input_tokens")

        ok = (
            stored_rate is not None
            and recomputed_rate is not None
            and abs(stored_rate - recomputed_rate) < 1e-9
            and recomputed_tokens == stored_tokens
        )
        return Check(
            "Metrics are reproducible from the stored run",
            "PASS" if ok else "FAIL",
            f"recomputed success {recomputed_passed}/{len(self.episodes)} "
            f"= {recomputed_rate:.4f} vs stored {stored_rate}; "
            f"input tokens {recomputed_tokens:,} vs {stored_tokens:,}",
        )

    def run_all(self) -> list[Check]:
        checks: list[Callable[[], Check]] = [
            self.spider_runs_through_the_runner,
            self.versions_are_pinned,
            self.exclusion_list_is_frozen,
            self.episodes_are_isolated,
            self.sql_access_is_read_only,
            self.inspect_schema_works,
            self.execute_sql_works,
            self.model_visible_rows_are_capped,
            self.full_results_are_persisted,
            self.sut_is_a_langgraph_agent,
            self.verification_is_execution_based,
            self.gold_qa_passes,
            self.known_bad_qa_fails,
            self.trajectories_are_complete,
            self.spans_are_emitted,
            self.traces_match_trajectories,
            self.no_unexplained_infrastructure_failures,
            self.task_success_measured,
            self.steps_measured,
            self.sql_error_rate_measured,
            self.tokens_and_cost_measured,
            self.failure_categories_measured,
            self.configuration_is_saved,
            self.protocol_limitation_documented,
            self.metrics_are_reproducible,
        ]

        results = []
        for check in checks:
            try:
                results.append(check())
            except Exception as error:  # noqa: BLE001
                results.append(
                    Check(check.__name__, "FAIL", f"{type(error).__name__}: {error}")
                )
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    trace_report = None
    metrics_path = root / args.run_id / "p0_metrics.json"
    if metrics_path.exists():
        trace_report = json.loads(metrics_path.read_text(encoding="utf-8"))

    verifier = P0Verifier(args.run_id, root, trace_report)
    results = verifier.run_all()

    symbols = {"PASS": "[x]", "FAIL": "[ ]", "UNVERIFIED": "[?]"}
    print(f"P0 completion check - run {args.run_id}\n")
    for check in results:
        print(f"{symbols[check.status]} {check.name}")
        print(f"      {check.evidence}")

    counts = {status: sum(1 for c in results if c.status == status) for status in symbols}
    print()
    print(f"{counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['UNVERIFIED']} unverified, of {len(results)} criteria")

    complete = counts["FAIL"] == 0 and counts["UNVERIFIED"] == 0
    print(f"\nP0 complete: {complete}")

    output = Path(args.output) if args.output else (root / args.run_id / "p0_completion.json")
    output.write_text(
        json.dumps(
            {
                "run_id": args.run_id,
                "checks": [vars(check) for check in results],
                "counts": counts,
                "p0_complete": complete,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {output}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
