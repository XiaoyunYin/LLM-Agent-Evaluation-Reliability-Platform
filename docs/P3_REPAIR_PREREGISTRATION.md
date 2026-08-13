
# P3 Schema-Repair Experiment — Pre-Registration

Written **before** the frozen baseline results were read. Every threshold,
estimator, cohort rule and verdict below is fixed here so that no choice in the
analysis can be made after seeing which choice would look better.

---

## 1. Why this intervention, and not another

The selection rule was fixed in `docs/P3_SUITE_COMPOSITION.md` §9: schema repair
is selected if invalid typed calls are **≥2% of tool calls**, or **≥15% of
episodes contain one**. Measured over the 3 post-fix calibration repeats:

| Signal | Measured | Threshold | Clears |
|---|---:|---|:--:|
| invalid typed calls | 49/930 = **5.27%** | ≥2% | yes |
| episodes with ≥1 invalid call | 49/180 = **27.2%** | ≥15% | yes |

Both clear, so the rule selects schema repair. Had it not, "schema repair not
selected" would have been recorded as the result — manufacturing malformed-call
tasks to justify a pre-planned intervention is explicitly forbidden.

## 2. What the treatment is

A config flag on one commit, `SupportAgentConfig.schema_repair_enabled`, default
`False`. Nothing else differs between arms; `scripts/assert_p3_frozen.py`
deliberately excludes this one field and asserts every other pin is identical, so
the comparison is paired by construction.

When a tool call fails argument validation and repair is **ON**, the error payload
additionally carries the tool's full JSON argument schema and one concrete valid
example call. When repair is **OFF**, the agent gets today's message, which names
the offending field and the accepted argument names but not the schema.

**The treatment changes only what the agent is told after it errs.** It does not
coerce arguments, does not retry on the agent's behalf, and cannot convert an
invalid call into a successful one. Auto-coercion was rejected: silently fixing a
malformed call is the same class of defect as
[SILENT_TOOL_FAILURE](SILENT_TOOL_FAILURE.md) — it makes a wrong call look right.

## 3. Repair accounting — no hidden or free retries

Pinned before running:

| Item | Rule |
|---|---|
| The repair turn | Counts against `max_steps`, exactly like any other turn |
| Repair tokens | Counted in `input_tokens` / `output_tokens` and in cost |
| The failed call | Still counted as an invalid typed call in both arms |
| Extra attempts | None. Repair grants no additional budget of any kind |

If the treatment wins by spending more turns or more money, the accounting will
show it, which is the point of pinning it now.

## 4. Primary metric

Task success is **saturated at ~97%** on this suite, so it cannot be the primary
metric — there is no headroom for an intervention to move, and a metric that
cannot move is not a test.

Also excluded: the *first* invalid call in an episode. Repair by definition acts
only after a call has already failed, so it cannot reduce first-offence rate, and
reporting it as the primary metric would guarantee a null result for structural
reasons rather than empirical ones.

> **Primary metric: repeat-invalid rate.**
> Over the frozen cohort, the fraction of invalid typed calls that are *not* the
> first invalid call in their episode:
>
> ```
> repeat_invalid_rate = (invalid_calls - episodes_with_at_least_one_invalid)
>                        / invalid_calls
> ```
>
> This measures exactly what the treatment can affect: whether an agent that has
> been told what it got wrong stops getting it wrong.

Estimator: pooled across all runs in an arm. Uncertainty: the run-level spread
(min–max and sd across repeats), not a within-run interval, because runs are the
unit of independent repetition.

## 5. Secondary metrics

| Metric | Direction |
|---|---|
| model turns per episode, cohort | lower is better |
| cost per episode, cohort | lower is better |
| turns from first invalid call to the next valid call to that tool | lower is better |
| task success, cohort and global | **guardrail** — must not regress |

## 6. Cohort, frozen before treatment

The cohort is the set of tasks that produced **≥1 invalid typed call in ≥3 of the
10 baseline runs**. Frozen to a file, with its task ids and the baseline counts,
**before any treatment run executes**.

Rationale for ≥3 rather than ≥1: a task that provoked one malformed call once is
noise, and a cohort defined by a single occurrence would be substantially composed
of tasks that will not provoke one again — regression to the mean would then
appear as a treatment effect.

If fewer than 8 tasks qualify, the experiment is reported as
**underpowered and inconclusive** rather than run to a number.

## 7. Bridge run — acceptance rule, fixed now

Before treatment, one bridge run at the treatment commit with the flag **OFF**.
Its purpose is to prove that the commit itself changed nothing.

> **Accept the bridge if** its cohort repeat-invalid rate and global task success
> both fall within the min–max range of the 10 frozen baseline runs.
>
> If it falls outside, the commit is not inert. Stop, find out why, and do not run
> the treatment.

## 8. Repeats

10 baseline (OFF) runs, 1 bridge (OFF), and **4 treatment (ON) runs**. Analysis is
paired at the task level over the frozen cohort.

## 9. Verdict rule, fixed before any treatment run

Let Δ = baseline repeat-invalid rate − treatment repeat-invalid rate (positive
means repair helped).

| Condition | Verdict |
|---|---|
| Δ ≥ 0.10, treatment range does not overlap baseline range, **and** task success does not regress beyond the baseline min | **ADOPT** — carry into P4 defaults, write to `config/adopted_agent_flags.json` |
| Δ ≥ 0.10 but the ranges overlap | **INCONCLUSIVE** — report the overlap and the run counts. Buy more repeats or report as inconclusive. Do not present a mean difference as an effect when the ranges overlap. |
| \|Δ\| < 0.10 | **NO EFFECT** — report as a null result and keep the flag off |
| Δ ≤ −0.10 | **HARMFUL** — report and keep off |
| Any arm regresses task success below the baseline minimum | **REJECT** regardless of Δ |

A null result is a legitimate and publishable outcome. The P1 validation ablation
was reported inconclusive at one OFF run rather than being written up as an
effect, and the same standard applies here.

## 10. Contamination handling

Any run that fails `scripts/assert_p3_frozen.py`, contains duplicate task ids, or
does not cover the frozen suite exactly once is **quarantined, not deleted**: a
tombstone records the run id, the contamination reason, the detection mechanism,
and its exclusion status. `analyze_p3_baseline.py` excludes such runs loudly
rather than silently.
