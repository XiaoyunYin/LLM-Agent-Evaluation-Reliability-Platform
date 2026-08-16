# P2 Frozen — Intervention A Adopted

Every rule below was fixed before the treatment existed, and the cohort was
frozen before that. Nothing was chosen after seeing a result. Raw run output is
kept local; this report retains the measured comparison and its scope.

**Verdict: ADOPT.** All four pre-registered conditions hold.

---

## 1. What was measured, and why not global accuracy

The frozen cohort is **39 tasks** — the union of tasks that showed a *recoverable
failure* in at least one of five baseline runs: a failed episode that had already
executed a query passing the **test-suite** evaluator.

The primary metric is the cohort conversion rate, not global accuracy. 39 tasks is
3.8% of the benchmark, so even a total fix moves global accuracy ~3pp, inside twice
the P1 noise envelope. Judging this intervention globally would have returned
inconclusive whether or not it worked. That was stated in advance, not after.

---

## 2. Primary result

| | Cohort pass rate |
|---|---:|
| Baseline ON runs | 0.1026, 0.2051, 0.1795, 0.2821 |
| **Pooled baseline** | **0.1923** |
| Bridge control (same commit, treatment off) | 0.1282 |
| **Treatment runs** | **0.7436, 0.6923, 0.7179** |
| **Pooled treatment** | **0.7179** |
| **Absolute change** | **+0.5256** |
| Adoption bar (ON maximum) | 0.2821 |

Every treatment run clears the bar by a wide margin — the lowest treatment run
(0.6923) is 2.5× the highest baseline run.

### Paired cells

| | Tasks |
|---|---:|
| Converted | **29** |
| Regressed | **1** |
| Unchanged | 9 |
| **Net** | **+28** |

12 of the 29 converted tasks had **never** passed in any baseline ON run (0/4).
That matters: the P1 pre-registration warned that a 0/k label is not proof of
deterministic failure, and this is the direct demonstration — a third of the
conversions came from tasks a naive reading would have written off.

The single regression is `spider_dev_0606` (3/4 baseline → 1/3 treatment).

---

## 3. Damage channel — instrumented in advance, held

The intervention changes how an empty result is read, so the pre-registered
damage cohort is the **65 tasks** not in the frozen cohort whose baseline
trajectories contain a successful empty execution.

| | Rate |
|---|---:|
| Pooled baseline | 0.2462 |
| Treatment runs | 0.2154, 0.2308, 0.2308 |
| Pre-registered floor | 0.1846 |
| Breaches | **none** |

Premature empty-result submissions rose from **0** across all baseline runs to
**62** in each treatment run. That is the intervention working as designed — the
agent now submits on an empty result instead of looping — and the damage cohort
shows the cost of that is small and within the threshold set before the run.

---

## 4. No-regression guards — all held

| Gate | Threshold | Worst baseline | Treatment |
|---|---:|---:|---|
| Test-suite accuracy | 0.027079 | 0.63636 | 0.66248 / 0.66344 / 0.66538 |
| Model turns / success | 0.055692 | 4.59970 | 4.56058 / 4.57726 / 4.59448 |
| Tool validity rate | 0.001912 | 0.99596 | 0.99819 / 0.99579 / 0.99440 |
| Est. cost / success | $0.000080 | $0.00098 | $0.00087 × 3 |

Infrastructure clean on all three runs: 1,034 episodes, no `RATE_LIMITED` /
`MODEL_ERROR` / `TOOL_ERROR`, no duplicates.

---

## 5. Secondary effects

**MAX_STEPS collapsed: 44–52 baseline → 9–11 treatment.** The agents that used to
burn their whole budget re-running a query they had already got right now stop.

**Full-suite test-suite accuracy improved beyond the noise envelope**, which the
cohort-sized effect did not guarantee:

| | Accuracy |
|---|---:|
| Baseline ON range | 0.6364 – 0.6499 |
| Bridge control | 0.6412 |
| **Treatment range** | **0.6625 – 0.6654** |

The worst treatment run beats the best baseline run by **+1.26pp**, and the P1
same-commit spread is 1.35pp — so the improvement is comparable to, and at its
best exceeds, the full noise band. Reported as secondary because that is how it
was pre-registered, not because it is weak.

**Cost per success fell** from $0.00098 to $0.00087 — fewer wasted turns.

---

## 6. Bridge control — the commit did not move the baseline

Run on `p2-runner` with `empty_result_policy: baseline`.

| Check | Requirement | Observed | |
|---|---|---:|---|
| Accuracy in region | 0.6093 – 0.6770 | 0.6412 | pass |
| Discordance vs each P1 ON run | ≤ 44 | 30, 41, 41, 35 | pass |

Both conditions hold, so the P1 runs are valid controls and the treatment results
are interpretable. Had the bridge failed, the pre-registration required stopping to
investigate the commit rather than proceeding.

---

## 7. What is adopted, and what is not

**Adopted:** `empty_result_policy: accept_empty` — `execute_sql` labels
`EXECUTION_SUCCESS_NONEMPTY` / `EXECUTION_SUCCESS_EMPTY` / `EXECUTION_ERROR`, and
an empty successful execution carries guidance that it is not itself evidence of
wrong SQL. The guidance deliberately does not instruct the agent to submit;
correcting a false inference must not install the opposite one.

**Not built, recorded for later:**

- **Intervention B — `FOUND_PASSING_SUBMITTED_WORSE`.** 60 of 139 recoverable
  occurrences, dominant in 14 of the 39 cohort tasks. A correct query is executed
  and a different, wrong one submitted. That is candidate selection, not
  termination, and it needs its own isolated experiment.
- **Equivalent-query detection.** If pursued, equivalence is defined practically —
  persisted result-set identity first, normalized SQL text as fallback. No semantic
  SQL-equivalence claim will be made.

---

## 8. What P2 does not claim

- No confidence intervals. Three treatment repeats is a descriptive range.
- No claim that the remaining cohort failures are unfixable.
- The single regression (`spider_dev_0606`) is one task and is not evidence of a
  systematic harm.
- No semantic equivalence claim of any kind.

---

## Reproducing

```powershell
python scripts/analyze_recoverable_headroom.py --run spider_rpt__on_1 ... --run spider_abl__off_1
python scripts/freeze_p2_cohort.py
python scripts/run_spider_benchmark.py --stage full --run-id spider_p2__bridge_control \
    --concurrency 16 --empty-result-policy baseline
python scripts/run_spider_benchmark.py --stage full --run-id spider_p2__treat_1 \
    --concurrency 16 --empty-result-policy accept_empty
python scripts/analyze_p2_treatment.py
```
