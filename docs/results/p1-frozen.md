# P1 Frozen — Variance, Consistency, Ablation, and Calibrated Gates

Complete. Every decision rule and estimator was fixed in
[`docs/P1_PREREGISTRATION_V2.md`](../P1_PREREGISTRATION_V2.md) **before** any run
in this family executed.

**Primary metric: test-suite execution accuracy.** Single-database accuracy is a
diagnostic companion throughout and gates nothing.

---

## 1. The variance family

Five runs, all from tag `p1-runner`, commit `30595c2`, **clean working tree**,
identical recorded configuration, identical 1,034-task set. Verified
programmatically: `identical_recorded_configuration: true`,
`identical_task_set: true`, `same_commit_clean_tree: true`.

| Run | validation | test-suite | single-DB | model turns/success | tool validity | $/success |
|---|---|---:|---:|---:|---:|---:|
| `spider_rpt__on_1` | ON | 0.6431 | 0.7215 | 4.589 | 0.99599 | $0.000978 |
| `spider_rpt__on_2` | ON | 0.6460 | 0.7282 | 4.572 | 0.99596 | $0.000947 |
| `spider_rpt__on_3` | ON | 0.6364 | 0.7263 | 4.574 | 0.99616 | $0.000959 |
| `spider_rpt__on_4` | ON | 0.6499 | 0.7350 | 4.600 | 0.99692 | $0.000938 |
| `spider_abl__off_1` | **OFF** | 0.6470 | 0.7224 | — | 0.97776 | — |

All five completed 1,034/1,034 with **zero** infrastructure failures — no
`RATE_LIMITED`, `MODEL_ERROR`, or `TOOL_ERROR` episodes, no evaluator or gold
errors, no missing or duplicated trajectories. Roughly 5–6.5 minutes per run at
concurrency 16.

The canonical P0 run `spider_full__p0_v2` is **outside** this family — different
commit, sequential execution — and remains a diagnostic reference baseline.

---

## 2. Same-commit variance envelope

| Metric | min | max | spread |
|---|---:|---:|---:|
| **Test-suite accuracy** | 0.636364 | 0.649903 | **0.013540** |
| Model turns / success | 4.571856 | 4.599702 | 0.027846 |
| Trajectory records / success | 9.143713 | 9.199405 | 0.055692 |
| SQL execution-error rate | 0.005822 | 0.012382 | 0.006559 |
| Tool validity rate | 0.995964 | 0.996920 | 0.000956 |
| Est. cost / success | $0.000938 | $0.000978 | $0.000040 |

**Accuracy moves 1.35pp between runs where nothing changed.** That is the number
the old arbitrary 5% CI threshold should have been anchored to and never was.

### Pairwise churn across the 6 ON↔ON pairs

| | Value |
|---|---:|
| Pass/fail discordance per pair | 31, 31, 33, 40, 42, **44** |
| Mean | 36.8 |
| Mean termination-reason changes | 50.3 |

Roughly 13 reason changes per pair alter no outcome at all — which is why the
termination-reason distribution stays on the monitor side rather than gating.

---

## 3. Consistency — `pass^k`

Estimator pinned before any run: `pass^k(task) = C(c,k)/C(n,k)`, averaged over
tasks. The `pass^1 == mean accuracy` identity is asserted by the analyzer and
holds.

| k | pass^k |
|---:|---:|
| 1 | 0.6439 |
| 2 | 0.6260 |
| 3 | 0.6180 |
| **4** | **0.6132** |

Per-task consistency histogram over 1,034 tasks:

| Passes | Tasks | Share |
|---|---:|---:|
| 4/4 | **634** | 61.3% |
| 3/4 | 20 | 1.9% |
| 2/4 | 20 | 1.9% |
| 1/4 | 27 | 2.6% |
| 0/4 | **333** | 32.2% |

**67 tasks (6.5%) are flaky** — they pass sometimes and fail sometimes with an
identical configuration. Mean accuracy (0.6439) overstates reliable capability by
**3.07pp** relative to `pass^4` (0.6132): a task that passes once is not a task
the agent can do.

---

## 4. Validation-OFF ablation — INCONCLUSIVE

Applying the pre-registered rule, which required **both** conditions against
**every** ON member:

