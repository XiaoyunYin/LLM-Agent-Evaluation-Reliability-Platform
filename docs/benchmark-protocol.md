# Spider SQL-Agent Benchmark Protocol

What this benchmark measures, what it deliberately does not measure, and why its
absolute number should not be compared to a published Spider leaderboard.

## The protocol

Each episode:

1. One Spider dev question and its database ID enter the agent. **The schema does
   not.**
2. The agent gets an isolated, read-only copy of that SQLite database and three
   tools: `inspect_schema`, `execute_sql`, `submit_answer`.
3. The agent decides for itself whether to list tables, describe a table, test a
   query, or submit. It has a budget of 10 model turns.
4. The submitted SQL is verified by execution against gold SQL, using the
   vendored official Spider evaluator.
5. Every model step, tool call, and verification is persisted as a trajectory
   record and emitted as an OpenTelemetry span.

## Why the result is not leaderboard-comparable

**The agent discovers the schema through tools. The full schema is never
serialized into the initial prompt.**

Most published Spider systems are given the complete schema up front - every
table, every column, often with sample rows and foreign-key hints - and are asked
to emit SQL in a single generation. That is a text-to-SQL task.

This is a different task. The agent must work out what it needs to know and go
get it, which means:

- it can fail by never finding the right table;
- it can spend its step budget exploring instead of answering;
- it can succeed on a question a single-shot system would fail, by testing a query
  and seeing the result before committing.

So the absolute execution-accuracy figure here is **an internal agent baseline,
not a leaderboard result**. Reporting it beside published Spider numbers would be
comparing two different tasks that happen to share a dataset.

## What the number *is* good for

Controlled deltas. The protocol is fixed and versioned, so a change to any one of
these is measurable against a prior run:

| Dimension | Version field | Where it is recorded |
|---|---|---|
| Prompt wording | `prompt_version` | every episode + run config |
| Model | `model_version` | every episode + run config |
| Tool names, arguments, response shape | `tool_schema_version` | every episode + run config |
| Task normalization | `adapter_version` | run config |
| Agent graph and policy | `agent_version` | run config |
| Dataset | `dataset_version` (benchmark + split + `dev.json` sha256) | run config |

A regression comparison is only meaningful when exactly one of those moves.

A regression comparison also needs to clear the noise floor. Two runs under an
identical recorded configuration measured 73.69% and 73.31% — 0.39 points apart in
aggregate, but with **34 of 1,034 tasks (3.29%) changing pass/fail outcome** (19
PASS→FAIL, 15 FAIL→PASS). A controlled delta smaller than that is not resolvable by
a single pair of runs.

Those two runs differed by observability-only working-tree changes, so they bound
the noise floor only approximately. Same-commit repeats from a clean tree are P1.

No seed was sent to the model, so these are repeated runs under an identical
recorded configuration, not seeded runs.

Worked example from this project's own history: fixing tool-argument validation
was a `tool_schema_version` change from `spider_tools_v1` to `spider_tools_v2`,
and on the same 10 task IDs (selected with a fixed *task-sampling* seed) with
everything else held constant it moved success from 5/10 to 8/10. That is the
*shape* of comparison this benchmark supports — but at n=10, against a 34-task
noise floor, it establishes the mechanism and not the effect size.

## Step accounting

Three quantities, never conflated:

| Quantity | Definition |
|---|---|
| **Model turns** | One completed model API call. **`max_steps` caps this.** |
| **Tool calls** | One tool invocation: `inspect_schema`, `execute_sql`, or `submit_answer`. |
| **Trajectory records** | Rows in `steps.jsonl` = model turns + tool calls. |

`max_steps = 10` is a **model-turn cap**. Tool calls do not count against it,
because the budget that matters is how many times the agent gets to think, and
counting tools would make the cap depend on how chatty the tool schema is.

## Verification semantics

`eval_exec_match` from `taoyds/test-suite-sql-eval`, with the official
execution-accuracy defaults `plug_value=False`, `keep_distinct=False`.

The metric's name is **single-database execution accuracy**. It is never called
test-suite accuracy.

It compares denotations, handling row order (significant only when the gold query
has `ORDER BY`), duplicate rows under bag semantics, and column permutation. This
is why `SELECT COUNT(*) AS number_of_singers FROM singer;` is correctly credited
against gold `SELECT count(*) FROM singer`.

**This is single-database execution accuracy, not test-suite accuracy.**
Test-suite accuracy requires the separately distributed distilled databases, which
run the same query pair against many database instances to catch queries that
agree with gold by coincidence on one instance. Single-database execution accuracy
can credit a wrong query that happens to match on the one shipped database.

That limit is measured, not hypothetical. In verifier QA, **30 of 166**
deliberately-wrong mutations returned exactly gold's rows on the shipped database
and were discarded as denotationally equivalent rather than counted as verifier
leaks — a **18.07%** collision rate. Every one is recorded with its task ID and
mutated query.

**That rate describes this mutation set, not the agent.** It is *not* an estimate
that 18% of the agent's passes are false positives: the agent's queries are not
drawn from the mutation distribution.

## Verifier QA, frozen before any agent ran

- **Gold-pass:** all 1,034 dev gold queries verified as predictions. 1,034/1,034
  pass, so the frozen exclusion list in `docs/LOCKED_INPUTS.md` is empty and
  accuracy is measured over the full dev split.
- **Known-bad:** 136 deliberately wrong queries, each first proven to return
  different rows from gold. 136/136 correctly rejected, 0 leaks.

Gold-pass alone would not prove anything: a verifier hardcoded to return PASS also
scores 100% on gold. The known-bad half is what makes the QA meaningful.

## Isolation and read-only enforcement

Two independent layers, because either alone has a hole:

1. Every episode runs against its own copy of the database in its own directory,
   discarded at the end. A write that escaped would hit a throwaway file.
2. The agent connection is opened with SQLite URI `mode=ro`, so writes are
   rejected by SQLite itself. A statement guard sits in front of it to produce
   clean, model-readable errors and to block multi-statement payloads and
   `ATTACH`, which `mode=ro` does not stop.

The guard is never the only layer. String-matching SQL is defeatable, so it must
not be the thing standing between an agent and the pinned dataset.

## Cost figures

Every cost in these reports is **estimated from published list price** and
labelled as such. It is not a billed invoice amount. Cached-input pricing is
applied when the API reports cached prompt tokens.

## What P0 does not establish

Per the plan, and not to be claimed from a single run:

- statistically calibrated regression-gate thresholds (needs P1 run-to-run variance)
- pass^k consistency
- bounded SQL-repair gains
- anything about stateful workflows, MCP, durable execution, or crash recovery

## Reproducing a run

Every run writes `config.json` carrying the dataset sha256, all version fields,
the selected task IDs, the frozen exclusion list, the sampling seed, and the code
commit SHA. A run is reproducible from that file alone:

```powershell
python scripts/download_spider.py
python scripts/qa_spider_evaluator.py --split dev
python scripts/run_spider_benchmark.py --stage full
python scripts/report_spider_metrics.py --run-id <run_id> --check-traces
```
