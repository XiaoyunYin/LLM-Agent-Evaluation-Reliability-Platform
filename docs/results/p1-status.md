# P1 Status — Measured, and Blocked

P1 was pre-registered in [`docs/P1_PREREGISTRATION.md`](../P1_PREREGISTRATION.md)
before any run executed. This records what has been measured and what is blocked,
without letting the second borrow credibility from the first.

**P2 headroom is now the stricter figure: 1.74pp** (18 of the 48 max-step episodes
ever produced a test-suite-passing query), superseding the single-database 2.42pp,
which is retained as historical diagnostic data only. 7 of the 25 queries the
looser metric called correct were themselves single-database false positives.

**Blocked:** everything requiring new agent runs — same-commit repeat variability,
the validation-OFF ablation, consistency metrics, and therefore CI thresholds.
**Cause:** OpenAI requests-per-day quota. See §4.

---

## 1. Test-suite substrate — measured

The distilled Spider test suite scores a query against **every** database instance
for its schema (695 instances across the 20 dev databases, 34.8 per `db_id`), not
just the one shipped copy.

### Substrate QA, run before any prediction was scored

| | Single-DB | Test-suite |
|---|---:|---:|
| Gold queries passing | 1,034 / 1,034 | **1,034 / 1,034** |
| Exclusions | 0 | **0** |
| Denominator | 1,034 | **1,034** |

Both substrates take the full 1,034-task denominator, so the two metrics are
directly comparable with no exclusion bookkeeping.

### Adversarial QA — same 166 mutations on both substrates

The mutation set is not regenerated per substrate. `scripts/compare_substrate_collisions.py`
reads the exact 166 task/mutation pairs frozen in the single-database QA and
re-runs those, so the comparison describes one population.

| | Single-DB | Test-suite |
|---|---:|---:|
| Mutations attempted | 166 | 166 |
| Detected as wrong | 136 | **146** |
| Execution-result collisions | 30 | **20** |
| Collision rate | 18.07% | **12.05%** |
| Leaks | 0 | 0 |

**Collision rate reduction: 6.02pp.** The test suite newly distinguishes **10 of
the 30** mutations that single-database scoring could not tell apart from gold.
Zero mutations became *less* distinguishable, which is the direction a strictly
tighter substrate must move.

The residual 12.05% is the honest limit: even 35 instances do not separate every
wrong query from gold.

**This rate describes the mutation set, not the agent.** For the agent's actual
false-positive rate, see §2 — and note the two numbers differ, which is exactly why
they must not be substituted for each other.

---

## 2. Both frozen P0 runs rescored — measured

**No model was re-run.** The agent's submitted SQL is persisted in
`episodes.jsonl`, so the second metric was computed over exactly the same
trajectories. Any difference is the metric, not the agent.

| Run | Single-DB | Test-suite | Gap |
|---|---:|---:|---:|
| `spider_full__p0_v2` (canonical baseline) | 758 / 1,034 = **73.31%** | 676 / 1,034 = **65.38%** | **7.93pp** |
| `spider_full__p0_v1` (repeat) | 762 / 1,034 = 73.69% | 673 / 1,034 = 65.09% | 8.61pp |

**The single-database metric's measured false-positive rate on this agent:**

| Run | Credited by single-DB, rejected by test-suite | As a share of single-DB passes |
|---|---:|---:|
| `p0_v2` | 82 | **10.82%** |
| `p0_v1` | 89 | 11.68% |

**`fail → pass` was 0 in both runs.** A strictly tighter substrate can only remove
passes, never add them, so a non-zero value here would have indicated a bug. It is
reported because a check that cannot fail proves nothing.

### The number that supersedes a caveat

Earlier documents said the 18.07% mutation collision rate "is not an estimate that
18% of the agent's passes are false positives." That was correct, and the real
figure is now measured: **10.82%**. The mutation rate over-stated it by ~7 points,
which is the size of error that hand-waving between the two would have introduced.

### Which metric to quote

**Stricter first, always paired:** "65.4% test-suite execution accuracy (73.3%
single-database)". The test-suite figure leads because it is the tighter and more
defensible one; leading with the looser number invites a reader to assume it is the
only one. The single-database figure stays attached because it is what the frozen
baseline was audited under and what the P0 artifacts recompute.