| OFF vs | PASS→FAIL | FAIL→PASS | discordance | > ON max (44)? | PASS→FAIL dominates? |
|---|---:|---:|---:|---|---|
| `on_1` | 15 | 19 | 34 | no | no |
| `on_2` | 19 | 20 | 39 | no | no |
| `on_3` | 12 | 23 | 35 | no | no |
| `on_4` | 19 | 16 | 35 | no | yes |

- Condition 1 (discordance exceeds the ON envelope against every member): **false**
- Condition 2 (PASS→FAIL strictly dominates in each comparison): **false**

**Verdict: inconclusive at one OFF run.** OFF test-suite accuracy (0.6470) lands
*inside* the ON range (0.6364–0.6499). No effect on accuracy is distinguishable
from same-configuration run-to-run variation.

### The mechanism is confirmed even though the accuracy effect is not

Reported regardless of verdict, as the pre-registration requires:

| | ON (4 runs) | OFF |
|---|---:|---:|
| Malformed tool calls | 16–21 | **117** |
| Tool validity rate | 0.99596–0.99692 | **0.97776** |
| MAX_STEPS terminations | 44–52 | **61** |

Turning validation off produces **~5.6x more malformed tool calls** and more
step-cap terminations. The agent visibly behaves worse. It just does not finish
with a worse score at n=1 OFF run, because the tasks it loses are largely tasks it
was going to fail anyway.

**This retires the 5/10 → 8/10 smoke result completely.** That was n=10 against a
noise floor now measured at 31–44 discordant tasks per pair. It was never an
effect size and is now known not to be one.

Honest reading: tool-argument validation is worth keeping because it makes the
agent's tool use measurably cleaner and its failure modes cheaper — not because
it has a demonstrated accuracy benefit. Establishing the latter would need
multiple OFF repeats, and the pre-registration permits buying them and re-applying
the same rule unchanged.

---

## 5. CI thresholds — derived, armed

`max(2 × observed spread, minimum detectable change)`, the formula fixed before
any of these runs existed. Full policy in `metrics/spider_gate_policy.json`.

### Gate — fails CI

| Metric | Spread | **Threshold** |
|---|---:|---:|
| Test-suite task success | 0.013540 | **0.027079** |
| Model turns / success | 0.027846 | **0.055692** |
| Tool validity rate | 0.000956 | **0.001912** |
| Est. cost / success | $0.000040 | **$0.000080** |

`pass^4` is a gate *candidate*, unarmed: it needs k repeats per side, so it is a
release gate rather than a per-commit one.

**The tool-validity gate would catch the ablation.** OFF measured 0.97776 against
an ON floor of 0.99596 — a move of 0.0182, roughly **9.5x** its 0.001912
threshold. The gate detects the regression that the accuracy metric could not,
which is the argument for gating behaviour and not only outcomes.

### Monitor — reported, never fails

Single-database accuracy (diagnostic companion; 10.8% false-positive rate),
external API p95 latency (provider-side; measured 0.5s–18s in one hour),
termination-reason distribution (still churning ~13 no-op changes per pair), and
SQL execution-error rate (spread is half its own mean).

### Cost gates are token-derived

From recorded input, cached-input, and output tokens against the price snapshot
stored in each run's manifest. Provider repricing cannot retroactively change a
historical CI verdict.

---

## 6. Superseded

| Was | Now |
|---|---|
| CI: >5% eval score, >15% latency/cost, chosen by judgement | Test-suite accuracy >0.0271, derived from a measured 1.35pp envelope |
| "5/10 → 8/10 from tool validation" | Inconclusive at one OFF run; mechanism confirmed, accuracy effect not |
| Single-database accuracy as the headline | Test-suite accuracy primary; single-DB is a diagnostic companion |
| P2 headroom 2.42pp | 1.74pp under test-suite scoring |

## 7. What P1 still does not claim

- No confidence intervals. Four repeats is a descriptive range.
- No ablation effect size. One OFF run cannot produce one.
- No `pass^k` beyond k = 4.
- Thresholds are a stated policy choice over a measured envelope, not a
  statistical guarantee.

---

## Reproducing

```powershell
python scripts/run_p1_family.py --concurrency 16
python scripts/analyze_run_variance.py --run spider_rpt__on_1 --run spider_rpt__on_2 \
    --run spider_rpt__on_3 --run spider_rpt__on_4 --substrate test_suite
python scripts/compare_spider_runs.py --run-a spider_rpt__on_1 --run-b spider_abl__off_1 \
    --substrate test_suite
```
