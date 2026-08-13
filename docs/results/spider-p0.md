# Spider SQL-Agent Benchmark — P0 Results

**Canonical P0 baseline: run `spider_full__p0_v2`.** "The P0 baseline" means that
run ID and no other. `spider_full__p0_v1` is a **repeat run** retained only for the
run-to-run comparison in section 2; it is never the baseline.

Every number below is recomputed from `runs/spider_benchmark/spider_full__p0_v2/`
by `scripts/audit_p0_claims.py`, which reports MISMATCH if a published figure and
its artifact disagree.

**Read `docs/benchmark-protocol.md` before comparing this to anything.** The agent
discovers the schema through tools rather than receiving it in the prompt, so the
absolute figure is an internal agent baseline, not a Spider leaderboard result.

---

## 1. Benchmark facts

Measured. Each row has a definition, a denominator, and a source artifact.

### Configuration

| | |
|---|---|
| Run ID | `spider_full__p0_v2` |
| Dataset | Spider 1.0 dev, all 1,034 examples, 20 databases |
| Dataset version | `spider-1.0:dev:30d64a3fccde` |
| Archive sha256 | `5ddff97bb1d421282c593e8d30ce0ce107270f4dd4a21d60eba4bf287d5956b1` |
| Excluded tasks | **0** — every gold query passes the verifier |
| Model | `gpt-4o-mini`, temperature 0 |
| Prompt | `sql_agent_v1`, sha256 `8bb3c2b460bb130d…` |
| Tool schema | `spider_tools_v2`, spec sha256 `a0ca63507c9d1891…` |
| Agent | `spider_langgraph_agent_v1`, **`max_steps=10` = model-turn cap** |
| Metric | **single-database execution accuracy** (`plug_value=False`, `keep_distinct=False`) |
| Wall clock | 72.4 min, sequential |

Full pin including content hashes: [`docs/P0_BASELINE.md`](../P0_BASELINE.md).

### Primary result

**758 / 1,034 = 73.31%** single-database execution accuracy.

### Complete termination breakdown

Every P0 termination reason, including the zeros. The counts sum exactly to 1,034.

| Termination | Count | Share |
|---|---:|---:|
| `SUCCESS` | 758 | 73.31% |
| `VERIFICATION_FAILED` | 226 | 21.86% |
| `MAX_STEPS` | 48 | 4.64% |
| `SQL_ERROR` | 2 | 0.19% |
| `MODEL_ERROR` | 0 | 0.00% |
| `TOOL_ERROR` | 0 | 0.00% |
| `NO_FINAL_SQL` | 0 | 0.00% |
| **Total** | **1,034** | 100% |

Zero infrastructure failures: no model errors, no tool errors, no evaluator
errors, no missing or duplicated trajectories.

### Step metrics — three distinct quantities

The earlier figure "9.36 steps per successful task" was ambiguous: it counted
model turns *and* tool calls together. All three are now published separately.

| Quantity | Definition | Mean | Median | Range |
|---|---|---:|---:|---:|
| **Model turns** | One completed model API call. **This is what `max_steps` caps.** | 4.67 | 4.00 | 4–9 |
| **Tool calls** | One tool invocation (`inspect_schema`, `execute_sql`, `submit_answer`) | 4.67 | 4.00 | 4–9 |
| **Trajectory records** | Rows in `steps.jsonl` = model turns + tool calls | 9.34 | 8.00 | 8–18 |

Per successful task. Across all 1,034 episodes: 5.04 mean model turns, 10.09 mean
trajectory records. Totals: 5,216 model turns + 5,216 tool calls = 10,432
trajectory records; the identity holds for every episode.

Model turns equal tool calls because parallel tool calls are disabled and every
model turn in this run ended in exactly one tool call. 51 episodes reached the
10-turn cap.

The median successful episode is **4 model turns**: list tables → describe a table
→ test a query → submit.

### Tool behavior — tool-call denominator

| Tool | Calls | Failures | Failure rate |
|---|---:|---:|---:|
| `inspect_schema` | 2,851 | 19 | 0.67% |
| `execute_sql` | 1,379 | 16 | **1.16%** |
| `submit_answer` | 986 | 0 | 0% |

Per episode: 2.76 schema inspections, 1.33 SQL executions. **All 1,034 episodes
used both tools.**

### SQL errors: two different metrics, two different denominators