Neither replaces the other and neither is ever called by the other'''s name.
`docs/RESUME_COPY.md` carries the exact permitted wording.

---

## 3. Infrastructure fixed along the way

### The vendored evaluator's timeout does not work

`eval_exec_match` runs each query as `await asyncio.wait_for(exec_on_db_(...), 60)`,
but `exec_on_db_` calls a **blocking** `cursor.execute`. A coroutine that never
awaits cannot be cancelled, so the timeout only fires after the query has already
finished. It is inert for precisely the queries it exists to bound.

Measured consequence: a full test-suite gold-pass stalled on a single task for
**over 13 minutes, twice**, and lowering the documented timeout from 60s to 15s
changed nothing — because the timeout was never in control.

`backend/app/spider/interruptible_eval.py` drives execution with SQLite's
`set_progress_handler`, which interrupts inside the C loop and therefore works.
**Comparison semantics are unchanged**: `result_eq`, `remove_distinct`, and
`postprocess` are imported from the vendored source, so the pinned hashes still
describe the semantics in force.

Equivalence check: **120 of 120** verdicts identical to the vendored driver across
60 tasks × {gold, wrong} on the single-database substrate. Runtime for the full
gold-pass went from *indefinite* to **29.7 s**.

### Model failures were unattributable

`MODEL_ERROR` recorded the reason only on a span, so a run that failed 90 of 92
episodes could not be diagnosed from its own artifacts. The reason is now persisted
as a `model_error` payload and surfaced on the episode's `error` field. That fix is
what turned an opaque failure into the diagnosis in §4.

### Episode concurrency

Episodes are independent — own database copy, own conversation — so
`--concurrency N` changes wall time, not per-episode behaviour. Worker threads
start with an empty OpenTelemetry context, which would have made every episode span
a root and silently destroyed the trace tree; the run span's context is captured
once and re-attached inside each worker. Verified: a 12-task concurrent run
produced **1 trace** with all 7 span types reconciling exactly.

Recorded as a config field, defaulting to 1 so the sequential mode the P0 baseline
used is preserved.

---

## 4. Blocked: OpenAI requests-per-day quota

```
429 - Rate limit reached for gpt-4o-mini ... on requests per day (RPD):
      Limit 10000, Used 10000, Requested 1
```

**This is a hard external cap, not a code defect.**

The earlier "provider latency degradation" — a 5-token call taking 0.5s to 18s —
was the SDK silently retrying 429s with backoff. Concurrency then converted the
same 429s into 90 `MODEL_ERROR` episodes out of 92. Both symptoms had one cause.

### Why the budget does not fit

| | Requests |
|---|---:|
| One full 1,034-task run | ~5,200 model calls |
| Daily cap | 10,000 |
| **Full runs available per day** | **fewer than 2** |
| P1 needs (4 ON repeats + 1 OFF ablation) | ~26,000 |
| **Days required at the current cap** | **~3** |

Today's quota was consumed by the two P0 full runs (~10,431 model calls between
them) plus the staged smoke and debug runs.

### What this blocks

- Same-commit repeat variability (4 ON repeats)
- Consistency: per-task pass frequency, `pass^k`, flaky-task identification
- The validation-OFF ablation and its pre-registered verdict
- **CI thresholds**, which the pre-registration derives *from* the measured
  variance and from nothing else

### What was NOT done in response

No threshold was invented to fill the gap. `metrics/spider_gate_policy.json` carries
the full gate/monitor split with every threshold `null` and `armed: false`. A gate
with a made-up number is worse than no gate: it manufactures confidence in a check
that has never been calibrated.

The previous arbitrary policy (>5% eval score, >15% latency/cost) is marked
superseded in that file rather than left in place, because two P0 runs of an
identical recorded configuration already differed by 34 pass/fail flips — so a 5%
accuracy threshold was never anchored to anything observed.

### To resume

```powershell
# once quota resets; ~1.6 h per run at concurrency 12
python scripts/run_spider_benchmark.py --stage full --run-id spider_rpt__on_1 --concurrency 12
# ... on_2, on_3, on_4 ...
python scripts/run_spider_benchmark.py --stage full --run-id spider_abl__off_1 --concurrency 12 --disable-tool-validation

python scripts/analyze_run_variance.py --run spider_rpt__on_1 --run spider_rpt__on_2 \
                                       --run spider_rpt__on_3 --run spider_rpt__on_4
```

`analyze_run_variance.py` is built and produces the variance table, consistency
metrics, and threshold derivation. It has no measured input yet.

Concurrency is a configuration difference from the sequential P0 baseline. It
should not affect outcomes — episodes are independent — but that is an argument,
not a measurement, and the repeats will be internally consistent regardless since
all of them will use the same setting.

---

## 4b. P1 execution commit and pre-registration v2

Tag **`p1-runner`** (commit `89bb102`) is the execution commit. The P1 variance
family is defined as runs from that tag with an identical recorded configuration.
The canonical P0 run `spider_full__p0_v2` sits **outside** the family — different
commit, sequential execution, no `tool_argument_validation` field — and is a
diagnostic reference baseline only.

Runner hardening in that commit, verified to leave every behaviour-defining input
unchanged (prompt sha256, tool-spec sha256, versions, caps, and pricing all still
match the frozen manifest):

- `RATE_LIMITED` is a distinct termination reason, classified structurally, and is
  in both `INFRASTRUCTURE_TERMINATIONS` and a new `HALTING_TERMINATIONS`.
- 429s are never retried in benchmark mode; transient errors still are. The client
  is built with `max_retries=0` so the SDK cannot retry behind our back.
- Latency is split: `api_latency_ms` (provider) vs `retry_wait_ms` (our backoff).
  Latency metrics use the former, so rate-limit waiting cannot inflate it.
- The run halts on the first `RATE_LIMITED`, skips in-flight episodes rather than
  recording quota artefacts, and exits 75 with resume instructions.
- `tool_argument_validation: true|false` is a recorded config field, so the OFF
  ablation is a config change on the same commit rather than a code change.

Six regression tests pin this behaviour.

`docs/P1_PREREGISTRATION_V2.md` supersedes the v1 decision rules:

- **Primary metric is test-suite execution accuracy**; single-database is a
  diagnostic companion and never a gate.
- **`pass^k` estimator pinned**: `pass^k(task) = C(c,k)/C(n,k)`, averaged over
  tasks, reported for k = 1..4 with the per-task histogram. Validated on a
  synthetic family: `pass^1` equals mean accuracy and `pass^4` equals the 4/4
  share.
- **Ablation rule tightened**: an effect is reported only if OFF-vs-ON discordance
  exceeds the maximum ON-to-ON pairwise discordance against **every** family
  member, **and** PASS-to-FAIL strictly dominates in each comparison. Otherwise
  the published result is "inconclusive at one OFF run."
- **Cost gates are token-derived** from the pinned price snapshot travelling with
  the run, so provider repricing cannot retroactively change a CI verdict.

## 4c. Evaluator provenance — pinned

`runs/spider_verifier_qa/evaluator_provenance.json` records the vendored file
hashes, the local execution driver and why it exists, the 120/120 verdict parity,
gold-pass QA on both substrates (1,034/1,034 each, zero exclusions), the
adversarial before/after, and the timeout rule:

- per-query budget 15s, applied symmetrically to gold and prediction
- **prediction timeout → FAIL**
- **gold timeout → substrate exclusion**, because a task whose gold cannot run is a
  benchmark defect rather than an agent failure

The two metric ids stay permanently separate; neither is ever renamed to the other.

## 5. Gate / monitor split — defined, unarmed

Full policy in `metrics/spider_gate_policy.json`.

**Gate** (fails CI): task success, consistency `pass^k`, model turns per success,
tool validity rate, token-derived cost per success.

**Monitor** (reported, never fails): external API p95 latency — measured to range
0.5s–18s within one hour from provider-side causes, so gating on it would fail CI
for someone else's incident; termination-reason distribution — 49 reason changes
between two identical-configuration runs, 15 of them fail→fail, so it churns
without any outcome changing.

**Always fails regardless of threshold:** any non-zero infrastructure-failure
count, missing or duplicated trajectories, or a trace/trajectory mismatch. Those
are not tunable metrics.

---

## What P1 does not yet claim

- No variance estimate, confidence interval, or calibrated threshold.
- No `pass^k` value.
- No ablation effect size, and no verdict under the pre-registered rule.
- Nothing about the test-suite figure being "the" accuracy — it is reported beside
  the single-database figure, never instead of it.
