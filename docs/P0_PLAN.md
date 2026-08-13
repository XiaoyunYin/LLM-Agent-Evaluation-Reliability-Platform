# P0 Plan — Execution-Verified SQL Agent Evaluation

## Goal

Transform the existing LLM/RAG evaluation platform into a minimal, execution-verifiable SQL agent evaluation platform while reusing the current runner, versioned datasets, model adapters, OpenTelemetry, metrics storage, dashboard, and CI plumbing.

P0 ends when the full benchmark produces reproducible trajectory-level measurements that are strong enough to replace the current RAG-first resume framing with measured agent-evaluation bullets.

---

## Scope Freeze

Build only:

- Spider dataset adapter
- isolated SQLite environments
- official Spider execution evaluator integration
- minimal LangGraph SQL agent
- `inspect_schema`
- `execute_sql`
- trajectory persistence
- OpenTelemetry spans
- staged benchmark runs
- P0 metrics
- verifier QA
- benchmark protocol documentation

Do not build in P0:

- ticket/file sandbox
- MCP server
- schema-repair experiment
- long-term memory
- multi-agent orchestration
- distributed agent execution
- step-level idempotency
- lease fencing
- crash recovery
- SIGKILL benchmark
- EKS
- additional retrieval tuning
- additional vLLM optimization

The vLLM-scheduler extension is parked while P0 is the active flagship build lane.

---

## P0 Target Architecture

```text
Spider task set
question + DB + gold SQL
        |
        v
Existing Eval Runner
run/task/version IDs
        |
        v
Minimal LangGraph Agent
        |
        +--> inspect_schema()
        |
        +--> execute_sql()
        |
        v
Episode-specific SQLite DB
        |
        v
Official Spider execution evaluator
        |
        v
PASS / FAIL

All model/tool/verifier steps emit OTel spans.
All agent steps are persisted as trajectories.
```

---

## Step 1 — Integrate Spider

- Pin the Spider benchmark version used by the project.
- Load:
  - development questions
  - database IDs
  - SQLite database paths
  - gold SQL
  - original task identifiers
  - split metadata
- Convert each example into the project's internal task format.

Suggested internal representation:

```python
SQLTask:
    task_id
    question
    database_id
    database_path
    gold_query
    split
    metadata
```

Do not mix train/dev splits when reporting the P0 benchmark.

---

## Step 2 — Build Isolated SQLite Environments

For each episode:

1. Identify the source Spider SQLite database.
2. Copy it to an episode-specific temporary path.
3. Open the agent connection as read-only.
4. Execute only against the temporary copy.
5. Clean up the episode database after completion.

Example:

```text
spider/database/foo/foo.sqlite
        |
        v
/tmp/episode_<episode_id>.sqlite
        |
        v
agent tools
```

Verify that mutation attempts such as `INSERT`, `UPDATE`, `DELETE`, `DROP`, and `ALTER` are rejected.

---

## Step 3 — Integrate and QA the Official Spider Evaluator

Use the established Spider execution/test-suite evaluator rather than implementing custom result-comparison semantics.

Before any LLM benchmark:

### Gold-pass QA

Run the gold SQL for every development example through the evaluator.

Expected behavior:

```text
gold SQL -> evaluator -> PASS
```

If a task fails:

1. Verify the integration first.
2. Confirm the correct DB and benchmark version are being used.
3. If the failure is genuine benchmark annotation/evaluator noise, record the task ID and reason in `LOCKED_INPUTS.md`.
4. Freeze the exclusion list before agent benchmarking.
5. Never silently skip examples or modify exclusions after seeing agent results.

### Known-bad QA

For representative tasks, create intentionally wrong SQL that must fail.

Example:

```text
gold: SELECT name FROM singer
bad:  SELECT age FROM singer
```

The bad query must not pass the evaluator.

---

## Step 4 — Create the Spider Adapter

Create a clean boundary between Spider and the evaluation runner.

Suggested structure:

```text
src/
└── datasets/
    └── spider/
        ├── loader.py
        ├── adapter.py
        └── environment.py
```

Responsibilities:

- dataset loading
- task normalization
- DB path resolution
- episode DB creation
- benchmark-version metadata
- exclusion-list application

The evaluation runner should consume the project's internal task abstraction rather than Spider-specific raw files.

---

## Step 5 — Implement `inspect_schema`

Build a tool that allows the agent to discover schema dynamically.

Suggested interface:

```python
inspect_schema(table_name: str | None = None)
```

Behavior:

### No table supplied

Return a concise table list.

### Table supplied

Return:

- column names
- column types
- primary-key information
- foreign-key relationships

Do not serialize the full database schema into the initial prompt.

The agent should decide what schema information it needs.

---

## Step 6 — Implement `execute_sql`

Suggested interface:

```python
execute_sql(query: str)
```

Requirements:

- read-only execution
- structured success/error response
- execution latency measurement
- full result persisted outside model context
- model-visible rows capped

Suggested model-visible response:

```python
{
    "columns": [...],
    "rows": [...],          # first ~20 rows only
    "row_count": 137,
    "error": None
}
```

If execution fails:

```python
{
    "columns": [],
    "rows": [],
    "row_count": 0,
    "error": "no such column: ..."
}
```

Store the complete result separately in the trajectory record.

Do not place hundreds of rows into the model context.

P0 records SQL execution errors but does not yet add the P2 bounded error-feedback retry experiment.

---

## Step 7 — Define Minimal Agent State

Keep state deliberately small.

Example:

```python
class AgentState(TypedDict):
    task_id: str
    question: str
    messages: list
    tool_calls: list
    step_index: int

    final_sql: str | None
    termination_reason: str | None

    input_tokens: int
    output_tokens: int
    estimated_cost: float
```

Add a simple step cap such as:

```text
max_steps = 10
```

Do not add:

- memory
- tenant state
- lease state
- fencing
- durable intent logging
- workflow orchestration fields

Those belong to later phases.

---

## Step 8 — Build the Minimal LangGraph Loop

The graph should remain simple:

```text
START
  |
  v
model
  |
  +--> tool call? -- yes --> tool --> model
  |
  no
  |
  v
finish
  |
  v
END
```

The model may choose:

- `inspect_schema`
- `execute_sql`
- finish

P0 should establish a genuine tool-using decision loop, not a fixed retrieve/generate sequence.

---

## Step 9 — Get One Task Working End-to-End

For one Spider task:

1. Load the task.
2. Create an isolated SQLite environment.
3. Start the LangGraph agent.
4. Allow schema inspection and SQL execution.
5. Capture every model/tool step.
6. Obtain the final SQL/result.
7. Run the official execution evaluator.
8. Produce a final PASS/FAIL result.
9. Clean up the episode environment.

Do not move to batch evaluation until one complete trajectory is correct and inspectable.

---

## Step 10 — Persist Complete Trajectories

Persist every agent step.

Suggested record:

```python
AgentStep:
    episode_id
    step_index
    step_type

    model_input_ref
    model_output_ref

    tool_name
    tool_args
    tool_result_ref

    input_tokens
    output_tokens
    latency_ms
    estimated_cost
```

Persist at the episode level:

```python
AgentEpisode:
    episode_id
    run_id
    task_id

    dataset_version
    model_version
    prompt_version
    tool_schema_version

    status
    final_sql
    verification_result
    termination_reason

    total_steps
    input_tokens
    output_tokens
    estimated_cost
    latency_ms
```

Large model inputs and SQL outputs should be stored outside span attributes and referenced by IDs.

---

## Step 11 — Add OpenTelemetry During Implementation

Instrument nodes as they are created.

Target trace:

```text
eval.run
└── agent.episode
    ├── agent.model_step
    ├── tool.inspect_schema
    ├── agent.model_step
    ├── tool.execute_sql
    │   └── sqlite.query
    ├── agent.model_step
    └── verifier.execution
```

Useful attributes:

```text
run.id
episode.id
task.id

dataset.name
dataset.version

model.name
prompt.version
tool_schema.version

agent.step_index

tool.name
tool.success

input_tokens
output_tokens

verification.success
termination.reason
```

Do not store large prompts or full SQL result sets directly as OTel attributes.

---

## Step 12 — Define P0 Termination Reasons

Keep the initial taxonomy small:

```text
SUCCESS
VERIFICATION_FAILED
SQL_ERROR
MAX_STEPS
MODEL_ERROR
TOOL_ERROR
NO_FINAL_SQL
```

P2 will later add:

```text
TOKEN_BUDGET
COST_BUDGET
TIMEOUT
```

and the bounded execution-error retry experiment.

---

## Step 13 — Run a 10-Task Smoke Test

Select a small set of straightforward tasks.

Verify:

- dataset loading
- DB isolation
- schema inspection
- SQL execution
- evaluator integration
- trajectory persistence
- OTel traces
- token accounting
- cost accounting
- termination handling

Do not optimize model performance yet.

Fix infrastructure correctness first.

---

## Step 14 — Run a ~50-Task Debugging Benchmark

Use a broader mix of tasks.