These must not appear in the same table, because they count different things:

| | Value | Denominator | Meaning |
|---|---:|---|---|
| `execute_sql` error rate | **16 / 1,379 = 1.16%** | tool calls | A single query failed to run. The agent sees the error and may fix it. |
| `SQL_ERROR` terminations | **2 / 1,034 = 0.19%** | episodes | The episode's *final submitted* query failed to run. |

The gap between them is recovery. **9 episodes** contained at least one failed
`execute_sql`; **3 of those still succeeded**. A tool-call failure is an event
inside an episode, not an episode outcome.

### Economics

Estimated from published list price, **not a billed invoice**. Cached-input
tokens are persisted, so the total is re-derivable rather than inferred.

| Metric | Value |
|---|---:|
| Total input tokens | 3,782,629 |
| — of which cached | 478,848 (12.7%) |
| Total output tokens | 141,545 |
| Input price / cached / output (USD per 1M) | 0.15 / 0.075 / 0.60 |
| Cost at full input price | $0.652321 |
| Cache discount | −$0.035914 |
| **Benchmark-only estimated cost** | **$0.616408** |
| Estimated cost per episode | $0.000596 |
| Estimated cost per **successful** episode | $0.000813 |
| Input / output tokens per successful task | 3,155 / 114 |

Reconciliation, checked by `scripts/audit_p0_claims.py`:

```
(3,782,629 − 478,848) × 0.15  +  478,848 × 0.075  +  141,545 × 0.60
──────────────────────────────────────────────────────────────────── = $0.616408  ✓
                            1,000,000
```

Cost per successful episode is **total benchmark cost divided by successes**
($0.616408 / 758), so it includes the spend on episodes that failed — those were
paid for too. The mean cost of an episode that happened to succeed is lower
($0.000526) and answers a different question; it is recorded in `claims_audit.json`
under a distinct name and is not published as cost per success.

The workload is prefill-dominated at **26.7 : 1** input to output.

### Total P0 spend

The benchmark run is not the whole bill. Full ledger in `claims_audit.json`:

| | Episodes | Input | Output | Est. cost |
|---|---:|---:|---:|---:|
| `spider_full__p0_v2` (frozen baseline) | 1,034 | 3,782,629 | 141,545 | $0.6164 |
| `spider_full__p0_v1` (superseded run) | 1,034 | 3,773,624 | 141,388 | $0.6168 |
| `spider_debug__step14` | 50 | 184,943 | 7,743 | $0.0304 |
| `spider_smoke__step13` (tools v1) | 10 | 48,178 | 1,419 | $0.0077 |
| `spider_smoke__step13_v2` (tools v2) | 10 | 38,106 | 1,596 | $0.0063 |
| `spider_single__step9` | 1 | 2,263 | 74 | $0.0004 |
| **Total real API spend** | **2,139** | **7,829,743** | **293,765** | **$1.2780** |
| Mock rehearsals (no spend) | 17 | 19,720 | 2,720 | $0.0046 |

### Observability

| Metric | Value |
|---|---:|
| Trajectory step records | 10,432 |
| Spans indexed in Elasticsearch | **13,832** |
| Largest full SQL result persisted | 20,662 rows |
| Largest result ever shown to the model | 20 rows (the cap) |
| Episode latency p50 / p95 | 3.77 s / 7.88 s |

**Why 13,832 spans against 10,432 trajectory records.** Four span types have no
corresponding step row, by design: `eval.run` (1) and `agent.episode` (1,034) are
scopes rather than steps; `sqlite.query` (1,379) is nested inside
`tool.execute_sql`; `verifier.execution` (986) runs after the agent graph
finishes. 10,432 + 1 + 1,034 + 1,379 + 986 = 13,832.

Every span type reconciles exactly against the trajectory:

| Span | Expected | Found |
|---|---:|---:|
| `agent.episode` | 1,034 | 1,034 |
| `agent.model_step` | 5,216 | 5,216 |
| `tool.inspect_schema` | 2,851 | 2,851 |
| `tool.execute_sql` | 1,379 | 1,379 |
| `tool.submit_answer` | 986 | 986 |
| `sqlite.query` | 1,379 | 1,379 |
| `verifier.execution` | 986 | 986 |

The reconciliation enumerates tool names **from the trajectory** rather than from
a hand-written list — see §3 for why that matters.

### Verifier QA, frozen before the run

