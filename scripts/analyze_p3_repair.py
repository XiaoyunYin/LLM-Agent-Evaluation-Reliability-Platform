"""Apply the pre-registered verdict to the schema-repair experiment.

Reads docs/P3_REPAIR_PREREGISTRATION.md's rules as code. Nothing here decides
anything the pre-registration did not already decide; it only measures and looks
up the verdict.

    python -m scripts.analyze_p3_repair \\
        --baseline support_b3_01 ... --bridge support_p3_bridge \\
        --treatment support_p3_on_1 ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.p3_repair_metrics import arm_metrics, load_arm  # noqa: E402

MANIFEST = REPO_ROOT / "config" / "p3_frozen_manifest.json"
COHORT = REPO_ROOT / "config" / "p3_repair_cohort.json"
RESULT = REPO_ROOT / "runs" / "support_baseline" / "repair_experiment.json"

DELTA_THRESHOLD = 0.10


def show(name: str, metrics: dict) -> None:
    if not metrics.get("episodes"):
        print(f"{name}: no usable episodes")
        return
    primary = metrics["repeat_invalid_rate"]
    primary_text = "n/a (no invalid calls)" if primary is None else f"{primary:.4f}"
    print(f"\n=== {name} ===")
    print(f"  runs {metrics['runs']}  episodes {metrics['episodes']}")
    print(f"  invalid calls              {metrics['invalid_calls']}")
    print(f"  episodes with >=1 invalid  {metrics['episodes_with_invalid']}")
    print(f"  episodes with >=2 invalid  {metrics['episodes_with_two_or_more']}")
    print(f"  PRIMARY repeat-invalid     {primary_text}"
          f"{'   [DEGENERATE]' if metrics['degenerate'] else ''}")
    print(f"  success                    {metrics['success']:.4f}")
    print(f"  mean turns / episode       {metrics['mean_turns']:.2f}")
    print(f"  mean cost / episode        ${metrics['mean_cost']:.6f}")
    rates = [r["success"] for r in metrics["per_run"]]
    print(f"  per-run success range      {min(rates):.4f} - {max(rates):.4f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", nargs="+", required=True)
    parser.add_argument("--bridge", nargs="*", default=[])
    parser.add_argument("--treatment", nargs="*", default=[])
    args = parser.parse_args()

    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cohort_spec = json.loads(COHORT.read_text(encoding="utf-8")) if COHORT.exists() else None
    cohort = set(cohort_spec["cohort"]) if cohort_spec else None
    if cohort_spec:
        print(f"cohort: {cohort_spec['cohort_size']} tasks, rule '{cohort_spec['rule']}'")
        if cohort_spec["underpowered"]:
            print("  UNDERPOWERED per pre-registration §6")
        if cohort_spec["suite_sha256"] != frozen["suite_sha256"]:
            print("  !! cohort was frozen against a different suite hash")

    arms = {}
    for name, run_ids in (("BASELINE (OFF)", args.baseline),
                          ("BRIDGE (OFF, treatment commit)", args.bridge),
                          ("TREATMENT (ON)", args.treatment)):
        if not run_ids:
            continue
        episodes, excluded = load_arm(run_ids, frozen["task_count"])
        for note in excluded:
            print(f"EXCLUDED {note}")
        arms[name] = arm_metrics(episodes, cohort)
        show(f"{name} — cohort", arms[name])
        arms[name + " / global"] = arm_metrics(episodes, None)
        show(f"{name} — global", arms[name + " / global"])

    base = arms.get("BASELINE (OFF)")
    treat = arms.get("TREATMENT (ON)")

    # ---- bridge acceptance (pre-registration §7) --------------------------
    bridge = arms.get("BRIDGE (OFF, treatment commit) / global")
    verdict_lines = []
    if bridge and base:
        base_success = [r["success"] for r in arms["BASELINE (OFF) / global"]["per_run"]]
        inside = min(base_success) <= bridge["success"] <= max(base_success)
        verdict_lines.append(
            f"BRIDGE: success {bridge['success']:.4f} vs baseline range "
            f"{min(base_success):.4f}-{max(base_success):.4f} -> "
            f"{'ACCEPTED' if inside else 'REJECTED - the commit is not inert, stop'}"
        )

    # ---- primary verdict (pre-registration §9 + amendment 1) --------------
    if base and treat and base.get("episodes") and treat.get("episodes"):
        if base["degenerate"] and treat["degenerate"]:
            verdict_lines.append(
                "PRIMARY: DEGENERATE in both arms - zero episodes emitted a second "
                "invalid call either way. Verdict NO EFFECT ON THE PRIMARY METRIC, "
                "per amendment 1. The publishable finding is the recovery rate "
                "itself: a structured validation error is already sufficient for "
                "one-shot recovery in 100% of observed cases."
            )
        else:
            delta = (base["repeat_invalid_rate"] or 0) - (treat["repeat_invalid_rate"] or 0)
            base_range = [r["repeat_invalid_rate"] for r in base["per_run"]]
            treat_range = [r["repeat_invalid_rate"] for r in treat["per_run"]]
            overlap = not (max(treat_range) < min(base_range) or min(treat_range) > max(base_range))
            base_success = [r["success"] for r in base["per_run"]]
            regressed = treat["success"] < min(base_success)
            if regressed:
                verdict = "REJECT - task success regressed below the baseline minimum"
            elif abs(delta) < DELTA_THRESHOLD:
                verdict = "NO EFFECT - null result, keep the flag off"
            elif delta >= DELTA_THRESHOLD and not overlap:
                verdict = "ADOPT"
            elif delta >= DELTA_THRESHOLD:
                verdict = "INCONCLUSIVE - ranges overlap"
            else:
                verdict = "HARMFUL - keep off"
            verdict_lines.append(f"PRIMARY: delta={delta:+.4f}  overlap={overlap}  -> {verdict}")

        # Secondary metrics are reported, never promoted.
        verdict_lines.append(
            f"SECONDARY (reported, not promoted): turns "
            f"{base['mean_turns']:.2f} -> {treat['mean_turns']:.2f}; "
            f"cost ${base['mean_cost']:.6f} -> ${treat['mean_cost']:.6f}; "
            f"success {base['success']:.4f} -> {treat['success']:.4f}"
        )

    print("\n=== PRE-REGISTERED VERDICT ===")
    for line in verdict_lines or ["not enough arms measured yet"]:
        print(f"  {line}")

    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(
        {"arms": arms, "cohort": cohort_spec, "verdict": verdict_lines}, indent=2
    ) + "\n", encoding="utf-8")
    print(f"\nWrote {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
