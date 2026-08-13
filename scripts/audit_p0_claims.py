"""Audit every published P0 number against its source artifact.

For each claim this records six things and then **recomputes the value from the
raw artifact** rather than trusting the stored report:

    value · metric definition · exact denominator · source artifact ·
    run ID + code commit · model/config version

A claim whose recomputed value disagrees with the published one is reported as
MISMATCH. The point is that no number reaches the README without a query that
regenerates it.

It also closes the cost ledger across *every* run in the benchmark directory, so
"what did P0 cost" separates benchmark spend from total development spend instead
of leaving one number doing both jobs.

Usage:
    python scripts/audit_p0_claims.py --run-id spider_full__p0_v1
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.agent import MODEL_PRICING  # noqa: E402
from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    TrajectoryStore,
    open_jsonl,
)


@dataclass
class Claim:
    name: str
    value: Any
    definition: str
    numerator: Any = None
    denominator: Any = None
    source: str = ""
    status: str = "OK"
    note: str = ""

    def rendered(self) -> str:
        if isinstance(self.value, float):
            return f"{self.value:.6g}"
        if isinstance(self.value, int):
            return f"{self.value:,}"
        return str(self.value)


def build_cost_ledger(root: Path) -> dict[str, Any]:
    """Every run in the benchmark directory, with real spend separated from mock."""
    runs = []
    for config_path in sorted(root.glob("*/config.json")):
        run_dir = config_path.parent
        episodes_path = run_dir / "episodes.jsonl"
        if not episodes_path.exists():
            continue

        config = json.loads(config_path.read_text(encoding="utf-8"))
        with open_jsonl(episodes_path) as handle:
            episodes = [json.loads(line) for line in handle if line.strip()]
        if not episodes:
            continue

        runs.append(
            {
                "run_id": run_dir.name,
                "stage": config.get("stage"),
                "is_mock": bool(config.get("is_mock")),
                "model_version": config.get("model_version"),
                "prompt_version": config.get("prompt_version"),
                "tool_schema_version": config.get("tool_schema_version"),
                "episodes": len(episodes),
                "successes": sum(
                    1 for e in episodes if e["termination_reason"] == "SUCCESS"
                ),
                "input_tokens": sum(e["input_tokens"] for e in episodes),
                "output_tokens": sum(e["output_tokens"] for e in episodes),
                "estimated_cost_usd": sum(e["estimated_cost"] for e in episodes),
            }
        )

    real = [r for r in runs if not r["is_mock"]]
    mock = [r for r in runs if r["is_mock"]]

    def totals(rows: list[dict]) -> dict[str, Any]:
        return {
            "runs": len(rows),
            "episodes": sum(r["episodes"] for r in rows),
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "estimated_cost_usd": sum(r["estimated_cost_usd"] for r in rows),
        }

    return {
        "pricing_snapshot_usd_per_1m_tokens": MODEL_PRICING,
        "pricing_basis": (
            "Published list price at time of run. NOT a billed invoice amount. "
            "Cached-input pricing is applied when the API reports cached prompt tokens, "
            "so recomputing cost from headline input/output prices alone yields a "
            "slightly higher figure."
        ),
        "runs": runs,
        "real_api_spend": totals(real),
        "mock_rehearsal_no_spend": totals(mock),
    }


def audit(run_id: str, root: Path) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes at {store.episodes_path}")

    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    episodes = list(store.iter_episodes())
    steps = list(store.iter_steps())

    def load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    metrics = load(store.run_dir / "p0_metrics.json")
    completion = load(store.run_dir / "p0_completion.json")
    failures = load(store.run_dir / "failure_analysis.json")
    qa = load(REPO_ROOT / "runs" / "spider_verifier_qa" / "verifier_qa_dev.json")

    provenance = {
        "run_id": run_id,
        "code_commit_sha": config.get("code_commit_sha"),
        "code_working_tree_dirty": config.get("code_working_tree_dirty"),
        "dataset_version": config.get("dataset_version"),
        "archive_sha256": config.get("archive_sha256"),
        "model_version": config.get("model_version"),
        "prompt_version": config.get("prompt_version"),
        "tool_schema_version": config.get("tool_schema_version"),
        "agent_version": config.get("agent_version"),
        "adapter_version": config.get("adapter_version"),
        "max_steps": config.get("max_steps"),
        "temperature": config.get("temperature"),
    }

    total = len(episodes)
    successes = [e for e in episodes if e["termination_reason"] == "SUCCESS"]
    tool_steps = [s for s in steps if s["step_type"] == "tool"]
    sql_calls = [s for s in tool_steps if s["tool_name"] == "execute_sql"]
    sql_failures = [s for s in sql_calls if s["tool_success"] is False]

    claims: list[Claim] = []

    claims.append(Claim(
        name="task_success_rate",
        value=len(successes) / total,
        definition=(
            "Episodes terminating SUCCESS divided by episodes measured. SUCCESS "
            "means the submitted SQL passed single-database execution accuracy "
            "against gold."
        ),
        numerator=len(successes), denominator=total,
        source="episodes.jsonl (termination_reason == 'SUCCESS')",
    ))

    claims.append(Claim(
        name="execute_sql_error_rate",
        value=len(sql_failures) / len(sql_calls) if sql_calls else None,
        definition=(
            "Failed execute_sql TOOL CALLS divided by total execute_sql TOOL CALLS. "
            "Tool-call denominator, not episodes. Distinct from the SQL_ERROR "
            "termination reason, which is episode-level."
        ),
        numerator=len(sql_failures), denominator=len(sql_calls),
        source="steps.jsonl (tool_name == 'execute_sql')",
    ))

    claims.append(Claim(
        name="sql_error_terminations",
        value=sum(1 for e in episodes if e["termination_reason"] == "SQL_ERROR"),
        definition=(
            "Episodes whose FINAL SUBMITTED query failed to execute. Episode "
            "denominator. Not to be reported alongside the tool-call error rate."
        ),
        numerator=sum(1 for e in episodes if e["termination_reason"] == "SQL_ERROR"),
        denominator=total,
        source="episodes.jsonl (termination_reason == 'SQL_ERROR')",
    ))

    claims.append(Claim(
        name="mean_model_turns_per_successful_task",
        value=statistics.fmean([e["model_steps"] for e in successes]) if successes else None,
        definition="Model API calls per successful episode. This is what max_steps caps.",
        denominator=f"{len(successes)} successful episodes",
        source="episodes.jsonl field model_steps",
    ))

    claims.append(Claim(
        name="median_model_turns_per_successful_task",
        value=statistics.median([e["model_steps"] for e in successes]) if successes else None,
        definition="Median model API calls per successful episode.",
        denominator=f"{len(successes)} successful episodes",
        source="episodes.jsonl field model_steps",
    ))

    claims.append(Claim(
        name="mean_tool_calls_per_successful_task",
        value=statistics.fmean([e["tool_steps"] for e in successes]) if successes else None,
        definition=(
            "Tool invocations per successful episode, counting inspect_schema, "
            "execute_sql, and the single terminating submit_answer."
        ),
        denominator=f"{len(successes)} successful episodes",
        source="episodes.jsonl field tool_steps",
    ))

    claims.append(Claim(
        name="mean_trajectory_records_per_successful_task",
        value=statistics.fmean([e["total_steps"] for e in successes]) if successes else None,
        definition=(
            "Rows written to steps.jsonl per successful episode = model turns + "
            "tool calls. This is the quantity previously published as 'steps', "
            "which was ambiguous."
        ),
        denominator=f"{len(successes)} successful episodes",
        source="episodes.jsonl field total_steps",
        note="Superseded the ambiguous 'mean steps per successful task'.",
    ))

    claims.append(Claim(
        name="trajectory_step_records",
        value=len(steps),
        definition="Total rows in steps.jsonl across the run.",
        denominator=f"{total} episodes",
        source="steps.jsonl line count",
    ))

    span_documents = ((metrics.get("trace_check") or {}).get("span_documents"))
    claims.append(Claim(
        name="indexed_spans",
        value=span_documents,
        definition=(
            "OTel span documents in Elasticsearch carrying attributes.run.id == "
            "this run. Exceeds trajectory records because spans also cover "
            "eval.run, agent.episode, sqlite.query, and verifier.execution, none "
            "of which are trajectory step rows."
        ),
        denominator="span documents for this run.id",
        source="p0_metrics.json trace_check (track_total_hits enabled)",
        status="OK" if span_documents else "UNVERIFIED",
    ))

    # cost
    total_cost = sum(e["estimated_cost"] for e in episodes)
    claims.append(Claim(
        name="benchmark_only_estimated_cost_usd",
        value=total_cost,
        definition=(
            "Sum of per-episode estimated cost for THIS run only. Estimated from "
            "published list price, not billed."
        ),
        denominator=f"{total} episodes",
        source="episodes.jsonl field estimated_cost",
    ))
    claims.append(Claim(
        name="estimated_cost_per_episode_usd",
        value=total_cost / total if total else None,
        definition="Benchmark-only estimated cost divided by episodes measured.",
        numerator=total_cost, denominator=total,
        source="episodes.jsonl",
    ))
    # Canonical definition: TOTAL benchmark cost divided by successes. This answers
    # "what did each success cost", which necessarily includes the spend on
    # episodes that failed. An earlier version published the mean over successful
    # episodes only ($0.000526), which silently excluded the cost of failure and
    # is a different question; it is retired.
    claims.append(Claim(
        name="estimated_cost_per_successful_episode_usd",
        value=total_cost / len(successes) if successes else None,
        definition=(
            "TOTAL benchmark estimated cost divided by the number of successful "
            "episodes. Includes spend on failed episodes, because those were paid "
            "for too. Not the mean cost of a successful episode."
        ),
        numerator=total_cost, denominator=len(successes),
        source="episodes.jsonl",
    ))
    claims.append(Claim(
        name="mean_cost_of_a_successful_episode_usd",
        value=(
            sum(e["estimated_cost"] for e in successes) / len(successes)
            if successes else None
        ),
        definition=(
            "Mean estimated cost of episodes that succeeded, excluding spend on "
            "failures. Reported only to keep it distinguishable from the canonical "
            "cost-per-success above; do not publish it as cost per success."
        ),
        numerator=sum(e["estimated_cost"] for e in successes), denominator=len(successes),
        source="episodes.jsonl",
    ))
    claims.append(Claim(
        name="total_input_tokens",
        value=sum(e["input_tokens"] for e in episodes),
        definition="Prompt tokens reported by the API, summed over the run.",
        denominator=f"{total} episodes", source="episodes.jsonl field input_tokens",
    ))
    claims.append(Claim(
        name="total_output_tokens",
        value=sum(e["output_tokens"] for e in episodes),
        definition="Completion tokens reported by the API, summed over the run.",
        denominator=f"{total} episodes", source="episodes.jsonl field output_tokens",
    ))

    # verifier QA
    gold = qa.get("gold_pass") or {}
    known_bad = qa.get("known_bad") or {}
    attempted = (known_bad.get("checked", 0)
                 + known_bad.get("skipped_denotationally_equivalent", 0))

    claims.append(Claim(
        name="gold_pass_qa",
        value=f"{gold.get('passed')}/{gold.get('checked')}",
        definition=(
            "Gold queries fed to the evaluator as if they were predictions, and "
            "passing. Run before any agent episode; empty exclusion list follows."
        ),
        numerator=gold.get("passed"), denominator=gold.get("checked"),
        source="runs/spider_verifier_qa/verifier_qa_dev.json gold_pass",
        status="OK" if gold else "UNVERIFIED",
    ))
    claims.append(Claim(
        name="known_bad_detected",
        value=f"{known_bad.get('rejected')}/{known_bad.get('checked')}",
        definition=(
            "Deliberately wrong queries correctly rejected, among mutations that "
            "were FIRST PROVEN to return different rows from gold."
        ),
        numerator=known_bad.get("rejected"), denominator=known_bad.get("checked"),
        source="runs/spider_verifier_qa/verifier_qa_dev.json known_bad",
        status="OK" if known_bad else "UNVERIFIED",
    ))
    claims.append(Claim(
        name="mutation_execution_collisions",
        value=known_bad.get("skipped_denotationally_equivalent"),
        definition=(
            "Mutations that changed the SQL text but returned exactly gold's rows "
            "on the shipped database, so they were discarded rather than counted "
            "as verifier leaks."
        ),
        numerator=known_bad.get("skipped_denotationally_equivalent"),
        denominator=attempted,
        source="runs/spider_verifier_qa/verifier_qa_dev.json known_bad",
        status="OK" if known_bad else "UNVERIFIED",
    ))
    claims.append(Claim(
        name="mutation_collision_rate",
        value=(
            known_bad.get("skipped_denotationally_equivalent", 0) / attempted
            if attempted else None
        ),
        definition=(
            "Collisions divided by mutations ATTEMPTED. A property of this "
            "mutation set on this database. It is NOT an estimate of the share of "
            "the agent's passes that are false positives - the agent's queries are "
            "not drawn from this mutation distribution."
        ),
        numerator=known_bad.get("skipped_denotationally_equivalent"),
        denominator=attempted,
        source="runs/spider_verifier_qa/verifier_qa_dev.json known_bad",
        status="OK" if known_bad else "UNVERIFIED",
    ))

    # failure analysis
    max_steps_block = (failures.get("max_steps_analysis") or {})
    claims.append(Claim(
        name="max_step_episodes",
        value=max_steps_block.get("total_max_step_episodes"),
        definition="Episodes terminating MAX_STEPS (model-turn cap reached without submitting).",
        numerator=max_steps_block.get("total_max_step_episodes"), denominator=total,
        source="failure_analysis.json",
        status="OK" if max_steps_block else "UNVERIFIED",
    ))
    broad = max_steps_block.get("empty_result_loop_broad") or {}
    claims.append(Claim(
        name="empty_result_loop_broad",
        value=broad.get("count"),
        definition=(failures.get("max_steps_analysis", {})
                    .get("rules", {}).get("empty_result_loop_broad", "")),
        numerator=broad.get("count"),
        denominator=max_steps_block.get("total_max_step_episodes"),
        source="failure_analysis.json (task IDs stored)",
        status="OK" if broad else "UNVERIFIED",
    ))
    abandoned = max_steps_block.get("abandoned_a_correct_query") or {}
    claims.append(Claim(
        name="abandoned_a_correct_query",
        value=abandoned.get("count"),
        definition=(failures.get("max_steps_analysis", {})
                    .get("rules", {}).get("abandoned_a_correct_query", "")),
        numerator=abandoned.get("count"),
        denominator=max_steps_block.get("total_max_step_episodes"),
        source="failure_analysis.json (task IDs stored)",
        status="OK" if abandoned.get("count") is not None else "UNVERIFIED",
    ))

    comparison = {}
    for path in sorted(store.run_dir.glob("comparison_vs_*.json")):
        comparison = json.loads(path.read_text(encoding="utf-8"))
        break

    if comparison:
        ledger = comparison["pass_fail_ledger"]
        shared = comparison["task_sets"]["shared"]
        for name, key in (
            ("repeat_pass_to_pass", "pass_to_pass"),
            ("repeat_pass_to_fail", "pass_to_fail"),
            ("repeat_fail_to_pass", "fail_to_pass"),
            ("repeat_fail_to_fail", "fail_to_fail"),
        ):
            claims.append(Claim(
                name=name,
                value=ledger[key],
                definition=(
                    f"Tasks with outcome {key.replace('_', ' ')} between "
                    f"{comparison['run_a']} and {comparison['run_b']}, joined on "
                    "task_id. PASS means termination_reason == SUCCESS."
                ),
                numerator=ledger[key], denominator=shared,
                source=f"comparison_vs_{comparison['run_a']}.json",
            ))
        claims.append(Claim(
            name="repeat_total_pass_fail_flips",
            value=ledger["total_pass_fail_flips"],
            definition=(
                "PASS->FAIL + FAIL->PASS across two runs of an identical recorded "
                "configuration. NOT the count of termination-reason changes, which "
                "is larger because it includes fail-to-fail reason changes."
            ),
            numerator=ledger["total_pass_fail_flips"], denominator=shared,
            source=f"comparison_vs_{comparison['run_a']}.json",
            note="Supersedes an earlier figure of 49, which counted reason changes.",
        ))
        claims.append(Claim(
            name="repeat_termination_reason_changes",
            value=comparison["termination_reason_churn"]["total_reason_changes"],
            definition=(
                "Any change in termination_reason between the two runs, including "
                "fail-to-fail changes that did not alter the outcome."
            ),
            denominator=shared,
            source=f"comparison_vs_{comparison['run_a']}.json",
        ))

    overlap = (failures.get("max_steps_analysis") or {}).get("cohort_overlap") or {}
    if overlap:
        claims.append(Claim(
            name="abandoned_correct_query_in_empty_result_cohort",
            value=overlap.get("in_both"),
            definition=(
                "Exact intersection of episodes that abandoned a verifier-passing "
                "query with the empty_result_loop_broad cohort."
            ),
            numerator=overlap.get("in_both"),
            denominator=overlap.get("abandoned_correct_query"),
            source="failure_analysis.json",
        ))
        claims.append(Claim(
            name="abandoned_correct_query_share_of_benchmark_pp",
            value=(max_steps_block.get("abandoned_a_correct_query") or {}).get(
                "share_of_benchmark_pp"
            ),
            definition=(
                "Observed theoretical headroom in percentage points: episodes that "
                "executed a verifier-passing query and never submitted it, over all "
                "measured episodes. NOT guaranteed recoverable accuracy."
            ),
            numerator=(max_steps_block.get("abandoned_a_correct_query") or {}).get("count"),
            denominator=total,
            source="failure_analysis.json",
        ))

    claims.append(Claim(
        name="p0_criteria_verified",
        value=f"{(completion.get('counts') or {}).get('PASS')}/"
              f"{len(completion.get('checks') or [])}",
        definition="P0 completion criteria passing in scripts/verify_p0_completion.py.",
        source="p0_completion.json",
        status="OK" if completion else "UNVERIFIED",
    ))

    # -- cost algebra ------------------------------------------------------
    # Recompute total cost from tokens and the pricing snapshot. If the run
    # persisted cached_input_tokens, this reproduces the stored figure exactly.
    # Older runs did not, so the cached count can only be *solved backwards* -
    # recorded here as an explicit weakness rather than glossed over.
    pricing = MODEL_PRICING.get(config.get("model_version")) or {}
    total_input = sum(e["input_tokens"] for e in episodes)
    total_output = sum(e["output_tokens"] for e in episodes)
    persisted_cached = sum(e.get("cached_input_tokens") or 0 for e in episodes)
    has_cached_field = any("cached_input_tokens" in e for e in episodes)

    uncached_price = pricing.get("input")
    cached_price = pricing.get("cached_input", uncached_price)
    output_price = pricing.get("output")

    cost_algebra: dict[str, Any] = {
        "pricing_snapshot_usd_per_1m": pricing,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "stored_total_cost_usd": total_cost,
        "persisted_cached_input_tokens": persisted_cached if has_cached_field else None,
        "cached_input_tokens_persisted": has_cached_field,
    }

    if uncached_price is not None and output_price is not None:
        naive = (total_input * uncached_price + total_output * output_price) / 1e6
        cost_algebra["cost_at_full_input_price_usd"] = naive
        cost_algebra["cache_discount_usd"] = naive - total_cost

        if has_cached_field and persisted_cached:
            recomputed = (
                (total_input - persisted_cached) * uncached_price
                + persisted_cached * cached_price
                + total_output * output_price
            ) / 1e6
            cost_algebra["recomputed_from_persisted_tokens_usd"] = recomputed
            cost_algebra["reconciles_exactly"] = abs(recomputed - total_cost) < 1e-9
        else:
            denominator = uncached_price - cached_price
            implied = (naive - total_cost) * 1e6 / denominator if denominator else None
            cost_algebra["implied_cached_input_tokens"] = implied
            cost_algebra["implied_cached_share_of_input"] = (
                implied / total_input if implied and total_input else None
            )
            cost_algebra["reconciles_exactly"] = None
            cost_algebra["limitation"] = (
                "This run did not persist cached_input_tokens, so the cached count "
                "is solved backwards from the cost rather than read from the "
                "record. The arithmetic closes, but it is a consistency check, not "
                "an independent derivation. Runs after this fix persist the field."
            )

    # cross-check the audit's recomputation against the published report
    mismatches = []
    published = {
        "task_success_rate": (metrics.get("primary") or {}).get("task_success_rate"),
        "execute_sql_error_rate": (metrics.get("tool_behavior") or {}).get(
            "sql_execution_error_rate"
        ),
        "total_input_tokens": (metrics.get("economics") or {}).get("total_input_tokens"),
        "total_output_tokens": (metrics.get("economics") or {}).get("total_output_tokens"),
        "benchmark_only_estimated_cost_usd": (metrics.get("economics") or {}).get(
            "total_estimated_cost"
        ),
    }
    by_name = {claim.name: claim for claim in claims}
    for name, published_value in published.items():
        if published_value is None or name not in by_name:
            continue
        recomputed = by_name[name].value
        agree = (
            abs(recomputed - published_value) < 1e-9
            if isinstance(recomputed, float)
            else recomputed == published_value
        )
        if not agree:
            by_name[name].status = "MISMATCH"
            by_name[name].note = f"published={published_value} recomputed={recomputed}"
            mismatches.append(name)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance,
        "claims": [asdict(claim) for claim in claims],
        "cost_algebra": cost_algebra,
        "cost_ledger": build_cost_ledger(root),
        "mismatches": mismatches,
        "all_reconciled": not mismatches
        and all(c.status in {"OK"} for c in claims),
        "unverified": [c.name for c in claims if c.status == "UNVERIFIED"],
    }


def print_report(report: dict[str, Any]) -> None:
    print("P0 CLAIMS AUDIT\n")
    print("Provenance (applies to every claim below):")
    for key, value in report["provenance"].items():
        print(f"  {key:<26} {value}")
    print()

    print(f"{'claim':<44} {'value':>14}  {'denominator':<26} status")
    print("-" * 104)
    for claim in report["claims"]:
        value = claim["value"]
        rendered = f"{value:.6g}" if isinstance(value, float) else (
            f"{value:,}" if isinstance(value, int) else str(value)
        )
        print(f"{claim['name']:<44} {rendered:>14}  "
              f"{str(claim['denominator'])[:26]:<26} {claim['status']}")
        if claim["note"]:
            print(f"    note: {claim['note']}")
    print()

    algebra = report["cost_algebra"]
    print("COST ALGEBRA")
    for key, value in algebra.items():
        if isinstance(value, float):
            print(f"  {key:<40} {value:,.6f}")
        elif isinstance(value, dict):
            print(f"  {key:<40} {value}")
        else:
            print(f"  {key:<40} {value}")
    print()

    ledger = report["cost_ledger"]
    print("COST LEDGER  (list price, not billed)")
    print(f"{'run':<30} {'stage':<8} {'mock':<6} {'eps':>6} {'in':>11} {'out':>8} {'usd':>9}")
    for row in ledger["runs"]:
        print(f"{row['run_id']:<30} {str(row['stage']):<8} {str(row['is_mock']):<6} "
              f"{row['episodes']:>6,} {row['input_tokens']:>11,} "
              f"{row['output_tokens']:>8,} {row['estimated_cost_usd']:>9.4f}")
    real = ledger["real_api_spend"]
    mock = ledger["mock_rehearsal_no_spend"]
    print("-" * 84)
    print(f"{'REAL API SPEND (all P0 dev+test)':<30} {'':<8} {'':<6} "
          f"{real['episodes']:>6,} {real['input_tokens']:>11,} "
          f"{real['output_tokens']:>8,} {real['estimated_cost_usd']:>9.4f}")
    print(f"{'  mock rehearsals (no spend)':<30} {'':<8} {'':<6} "
          f"{mock['episodes']:>6,} {mock['input_tokens']:>11,} "
          f"{mock['output_tokens']:>8,} {mock['estimated_cost_usd']:>9.4f}")
    print()

    print(f"all_reconciled: {report['all_reconciled']}")
    if report["mismatches"]:
        print(f"MISMATCHES: {report['mismatches']}")
    if report["unverified"]:
        print(f"UNVERIFIED: {report['unverified']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = audit(args.run_id, Path(args.root))
    print_report(report)

    output = Path(args.output) if args.output else (
        Path(args.root) / args.run_id / "claims_audit.json"
    )
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0 if report["all_reconciled"] else 1


if __name__ == "__main__":
    sys.exit(main())
