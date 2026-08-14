# P1 Pre-Registration

> **Historical version:** decision rules were superseded by
> [`P1_PREREGISTRATION_V2.md`](P1_PREREGISTRATION_V2.md) before the P1 runs.

Written and committed **before** the runs it governs were executed. The point is
that the decision rule cannot be adjusted after seeing the result — that is the
difference between a measurement and a rationalisation.

Commit this file before launching any run described in it.

---

## 1. What is being measured

### A. Same-commit repeat variability (ON repeats)

Repeated executions of the canonical P0 configuration from a **clean working tree
at a single commit**, to establish how much the benchmark moves when nothing
changes.

- Runs: **4** (`spider_rpt__on_1` … `spider_rpt__on_4`)
- Configuration: identical to `spider_full__p0_v2` — `gpt-4o-mini`, temperature 0,
  `sql_agent_v1`, `spider_tools_v2`, `max_steps=10`, full 1,034-task dev split
- No seed is sent. These are **repeated runs under an identical recorded
  configuration**, not seeded runs.

### B. Tool-argument-validation ablation (OFF run)

One run with tool-argument validation disabled, reverting `inspect_schema` to the
`spider_tools_v1` behaviour of silently ignoring unknown arguments.

- Run: **1** (`spider_abl__off_1`), `tool_schema_version = spider_tools_v1_ablation`
- Everything else identical to the ON configuration.

This replaces the n=10 smoke comparison (5/10 → 8/10), which is below the noise
floor and was never a quantitative claim.

---

## 2. The decision rule — fixed in advance

Let the ON repeats give observed accuracies `a₁ … a₄`, with
`ON_min = min(aᵢ)` and `ON_max = max(aᵢ)`. Let `OFF` be the ablation accuracy.

**This range is a descriptive envelope over 4 runs, not a confidence interval.**
With n=4 no distributional claim is available, and none will be made.

| Condition | Verdict | Wording permitted |
|---|---|---|
| `OFF < ON_min` and `ON_min − OFF > (ON_max − ON_min)` | **Effect supported** | "Disabling tool-argument validation reduced accuracy by X points, a gap larger than the observed same-commit spread over 4 repeats." |
| `OFF < ON_min` but gap ≤ spread | **Inconclusive — directionally consistent** | "Directionally consistent with a benefit, but the gap does not exceed same-commit run-to-run spread. Not established." |
| `ON_min ≤ OFF ≤ ON_max` | **Inconclusive — within noise** | "No effect distinguishable from run-to-run variation at n=1 OFF run." |
| `OFF > ON_max` | **Contradicts the hypothesis** | Report plainly that the ablation scored *higher*, and do not explain it away. |

Additional pre-committed conditions:

1. **A single OFF run cannot establish an effect size.** Even under "Effect
   supported", the reported quantity is a gap between one run and an envelope, not
   a calibrated effect.
2. **Mechanism evidence is reported regardless of verdict.** The count of
   `inspect_schema` calls carrying an unknown argument, and the count of episodes
   terminating `MAX_STEPS`, are reported for ON and OFF whatever the accuracy does.
   The mechanism is directly observable in trajectories and does not depend on the
   accuracy delta.
3. **If the verdict is inconclusive, that is the published result.** The permitted
   responses are (a) report inconclusive, or (b) buy additional OFF repeats and
   re-apply this same rule. Selecting a different statistic after the fact is not
   permitted.
4. **No stopping on a favourable result.** All 4 ON repeats complete before the OFF
   run is analysed.

---

## 3. CI threshold derivation — fixed in advance

Thresholds come from the measured same-commit envelope, not from judgement.

For each gated metric, let `spread = max − min` over the 4 ON repeats.

```
gate_threshold = max(2 × spread, minimum_detectable_change)
```

- The `2 ×` factor is chosen in advance so a gate fires on a change roughly twice
  the size of observed same-commit noise. It is a stated policy choice, not a
  statistical guarantee.
- `minimum_detectable_change` is one task (1/1,034 = 0.097pp) for accuracy, to stop
  a degenerate zero-width threshold if all repeats coincide.
- Any threshold that comes out **wider** than the previous arbitrary 5% is reported
  as such rather than quietly tightened.

### Gate vs monitor split, fixed in advance

**Gate** — fails CI:

- task success (single-database execution accuracy)
- consistency (per-task pass frequency across repeats)
- trajectory records and model turns per successful task
- tool validity (share of tool calls rejected for bad arguments)
- token-derived estimated cost per successful episode

**Monitor** — reported, never fails CI:

- external API p95 latency — dominated by provider-side variation this project does
  not control
- termination-reason distribution — the taxonomy showed 15 fail→fail reason changes
  between two runs of an identical configuration, so it is not yet stable enough to
  gate on. It is gated only after being characterised across the repeats.

---

## 4. Test-suite metric — fixed in advance

The distilled test-suite databases give a tighter metric. It is added **beside**
single-database execution accuracy, never replacing it.

- Both frozen P0 runs are rescored offline from persisted predicted SQL. **No model
  is re-run**, so the agent's behaviour is untouched and the two metrics describe
  exactly the same trajectories.
- Evaluator flags stay `plug_value=False`, `keep_distinct=False`: the agent predicts
  its own values, so plugging gold values in would measure a different system.
- Gold-pass QA is run on the test-suite substrate before any prediction is scored.
  If gold queries fail there, those tasks are excluded **from the test-suite metric
  only**, with a separate denominator. The single-database metric and its 1,034
  denominator are not touched.
- The 166-mutation adversarial QA is re-run on the test-suite substrate, and the
  collision rate is reported **before and after** so the tightening is quantified
  rather than asserted.

---

## 5. What this phase will not claim

- No confidence intervals from 4 repeats.
- No effect size from 1 OFF run.
- No pass^k claim beyond the repeat count actually run.
- No threshold presented as statistically calibrated; they are policy derived from
  a measured envelope, and the policy is stated above.