Look specifically for:

- schema-tool failures
- read-only enforcement problems
- malformed SQL-result serialization
- excessive model context caused by query results
- evaluator mismatches
- missing trajectory steps
- incorrect token/cost accounting
- trace/trajectory disagreement
- runner failures
- environment leakage

Resolve infrastructure issues before running the full suite.

---

## Step 15 — Run the Full Pinned Spider Dev Benchmark

Run the full valid dev set after applying only the frozen exclusions from `LOCKED_INPUTS.md`.

Version and persist the complete benchmark configuration:

```text
dataset
dataset version
valid task IDs
excluded task IDs + reasons

agent version
prompt version
tool-schema version
model version

max steps

code commit SHA
run ID
```

The benchmark should be reproducible from this configuration.

---

## Step 16 — Produce the P0 Metrics

### Primary metric

- task success / execution accuracy

```text
passed tasks / total valid tasks
```

### Agent efficiency

- mean steps per successful task
- median steps per successful task

### Tool behavior

- SQL execution-error rate
- schema inspections per episode
- SQL executions per episode

### Economics

- input tokens per successful task
- output tokens per successful task
- cost per successful task

### Failure breakdown

- verification failures
- SQL errors
- max-step terminations
- model failures
- tool failures
- missing-final-SQL failures

### Infrastructure correctness

- generation infrastructure failures
- tool infrastructure failures
- evaluator infrastructure failures
- missing trajectories
- missing traces

Do not create CI regression thresholds from a single P0 run.

P1 will measure run-to-run variance and determine statistically defensible gate thresholds.

---

## Step 17 — Document Benchmark Protocol

Add a short benchmark-protocol note stating:

- the agent discovers schema through tools;
- the full schema is not serialized into the initial prompt;
- this differs from the protocol used by many published Spider systems;
- therefore the project's absolute execution-accuracy number is an internal agent baseline, not a direct leaderboard comparison;
- future comparisons should primarily measure controlled deltas across:
  - prompt versions
  - model versions
  - tool-schema versions
  - agent-policy changes

---

## Step 18 — Verify P0 Completion

**Status: complete.** Frozen baseline run `spider_full__p0_v2`, verified by
`scripts/verify_p0_completion.py`: **25 passed, 0 failed, 0 unverified**.

Each criterion names the artifact that proves it. `R/` abbreviates
`runs/spider_benchmark/spider_full__p0_v2/`.