| Check | Result |
|---|---|
| Gold queries passing the evaluator | **1,034 / 1,034** |
| Frozen exclusion list | **empty** |
| Mutations attempted | 166 |
| Detected as wrong | **136 / 136**, 0 leaks |
| Execution-result collisions (discarded) | **30** |
| Collision rate on attempted mutations | **18.07%** |

Re-running the QA reproduces this exactly — identical gold results and identical
mutation/task pairs. All 30 collisions are stored individually with task ID and
mutated query in `runs/spider_verifier_qa/verifier_qa_dev.json`.

### Success by database

| Hardest | n | success | | Easiest | n | success |
|---|---:|---:|---|---|---:|---:|
| `car_1` | 92 | 47.8% | | `poker_player` | 40 | 95.0% |
| `real_estate_properties` | 4 | 50.0% | | `voter_1` | 15 | 93.3% |
| `flight_2` | 80 | 57.5% | | `employee_hire_evaluation` | 38 | 92.1% |
| `student_transcripts_tracking` | 78 | 64.1% | | `museum_visit` | 18 | 88.9% |
| `world_1` | 120 | 66.7% | | `singer` | 30 | 86.7% |

---

## 2. Repeat run: two executions of an identical recorded configuration

`spider_full__p0_v1` and `spider_full__p0_v2` have **zero differing recorded
configuration fields** — same model, prompt hash, tool-spec hash, dataset,
temperature, `max_steps`, and task set.

Both runs recorded commit `ff9a4945` with a **dirty working tree**, and the changes
between them were observability-only (span placement, persisted fields) — provably
unable to alter agent behaviour, but they mean this is **not a same-commit
comparison**. It is two runs of an identical *recorded configuration* whose working
trees differed. A true same-commit repeat measurement is P1 (`docs/P1_PREREGISTRATION.md`).

| | v1 | v2 |
|---|---:|---:|
| Success | 762 / 1,034 = 73.69% | 758 / 1,034 = 73.31% |
| `VERIFICATION_FAILED` | 224 | 226 |
| `MAX_STEPS` | 48 | 48 |
| `SQL_ERROR` | 0 | 2 |

Aggregate moved **0.39 points**. The per-task ledger, joined on `task_id`:

| | Run B: PASS | Run B: FAIL |
|---|---:|---:|
| **Run A: PASS** | 743 | **19** |
| **Run A: FAIL** | **15** | 257 |

- PASS→FAIL: **19**
- FAIL→PASS: **15**
- **Total pass/fail flips: 34 (3.29% of tasks)**
- Net: 15 − 19 = −4 tasks = 758 − 762 ✓

A separate, larger quantity is **termination-reason churn: 49 changes**, of which
34 changed the outcome and **15 were fail→fail** (e.g. `VERIFICATION_FAILED` →
`MAX_STEPS`, 7 cases). An earlier version of this document published 49 as the
flip count. That was wrong: it counted reason changes, not outcome changes.

**Aggregate stability hides per-task churn.** A 0.4-point aggregate move sits on top
of 34 tasks changing answer and 49 termination reasons changing.

### Nondeterminism settings, recorded

| | Value |
|---|---|
| `temperature` | 0.0 |
| `top_p` | not sent — provider default applied |
| `seed` | **not sent** |
| Requested model alias | `gpt-4o-mini` |
| Resolved model revision | not captured for these runs; captured going forward |

Because no seed was sent, these are **repeated runs under an identical recorded
configuration** — not seeded runs, and not reproducible in the bitwise sense.

**This is n=2 and is not a variance estimate.** It cannot support a confidence
interval or a regression threshold. It is recorded because it is direct evidence
for why a threshold must not be set from a single run — that measurement is P1.

Ledger, identity checks, and the full config diff:
`comparison_vs_spider_full__p0_v1.json`, regenerated by
`scripts/compare_spider_runs.py`.

---

## 3. Debugging findings

Findings from the build, not headline results.

### A tool that answered the wrong question convincingly

`spider_tools_v1` of `inspect_schema` read only its `table_name` argument and
ignored anything else. The model calls `inspect_schema({"table": "course"})`, and
the tool returned the *table list* — a successful-looking response to a question
that was never asked. The agent could not detect the mismatch and re-requested
until its step budget ran out.

