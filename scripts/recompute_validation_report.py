"""Recompute the summary metrics of a saved dual-judge validation report.

The per-case judge scores are persisted in every validation report, so summary
fields can be recomputed from them without re-running any judge. That matters
when a metric function is corrected after a report was written: the raw
measurement is still valid, only the derived summary was wrong.

This performs no new measurement. It only re-derives summary fields from
already-persisted per-case scores using the current implementation.

Usage:
    python scripts/recompute_validation_report.py runs/gpu_window/real_7b_validation_report.json
    python scripts/recompute_validation_report.py <path> --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.dual_judge_validation import calculate_cohens_kappa  # noqa: E402


def recompute(report: dict) -> dict:
    results = report.get("results", [])
    if not results:
        raise ValueError("Report has no per-case results to recompute from.")

    labels_a = [bool(r["judge_a_score"]["passed"]) for r in results]
    labels_b = [bool(r["judge_b_score"]["passed"]) for r in results]
    total = len(results)

    pass_rate_a = sum(labels_a) / total
    pass_rate_b = sum(labels_b) / total
    degenerate = pass_rate_a in (0.0, 1.0) or pass_rate_b in (0.0, 1.0)

    return {
        "total_cases": total,
        "judge_a_pass_rate": pass_rate_a,
        "judge_b_pass_rate": pass_rate_b,
        "agreement_is_degenerate": degenerate,
        "inter_judge_kappa": calculate_cohens_kappa(labels_a, labels_b),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the recomputed fields back into the report file.",
    )
    args = parser.parse_args()

    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    recomputed = recompute(report)

    print(f"report: {args.report_path}")
    print(f"  stored inter_judge_kappa:      {report.get('inter_judge_kappa')!r}")
    print(f"  recomputed inter_judge_kappa:  {recomputed['inter_judge_kappa']!r}")
    print(f"  judge_a pass rate:             {recomputed['judge_a_pass_rate']:.4f}")
    print(f"  judge_b pass rate:             {recomputed['judge_b_pass_rate']:.4f}")
    print(f"  agreement_is_degenerate:       {recomputed['agreement_is_degenerate']}")

    if recomputed["agreement_is_degenerate"]:
        print()
        print("  NOTE: at least one judge used a single pass/fail category, so")
        print("  pass/fail agreement is trivially high and kappa is undefined.")
        print("  This slice does not support a judge-agreement claim.")

    if args.write:
        report.update(recomputed)
        args.report_path.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print()
        print(f"  wrote recomputed summary fields into {args.report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
