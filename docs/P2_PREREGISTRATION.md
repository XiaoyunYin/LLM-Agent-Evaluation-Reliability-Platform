
# P2 Pre-Registration

Written and committed **before** the treatment exists and before any P2 run
executes. Every threshold below is derived from baseline data already frozen in
P1.

---

## 1. The frozen target cohort

`runs/spider_variance/p2_cohort_frozen.json` — **39 tasks**, the union of tasks
that showed a *recoverable failure* in at least one of the 5 baseline runs: a
failed episode that had already executed a query passing the **test-suite**
evaluator.

| | |
|---|---:|
| Cohort size | 39 tasks |
| Recoverable occurrences per run | 24–32 (mean 27.8 = **2.69pp** of 1,034) |
| `FOUND_PASSING_NEVER_SUBMITTED` occurrences | 79 |
| `FOUND_PASSING_SUBMITTED_WORSE` occurrences | 60 |
| Cohort tasks whose passing query was always empty | 26 / 39 |
| Tasks recurring in all 5 runs | 15 |
| Tasks appearing in only 1 run | 6 |

**The cohort is frozen and is not modified after treatment results appear.**

Baseline pass frequency across the 5 runs is recorded per task (0/5: 20 tasks,
1/5: 8, 2/5: 5, 3/5: 5, 4/5: 1). **These are descriptive labels only.** A 0/5 task
is not proven deterministically unsolvable — P1 measured 6.5% of tasks flipping
between identical runs, so five samples cannot establish determinism. Inference
rests on pooled paired behaviour, never on these labels.

---

## 2. Two intervention classes, separated

| | Class A | Class B |
|---|---|---|
| Subtype | `FOUND_PASSING_NEVER_SUBMITTED` | `FOUND_PASSING_SUBMITTED_WORSE` |
| Dominant in | 25 of 39 cohort tasks | 14 of 39 |
| Occurrences | 79 | 60 |
| Defect | termination / confidence handling | final-answer candidate selection |
| Status | **built now** | **recorded, deferred** |

Only Class A is implemented in P2. Class B is real and sizeable — 43% of
recoverable occurrences — but mixing two treatments into one experiment makes
neither attributable.

---

## 3. The treatment — Intervention A only

Tool outcomes become explicitly distinguishable to the agent:

- `EXECUTION_SUCCESS_NONEMPTY`
- `EXECUTION_SUCCESS_EMPTY`
- `EXECUTION_ERROR`

and the agent policy stops treating a successful *empty* execution as evidence
that the SQL is wrong.

Activated **only** through recorded configuration:

```
empty_result_policy: baseline | accept_empty
```

Control and treatment runs use the **same commit** (`p2-runner`). No code
difference separates them.

**Not in this experiment:** loop detection, equivalent-query detection, final-answer
selection. Each would confound the attribution.

---

## 4. Bridge control — acceptance rule, fixed in advance

One run on `p2-runner` with `empty_result_policy: baseline`, otherwise identical
to the P1 configuration. It exists to prove the new commit did not move the
baseline, so P1 runs remain valid controls.

The bridge is **compatible** only if both hold:

1. Bridge test-suite accuracy lies within the P1 ON range **0.6364 – 0.6499**,
   widened by the pre-registered accuracy threshold 0.0271 → acceptance region
   **0.6093 – 0.6770**.
2. Paired discordance against each of the 4 P1 ON runs is **≤ 44**, the observed
   ON-family maximum.

If the bridge falls outside either: **stop, investigate the commit, and do not
treat the P1 runs as controls.** Treatment results are not interpreted until the
bridge passes.

---

## 5. Primary metric

**`recoverable_cohort_conversion_rate`** — the share of frozen-cohort tasks that
pass under treatment, measured on the test-suite substrate.

Pooled baseline over the 4 ON runs: **0.1923** (30 passes of 156 task-run cells).
Per-run: 0.1026, 0.2051, 0.1795, 0.2821. **Observed spread 0.1795.**