Controlled comparison, verified by diffing the two run configs — `tool_schema_version`
is the **only** differing field, across the same 10 task IDs (selected with a fixed
task-sampling seed), same model, prompt, temperature, and code commit:

| | `spider_smoke__step13` | `spider_smoke__step13_v2` |
|---|---:|---:|
| Tool schema | `spider_tools_v1` | `spider_tools_v2` |
| Success | 5 / 10 | 8 / 10 |
| `MAX_STEPS` | 3 | 0 |

**n=10. This is a debugging finding, not a quantitative claim.** Given that 34 of
1,034 tasks change pass/fail between two runs of an identical recorded
configuration, a 10-task comparison cannot separate the fix from sampling noise.
What it establishes is the *mechanism*, which the trajectories show directly; the
effect size is not established.

The mechanism persists at scale and is visible in the frozen run: the model still
sent `{"table": ...}` **19 times in 1,034 episodes**, and with validation in place
each one returned a corrective error naming `table_name` and the agent recovered.

### Empty result sets read as failure

Classification rules are applied by code and recorded in `failure_analysis.json`:

| Rule | Definition | Count |
|---|---|---:|
| `empty_result_loop_broad` | `MAX_STEPS` **and** ≥1 `execute_sql` returning `row_count == 0` with `error == None` | **39 / 48 (81.2%)** |
| `empty_result_loop_strict` | `MAX_STEPS` **and** ≥2 such calls | **36 / 48 (75.0%)** |
| `abandoned_a_correct_query` | `MAX_STEPS` **and** ≥1 executed query passes the evaluator against gold, established by re-running it | **25 / 48 (52.1%)** |

The third rule is the strongest: **25 max-step episodes executed a query that would
have passed, and did not submit it.** Measured by re-verification, not inspection.
All 25 task IDs are stored in `failure_analysis.json`.

As a share of the whole benchmark that is **2.42pp** (25 / 1,034). That figure is
**observed theoretical headroom, not recoverable accuracy**: no intervention has
been measured, and one that changed behaviour on these episodes would change it
elsewhere too.

Per-case classification of all 25:

| | |
|---|---:|
| Also in the empty-result cohort (exact overlap) | **23 of 25** |
| Passing query itself returned zero rows | **23 of 25** |
| Re-ran an equivalent query after already having a passing one | **17 of 25** |
| First passing query appeared at model turn | 3–6 (13 cases at turn 4) |
| Model turns still unused at that point | 4–7 |
| Spent the full 10-turn budget | **25 of 25** |
| Median distinct queries executed | 3 |

Only **2 of the 25** (`spider_dev_0043`, `spider_dev_0532`) sit outside the
empty-result cohort. The empty-result mechanism therefore accounts for 23 of 25,
which is what makes it the natural P2 intervention target — the remaining 16
empty-result episodes never produced a passing query at all, so a prompt change
addressing empty results would not obviously help them.

Representative trajectory, `spider_dev_0397` — *"Show the hometowns shared by at
least two teachers."* The agent executed:

```sql
SELECT Hometown FROM teacher GROUP BY Hometown HAVING COUNT(Teacher_ID) >= 2;
```

denotationally equivalent to gold. It returned 0 rows, because no hometown is
shared in that database. The agent read the empty result as evidence it was wrong
and cycled through eight variants — `COUNT(*)` vs `COUNT(Teacher_ID)`, `>= 2` vs
`> 1`, adding `IS NOT NULL` — never submitting.

**Not an infrastructure defect.** The tool response
(`{"rows": [], "row_count": 0, "error": null}`) is accurate and unambiguous. It is
a genuine agent failure mode, frozen as a P0 baseline finding and deliberately not
fixed: addressing it is a P1/P2 experiment requiring a controlled before/after.

Ceiling if every max-step episode converted: **77.95%**. A ceiling, not a forecast.

### Three observability defects found by auditing our own claims

All three were found by checking published numbers against artifacts, and all
three are fixed with regression tests:

1. **Span reconciliation checked only 4 hand-listed span types**, and the two it
   skipped were exactly the two with gaps. In the superseded v1 run, 23
   `inspect_schema` steps had no span (argument validation returned before the
   span opened) and all 986 `submit_answer` steps had none — **1,009 of 5,215 tool
   steps, 19%, invisible in traces**. The reconciliation now enumerates tool names
   from the trajectory, so a gap cannot hide in a span type nobody listed.
