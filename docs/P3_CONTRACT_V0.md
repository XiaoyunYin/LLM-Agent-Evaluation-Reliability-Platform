
# P3 Contract v0 — Calibration Stage

**This is not the frozen contract.** Everything below may still change during
calibration under the edit rules in §5. After the freeze, any agent-visible change
to this surface becomes an intervention requiring a bridge run.

Versions: tools `support_tools_v0` · schema `support_schema_v1` · normalization
`support_normalize_v1` · verifier `support_verifier_v1` · families
`support_tasks_v1` · agent `support_langgraph_agent_v0`.

---

## 1. Tool surface

| Tool | Kind | Required | Optional |
|---|---|---|---|
| `search_tickets` | read | — | `status`, `priority`, `customer_id`, `team_id`, `query` |
| `get_ticket` | read | `ticket_id` | — |
| `search_policy` | read | `query` | `topic` |
| `update_ticket` | **effectful** | `ticket_id` + ≥1 of below | `priority`, `status`, `escalated` |
| `assign_ticket` | **effectful** | `ticket_id` + ≥1 of below | `team_id`, `assignee_id` |
| `add_comment` | **effectful** | `ticket_id`, `body` | `reason_code`, `author` |

Read and effectful are separated in code (`READ_ONLY_TOOLS` / `EFFECTFUL_TOOLS`)
because P4 needs to identify state-changing calls individually.

### Enums, closed

- `priority`: `low`, `normal`, `high`, `urgent`
- `status`: `open`, `in_progress`, `waiting_customer`, `escalated`, `resolved`, `closed`
- `escalated`: boolean

An out-of-enum value is refused. An agent cannot invent a status and have it persist.

### Return shape

Reads return their payload plus `row_count`. Effectful calls return a confirmation
and the fields they changed. Every result carries `tool_schema_version` and, when
issued through the runtime, its `ToolCallIdentity`.

### Empty-result semantics — adopted, generalized

Adopted in P2 for one tool; applied uniformly here because the same ambiguity
exists on any read that can legitimately match nothing.

| Outcome | When |
|---|---|
| `SUCCESS_NONEMPTY` | success with results |
| `SUCCESS_EMPTY` | success, zero matches, **on `search_tickets` / `search_policy` only** |
| `ERROR` | any failure |

`SUCCESS_EMPTY` carries guidance that an empty result is a valid outcome, not
evidence the call was wrong. Effectful tools are excluded: "updated nothing" is a
failed update, not a successful empty read.

Applied in one place (`apply_empty_result_policy`) rather than at each call site —
twenty call sites are twenty chances for one tool to drift out of the contract.

**Default ON**, from `config/adopted_agent_flags.json`.

### Error payload format

```json
{"error_kind": "INVALID_ARGUMENTS", "field": "priority",
 "message": "'nope' is not a valid priority",
 "accepted_values": ["low", "normal", "high", "urgent"],
 "outcome": "ERROR"}
```

`error_kind` ∈ `INVALID_ARGUMENTS`, `NOT_FOUND`, `MALFORMED_ARGUMENTS`,
`UNKNOWN_TOOL`. The payload is **structured and machine-readable by design** —
that is what makes the planned schema-repair treatment "one bounded repair
attempt" rather than "add error messages", which would confound the two.

---

## 2. Call identity

Every tool call, read and effectful alike, carries:

```
ToolCallIdentity(episode_id, step_index, call_index)  →  "ep123:004:007"
```

Uniqueness is **asserted at allocation**, not assumed. A duplicated identity would
make a P4 intent log ambiguous about which call it describes — a defect invisible
until it matters. Reads are numbered too, so the sequence has no gaps.

---

## 3. Trajectory persistence

Per call: tool name and schema version, arguments as sent plus raw argument
string, validation result, returned payload or error, `error_kind`, effectful
flag, mutation descriptor, and the call identity.

Per episode: before-state reference, after-state reference, normalized diff,
model/token/cost metadata, and the final verifier result.

---

## 4. Model-turn budget — derived, not guessed

Measured from the 33 reference trajectories (`runs/support_reference_replay/`):

| | Tool calls |
|---|---:|
| min | 1 |
| median | 3 |
| **max** | **4** (`policy_update`) |
| mean | 2.39 |

Parallel tool calls are disabled, so one tool call costs one model turn, plus one
turn for `finish_task`. The longest legitimate reference therefore needs
**5 model turns**.

```
budget = 2 × 5 = 10 model turns
```

The 2× multiplier is a stated policy choice, giving an agent room to read before
acting and to recover from one mistake, without leaving space for the long
unproductive loops P2 measured.

**This is the calibration-stage budget.** It is recomputed on the final candidate
set after expansion to ~80 tasks and frozen with the benchmark. After the freeze a
budget change is an intervention requiring a bridge.

---

## 5. Calibration-edit rules

A calibration task, fixture, verifier, or tool-contract may change **only** for a
documented:

1. task/spec defect
2. verifier defect
3. tool/runtime defect
4. coherent ambiguity — the instruction admits more than one reasonable reading
5. fixture defect

**Poor model performance alone is not grounds for editing.** A task the agent
fails for a real reason is a measurement, not a bug. Editing it because the score
is disappointing converts the benchmark into a description of what the model
already does.

Every change is recorded in `docs/P3_CALIBRATION_CHANGELOG.md` with its category
and rationale. Exactly **one** intentional difficulty/fairness rebalancing pass is
permitted before the freeze.

---

## 6. Contaminated-run policy

Superseding the P2 practice of deleting contaminated runs: they are now
**quarantined, not deleted**. A contaminated run keeps its directory and gains a
`TOMBSTONE.json` recording the run ID, contamination reason, detection mechanism,
and exclusion status. Analysis tooling skips tombstoned runs.

Deleting hid the evidence of *how* the contamination happened. The P2 case — two
concurrent writers producing 1,008 duplicated task IDs — was worth keeping as a
record even though its data was worthless.
