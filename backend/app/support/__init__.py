"""P3: a stateful support-ticket environment with execution-verified mutations.

Where P0-P2 verified a *read*-only answer (did this SQL return gold's rows), P3
verifies *effects*: the agent changes the world, and correctness is whether the
world ended up in the declared state and nothing else moved.

- `schema`      - entities, enums, and the seeded fixture
- `environment` - per-episode isolated SQLite instance with snapshot/diff
- `normalize`   - deterministic normalization rules, versioned
- `verifier`    - declarative required / allowed / forbidden change checking
- `tools`       - the six typed tools the agent is given
- `tasks`       - parameterized task families and the frozen benchmark
"""