2. **Rejected tool calls persisted an empty payload.** `full_result` defaulted to
   `{}`, so the rejection reason was missing from the audit trail — 23 of 23 cases
   in v1.
3. **Elasticsearch capped the span count at exactly 10,000**, its default
   `track_total_hits` limit, and that capped value was published as if it were the
   total. The real v1 figure was 12,817.

---

## 4. Limitations

- **Not leaderboard-comparable.** Different protocol; see
  `docs/benchmark-protocol.md`.
- **Single-database execution accuracy**, not test-suite accuracy. The distilled
  multi-database test suite was not used. Measured blind spot: 30 of 166
  deliberately-wrong mutations (18.07%) return exactly gold's rows on the shipped
  database. **That rate describes this mutation set, not the agent** — it is not an
  estimate that 18% of the agent's passes are false positives, because the agent's
  queries are not drawn from that distribution.
- **Cost is estimated from list price**, not billed.
- **No variance estimate.** Two runs is not a sample. No confidence interval, no
  regression threshold, no pass^k.
- **One model, one prompt, one tool schema.** No full-scale A/B has been run.
- **Verification confirms the final answer, not the reasoning.** An agent that
  reaches a correct query by a wrong route still scores SUCCESS.

---

## 5. Future hypotheses (not results)

Unmeasured. Recorded so they are not mistaken for findings.

- Prompting the agent that an empty result may be correct might convert some of
  the 39 empty-result max-step episodes. Ceiling 77.95%; actual effect unknown.
- A larger `max_steps` might convert some max-step episodes, or might just spend
  more tokens on the same loops. `max_steps` is a measured input, so changing it
  produces a different configuration, not a better score on this one.
- Test-suite databases would tighten the metric's blind spot. Unquantified for
  this agent.

---

## Errata

Corrections made after the first freeze (commit `f4fe9a8`). No measurement was
re-run for any of these; all are recomputations or wording fixes over the same
artifacts.

| # | Was published | Corrected to | Cause |
|---|---|---|---|
| 1 | "49 of 1,034 tasks (4.7%) flipped outcome" | **34 tasks (3.29%)** changed pass/fail: 19 PASS→FAIL, 15 FAIL→PASS | The 49 counted *termination-reason* changes, which include 15 fail→fail changes that never altered the outcome. 49 remains correct as reason churn and is published under that name. |
| 2 | Cost per successful episode $0.000526 | **$0.000813** ($0.616408 / 758) | $0.000526 was the mean over successful episodes, silently excluding the spend on failures. The mean is retained in `claims_audit.json` under a distinct name. |
| 3 | "the same 10 seeded tasks" | "10 task IDs selected with a fixed **task-sampling** seed" | The seed governs task selection, not model sampling. No seed was ever sent to the model. |
| 4 | (absent) | Nondeterminism settings now recorded: `top_p` not sent, `seed` not sent, resolved model revision not captured | A repeat comparison is uncheckable without recording which sampling parameters were sent. Now captured going forward. |
| 5 | (absent) | Canonical baseline declared as `spider_full__p0_v2` | Two full runs existed with no stated precedence. |

The flip ledger is now generated by `scripts/compare_spider_runs.py`, which
asserts two identities the wrong number could not satisfy:
`PASS→FAIL + FAIL→PASS == total flips` and
`FAIL→PASS − PASS→FAIL == passes(B) − passes(A)`. It exits non-zero if either
fails.

---

## Reproducing

```powershell
python scripts/download_spider.py
python scripts/qa_spider_evaluator.py --split dev
python scripts/run_spider_benchmark.py --stage full --run-id spider_full__p0_v2
python scripts/report_spider_metrics.py --run-id spider_full__p0_v2 --check-traces
python scripts/analyze_spider_failures.py --run-id spider_full__p0_v2
python scripts/audit_p0_claims.py   --run-id spider_full__p0_v2
python scripts/verify_p0_completion.py --run-id spider_full__p0_v2
python scripts/freeze_p0_baseline.py --run-id spider_full__p0_v2 --verify
```

`verify_p0_completion` reports **25 passed, 0 failed, 0 unverified**.
`audit_p0_claims` reports **all_reconciled: True**.
`freeze_p0_baseline --verify` reports no drift in prompt text, tool spec, dataset,
evaluator source, or exclusions.

A regenerated run will not reproduce the success rate to the episode — see §2.
