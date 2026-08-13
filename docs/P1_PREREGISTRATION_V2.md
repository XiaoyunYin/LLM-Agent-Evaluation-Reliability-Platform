# P1 Pre-Registration v2 — Estimators and Decision Rules

Supersedes the decision rules in `docs/P1_PREREGISTRATION.md`. Written and
committed **before** any run in the P1 family executed, and after the test-suite
substrate made a stricter primary metric available.

Changes from v1: the primary metric is now test-suite execution accuracy; the
ablation rule is stated against the ON↔ON pairwise envelope rather than a
min/max range; the `pass^k` estimator is pinned explicitly.

---

## 1. The P1 variance family

**A run is in the family if and only if** it was executed from tag `p1-runner`
(commit `89bb102`) with:

| Field | Value |
|---|---|
| `prompt_version` | `sql_agent_v1` (sha256 `8bb3c2b460bb130d…`) |
| `tool_schema_version` | `spider_tools_v2` (spec sha256 `a0ca63507c9d1891…`) |
| `tool_argument_validation` | `true` for ON runs, `false` for the OFF ablation |
| `model_version` | `gpt-4o-mini` (resolved revision recorded per step) |
| `temperature` | `0.0` |
| `top_p` | not sent — provider default |
| `seed` | **not sent** |
| `max_steps` | `10` (model-turn cap) |
| Task set | Spider 1.0 dev, all 1,034, `spider-1.0:dev:30d64a3fccde` |

`spider_full__p0_v2` is **outside** the family — different commit, sequential
execution, and no `tool_argument_validation` field. It is a diagnostic reference
baseline and must never be used as a family member when deriving thresholds.

Family size is **4 ON runs**. Do not expand it unless a concrete defect requires
a replacement run, and say so if that happens.

---

## 2. Metrics

**Primary:** test-suite execution accuracy.
**Secondary, reported always:** single-database execution accuracy, PASS→FAIL and
FAIL→PASS, total paired churn, tool-contract rejection rate, model turns per
success, token-derived cost per success.

Single-database accuracy is a **diagnostic companion**, never the headline, and
never a gate.

---

## 3. `pass^k` — estimator pinned before any run

For a task passing `c` of `n = 4` ON runs, the probability that a randomly chosen
subset of `k` runs all pass it is:

```
pass^k(task) = C(c, k) / C(n, k)      and 0 when c < k
```

The benchmark figure is the **mean of the per-task values**:

```
pass^k = (1 / |tasks|) * sum over tasks of C(c_t, k) / C(n, k)
```

Report `pass^1`, `pass^2`, `pass^3`, `pass^4`. `pass^1` equals mean accuracy
across the family, which is a useful internal consistency check — if it does not,
the computation is wrong.

Also report the raw per-task consistency histogram: counts of tasks at 4/4, 3/4,
2/4, 1/4, 0/4.

This is an unbiased estimator over the runs actually performed. It is **not** an
extrapolation to unseen runs, and no confidence interval is attached to it.

---

## 4. Ablation decision rule — fixed in advance

Let the four ON runs give the 6 pairwise ON↔ON comparisons. For each pair record
total paired discordance `D = PASS→FAIL + FAIL→PASS`.

Let `D_ON_max = max` of those 6 values — the observed ceiling of same-configuration
churn.

Compare the OFF run against **each** of the 4 ON runs, giving `D_OFF,i` and the
directional split for each.

**A validation effect is reported only if both hold:**

1. `D_OFF,i > D_ON_max` for **every** i = 1..4. One ON run being unusually close
   to OFF is enough to withhold the claim.
2. The asymmetry runs the expected way: in each OFF-vs-ON comparison, PASS→FAIL
   (ON passes, OFF fails) **strictly exceeds** FAIL→PASS.

**Otherwise the published result is "inconclusive at one OFF run."**

Permitted responses to inconclusive: report it, or buy additional OFF repeats and
re-apply this same rule unchanged. Choosing a different statistic after seeing the
data is not permitted.

Additional standing conditions:

- **A single OFF run cannot establish an effect size.** Even when the rule fires,
  the reported quantity is a discordance comparison, not a calibrated effect.
- **Mechanism evidence is reported regardless of verdict**: the tool-contract
  rejection rate and the count of `inspect_schema` calls carrying an unknown
  argument, for ON and OFF. That mechanism is directly observable in trajectories
  and does not depend on the accuracy delta.
- **All 4 ON runs complete before the OFF run is analysed.** No stopping early on
  a favourable-looking result.

---

## 5. CI thresholds — derivation fixed in advance

Derived from the ON-family distribution on the **primary** metric, plus the
gate-candidate metrics.

For each gated metric, with `spread = max − min` across the 4 ON runs:

```
gate_threshold = max(2 × spread, minimum_detectable_change)
```

`minimum_detectable_change` is one task (1/1,034 = 0.097pp) for accuracy metrics,
so a degenerate zero-width threshold cannot arise if all four runs coincide.

The `2 ×` factor is a **stated policy choice**, not a statistical guarantee, and
must be described that way wherever a threshold appears.

### Gate candidates

- test-suite task success (primary)
- consistency: `pass^k`
- tool validity rate
- model turns per success
- token-derived cost per success

### Monitor only, initially

- external API wall-clock latency — provider-side and measured to vary 0.5s–18s
  within one hour
- termination-reason distribution — until its fail→fail churn is characterised
  across the family
- **single-database accuracy** — diagnostic companion to the primary metric

### Cost gates are token-derived

Computed from recorded input tokens, cached input tokens, output tokens, and the
**pinned price snapshot** in the run's manifest. Provider repricing must never
retroactively change a historical CI verdict, so the snapshot travels with the
run rather than being looked up at evaluation time.

---

## 6. What this phase will not claim

- No confidence interval from 4 repeats.
- No effect size from 1 OFF run.
- No `pass^k` beyond k = 4.
- No threshold described as statistically calibrated.