That spread is enormous relative to the mean, because 39 tasks means one task
moves the rate by 2.56pp. **This metric cannot resolve small effects at this
sample size, and the decision rule is built around that rather than pretending
otherwise.**

Global full-suite accuracy is **secondary**. A 39-task cohort is 3.8% of the
benchmark, so even a total cohort fix moves global accuracy by at most ~3pp —
within twice the P1 noise envelope. Judging this intervention on global accuracy
would guarantee an inconclusive result regardless of whether it worked.

### Secondary metrics, within the cohort

failure→success conversion count · test-suite success rate · turns after the first
passing SQL · MAX_STEPS rate · equivalent/repeated-result rate · cost per
successful target task.

---

## 6. Adoption / iteration / drop — fixed in advance

**Treatment repeats: 3.**

Let `T_i` be the cohort pass rate of treatment run i, and `ON_max = 0.2821` the
maximum cohort pass rate observed across the 4 P1 ON runs.

**ADOPT** if all of:

1. `T_i > ON_max` for **every** treatment run i — the cohort rate clears the entire
   baseline envelope, not just its mean.
2. Pooled paired conversions strictly exceed pooled paired regressions across all
   cohort task-run cells.
3. **No-regression guards hold** (§7).
4. Non-target damage (§8) does not exceed its threshold.

**ITERATE** if the cohort improves — pooled conversions exceed regressions — but
condition 1 fails, or localized damage appears while the guards still hold. The
intervention is promising and under-powered or imprecise; refine it or buy more
repeats and re-apply this rule unchanged.

**DROP** if any of:

- pooled conversions do not exceed pooled regressions, or
- any full-suite gate in §7 is violated, or
- non-target damage exceeds its threshold.

Helping the cohort while violating a full-suite gate is **not** an acceptable
trade. It is a drop.

---

## 7. No-regression guards — the P1 gates stay live

From `metrics/spider_gate_policy.json`, armed against the P1 envelope:

| Metric | Threshold | Direction |
|---|---:|---|
| Test-suite accuracy | 0.027079 | decrease is bad |
| Model turns / success | 0.055692 | increase is bad |
| Tool validity rate | 0.001912 | decrease is bad |
| Est. cost / success | $0.000080 | increase is bad |

Plus the unconditional failures: any `RATE_LIMITED` / `MODEL_ERROR` / `TOOL_ERROR`
episode, evaluator or gold errors, missing or duplicated trajectories, a
trace/trajectory mismatch, or an episode count other than 1,034.

---

## 8. The damage channel, instrumented in advance

The intervention changes how an empty result is read, so the tasks it can damage
are those that saw an empty result and were **not** recoverable.

**Non-target empty-result cohort: 65 tasks** — not in the frozen cohort, but whose
baseline trajectories contain at least one successful empty SQL execution.
Task IDs are frozen alongside the cohort.

Baseline pass rate over the 4 ON runs: 0.2615, 0.2308, 0.2308, 0.2615 —
pooled **0.2462**, spread **0.0308**.

Measured under treatment:

- PASS → FAIL transitions within this cohort
- premature empty-result submissions: episodes submitting immediately after a
  first empty result with no further verification

**Damage threshold:** treatment is rejected if the non-target cohort pass rate
falls below `0.2462 − 2 × 0.0308 = 0.1846` in any treatment run.

This is the localized safety metric. It is far more sensitive than full-suite
accuracy, where 65 tasks are only 6.3% of the benchmark.

---

## 9. What P2 will not claim

- No confidence intervals. Three treatment repeats is a descriptive range.
- No claim that a 0/5 baseline task is unsolvable.
- No semantic SQL-equivalence claim. If equivalence detection is tested later it is
  defined practically: persisted result-set identity first, normalized SQL text as
  fallback.
- No combined attribution. Class B stays out of this experiment.
