# P3 Calibration Changelog

Every change to a calibration task, fixture, verifier, or tool contract, with its
category and rationale. Categories are fixed in `docs/P3_CONTRACT_V0.md` §5.

**Poor model performance alone is never a valid category.** A task the agent fails
for a real reason is a measurement. Editing it because the score disappoints turns
the benchmark into a description of what the model already does.

| # | Date | Category | Target | Change | Rationale |
|---|---|---|---|---|---|
| 1 | 2026-08-13 | task/spec defect | `simple_update`, `lookup_update`, `policy_update`, `multi_field`, `multi_ticket`, `conditional_escalation` | Filter out tickets whose current value already equals the target when generating required changes | Verifier QA found two reference sequences failing. Root cause was not the verifier: two account-lockout tickets were already at priority `high`, so the required change produced no diff and the tasks were **unpassable regardless of agent behaviour**. Task count 35 → 33. |
| 2 | 2026-08-13 | verifier defect | `qa_support_verifier.py` | Isolation probe now picks a value that genuinely differs from the fixture's current one | Same root cause as #1. The probe set `TKT-0001` to a priority it already had, measured zero changes, and reported a false isolation failure. |
| 3 | 2026-08-13 | tool/runtime defect | `support_tools_v0` | Empty-result labelling moved from per-call-site to a single `apply_empty_result_policy`, and `call_tool` became the one runtime entry point | Twenty call sites are twenty chances for one tool to drift out of the contract. Also added `UNKNOWN_TOOL` handling, which had no defined payload before. |

## Rebalancing passes

One intentional difficulty/fairness rebalancing pass is permitted before the
freeze. **None used so far.**

| Pass | Date | Scope | Outcome |
|---|---|---|---|
| — | — | — | not yet run |
