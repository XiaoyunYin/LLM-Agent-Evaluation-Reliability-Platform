"""Spider SQL-agent evaluation (P0).

Boundary between the Spider benchmark and the evaluation runner:

- `loader`      - reads pinned Spider files into `SQLTask`
- `adapter`     - normalizes `SQLTask` into the platform's `EvalCase`, applies exclusions
- `environment` - per-episode isolated SQLite copies, opened read-only
- `tools`       - `inspect_schema` and `execute_sql`, the agent's only DB access
- `evaluator`   - execution-based verification via the vendored official evaluator
- `agent`       - the minimal LangGraph tool-using SQL agent
- `trajectory`  - persisted `AgentStep` / `AgentEpisode` records
"""