| # | Criterion | Evidence | Artifact |
|---|---|---|---|
| 1 | Spider dev tasks run through the evaluation runner | 1,034 episodes, `split=dev` | `R/episodes.jsonl`, `R/config.json` |
| 2 | Dataset and benchmark versions are pinned | `spider-1.0:dev:30d64a3fccde`; archive sha256 `5ddff97bb1d4…` | `datasets/spider/PIN.json`, `R/baseline_manifest.json` |
| 3 | A frozen verifier exclusion list exists if needed | 0 exclusions — every gold query passes | `docs/LOCKED_INPUTS.md` |
| 4 | Every episode uses an isolated SQLite database | live probe: separate copies ✓, one DB per episode dir ✓, cleaned up ✓ | `R/p0_completion.json` |
| 5 | Agent SQL access is read-only | guard blocked 5/5; SQLite `mode=ro` blocked 5/5 **with the guard bypassed** | `R/p0_completion.json` |
| 6 | `inspect_schema` works | 2,832 successful of 2,851 calls | `R/steps.jsonl` (`tool_name="inspect_schema"`) |
| 7 | `execute_sql` works | 1,363 successful of 1,379 calls | `R/steps.jsonl` (`tool_name="execute_sql"`) |
| 8 | SQL results shown to the model are capped | cap 20; 2,098 model-visible results checked, 0 over cap | `R/payloads.jsonl` (`kind="model_input"`) |
| 9 | Full SQL results are persisted separately | largest persisted result **20,662 rows** vs 20 shown — proves truncation happened | `R/payloads.jsonl` (`kind="tool_result"`) |
| 10 | The SUT is a LangGraph tool-using agent | compiled nodes `{model, tool, finish, max_steps}`; all 1,034 episodes made >1 tool call | `backend/app/spider/agent.py`, `R/episodes.jsonl` |
| 11 | SQL correctness uses execution-based verification | `spider-test-suite-sql-eval`, single-database execution accuracy, `plug_value=False`, `keep_distinct=False` | `R/episodes.jsonl` `verification_result`, `docs/P0_BASELINE.md` |
| 12 | Gold/reference QA passes for all non-excluded tasks | **1,034 / 1,034** | `runs/spider_verifier_qa/verifier_qa_dev.json` → `gold_pass` |
| 13 | Known-bad verifier QA fails as expected | **136 / 136** rejected, 0 leaks, 30 collisions recorded individually | `runs/spider_verifier_qa/verifier_qa_dev.json` → `known_bad` |
| 14 | Complete trajectories are persisted | 10,432 steps; 0 missing, 0 duplicate, 0 step-count disagreements | `R/steps.jsonl`, `R/episodes.jsonl` |
| 15 | Model/tool/verifier steps emit OTel spans | 10,432 / 10,432 steps carry a trace ID; 0 episodes without | `R/steps.jsonl` `trace_id` |
| 16 | Trace data matches persisted trajectory data | **exact on all 7 span types**, enumerated from the trajectory rather than hand-listed | ES query in `R/p0_metrics.json` → `trace_check.reconciliation` |
| 17 | The full benchmark completes without unexplained infrastructure failures | generation 0, tool 0, evaluator 0, gold 0, missing trajectories 0 | `R/p0_metrics.json` → `infrastructure_correctness` |
| 18 | Task success is measured | **758 / 1,034 = 73.31%** single-database execution accuracy | `R/p0_metrics.json` → `primary`, `R/claims_audit.json` |
| 19 | Steps per successful task are measured | **4.67 model turns**, 4.67 tool calls, 9.34 trajectory records (mean); medians 4.00 / 4.00 / 8.00 | `R/failure_analysis.json` → `step_decomposition` |
| 20 | SQL execution-error rate is measured | **16 / 1,379 = 1.16%** tool-call rate; separately, 2 `SQL_ERROR` episode terminations | `R/failure_analysis.json` → `tool_vs_episode_errors` |
| 21 | Token and cost metrics are measured | 3,782,629 in (478,848 cached) / 141,545 out; $0.616408 total, $0.000596/episode, $0.000813/success ($0.616408 / 758); **reconciles exactly** from persisted cached-token counts | `R/claims_audit.json` → `cost_algebra` |
| 22 | Failure categories are measured | all 7 reasons incl. zeros, summing exactly to 1,034 | `R/failure_analysis.json` → `termination_breakdown` |
| 23 | The exact benchmark configuration is saved | 10/10 required fields, plus prompt and tool-spec **content hashes** | `R/config.json`, `R/baseline_manifest.json`, `docs/P0_BASELINE.md` |
| 24 | The benchmark protocol limitation is documented | tool-discovered schema, not leaderboard-comparable, controlled deltas | `docs/benchmark-protocol.md` |
| 25 | Metrics are reproducible from the stored run | success rate and token totals recomputed from `episodes.jsonl` and matched; `audit_p0_claims` reports `all_reconciled: True` | `R/claims_audit.json` |

Reproduce every row:

```powershell
python scripts/report_spider_metrics.py --run-id spider_full__p0_v2 --check-traces
python scripts/analyze_spider_failures.py --run-id spider_full__p0_v2
python scripts/audit_p0_claims.py --run-id spider_full__p0_v2
python scripts/verify_p0_completion.py --run-id spider_full__p0_v2
python scripts/freeze_p0_baseline.py --run-id spider_full__p0_v2 --verify
```

Note on criterion 11: the run persisted the metric's pre-rename identifier
`execution_accuracy_original_db`. The metric is unchanged — same evaluator, same
flags, same semantics — and is now named `single_database_execution_accuracy`
everywhere. Frozen artifacts are immutable, so the verifier accepts the legacy ID
and says so.

Results: `docs/results/spider-p0.md`. Claim and scope: `docs/claims.md` §6.
Frozen inputs: `docs/P0_BASELINE.md`.

A superseded first run, `spider_full__p0_v1`, is retained. It measured 73.69%
under an identical configuration and is the basis for the run-to-run comparison in
`docs/results/spider-p0.md` §2.

---

## P0 Resume Update Rule

Update the resume only after Step 16 produces measured results.

P0 may support claims about:

- tool-using SQL-agent evaluation
- execution-based correctness
- trajectory-level measurement
- agent tool use
- OpenTelemetry trajectory tracing
- measured success/steps/cost/error rates

Do not claim yet:

- statistically calibrated regression gates
- pass^k consistency
- bounded SQL repair gains
- stateful ticket workflows
- typed tool-call repair
- MCP deployment
- durable per-step execution
- idempotent tool side effects
- lease fencing
- crash recovery
- SIGKILL benchmark results

Those belong to P1–P5.
