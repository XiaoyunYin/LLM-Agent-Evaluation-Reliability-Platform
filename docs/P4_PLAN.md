# P4 Plan

P4 has not started. This document is the protocol design and acceptance contract
that must exist before any P4 implementation or fault-injection measurement.

P4 is split into two claims:

- P4a proves crash-safe, idempotent, fenced agent effects in a Python-native
  substrate independent of Java.
- P4b proves the same guarantees survive integration with the real Java
  orchestration platform.

P4a is the correctness source of truth. P4b must not introduce a second
idempotency or fencing model.

## State Ownership

Runner/orchestration store owns:

- episode state
- lease owner and lease fencing token
- model-step state
- durable intent
- completed step and result reference
- consumed model turns, tokens, cost, tool-call count and retry count
- DLQ state

Sandbox/effect store owns atomically:

- the actual business mutation
- the idempotency record
- the effect result produced by that mutation
- fencing-token validation

The runner store must not persist a state called `EFFECT_EXECUTED`. Whether an
effect happened is derived from the sandbox/effect store's idempotency/result
record.

## Identities

The logical call identity is:

```text
episode_id
step_index
call_index
```

The runner intent table and the effect-store idempotency table both enforce a
unique constraint on that identity.

On intent insert conflict:

- read the existing intent
- verify the requested tool name, tool version and canonical arguments match the
  persisted winner
- replay the persisted winner
- never invent a second logical call for the same identity

## Runner State Machine

Runner-side state:

```text
READY
  -> MODEL_DECISION
  -> INTENT_WRITTEN
  -> result lookup / effect invocation
  -> STEP_COMPLETED
```

`INTENT_WRITTEN` is the serialization point for a logical tool call.

Decision immutability:

- Crash before durable intent: the model may be invoked again.
- Crash after durable intent: the model must never be consulted again for that
  logical call.

Once an intent exists, recovery replays the persisted tool name and canonical
arguments.

## Effect Transaction

Effect-store state:

```text
no record
  -> transaction:
       validate fencing token
       check idempotency key
       if already present, return stored result
       apply business mutation
       persist result keyed by call identity
  -> idempotency record exists
```

For every effectful tool:

```text
BEGIN
  verify fencing token is current
  check idempotency key
  if already present:
      return stored result
  apply business mutation
  persist result/idempotency record
COMMIT
```

Never do:

```text
mutate DB
-> separately record that mutation succeeded
```

The stale-owner check and the effect must be transactionally coupled. Do not
check the token, pause and then mutate.

## Idempotency Record

Key:

- `episode_id`
- `step_index`
- `call_index`

Stored fields:

- tool name and tool version
- canonical arguments hash
- fencing token used
- effect result
- mutation metadata
- completion timestamp

Repeated calls with the same identity return the stored result. Repeated calls
with the same identity and different canonical arguments are protocol violations
and must fail closed.

## Lease And Fencing

P4a implements only enough Python-native orchestration to prove the protocol:

- claim episode
- lease token
- heartbeat
- expiration
- reaper
- reclaim
- retry count
- DLQ

Fencing tokens are monotonically increasing. Every new lease ownership receives a
newer token:

```text
Worker A -> fence 41
lease expires
Worker B -> fence 42
```

Any later effect attempt carrying token 41 must fail if token 42 is current.

Budgets are durable episode state. A crash must not reset consumed model turns,
tokens, cost, tool-call count or retry count.

Recovery itself must be resumable. Required explicit case:

```text
worker A crashes
worker B recovers
worker B crashes during recovery
worker C recovers
```

Final effects must still occur exactly once.

## Deterministic Harness

Do not start with an LLM. P4a begins with deterministic scripted trajectories
using P3's stateful support tools.

Example trajectory:

```text
read ticket
search policy
update priority
assign team
add comment
```

The same trajectory must be replayable thousands of times cheaply.

Correctness oracle: reuse the P3 final-state verifier. Every crash-injection
episode ends with:

- normalized final-state snapshot
- P3 diff verifier
- expected final-state PASS

Do not build another correctness oracle.

## Continuous Invariants

Assert continuously:

- at most one durable intent per logical call
- at most one effect/result record per logical call
- no effect without corresponding intent
- no completed step without result
- no stale fencing token accepted
- no duplicate business mutation

Any invariant violation is a protocol failure.

## Crash Matrix

The clean deterministic matrix must enumerate every supported combination of:

```text
crash window
x trajectory step
x effectful tool type
```

Minimum crash windows:

- before intent insert
- after intent insert, before effect transaction
- inside/before effect application
- after effect plus idempotency record commit, before runner step completion
- after runner step completion, before next model step

This is a full factorial matrix, not random sampling. Random crash testing may be
added later as fuzzing, but the correctness headline comes only from exhaustive
deterministic coverage.

## Zombie Matrix

SIGKILL does not test fencing because the worker is gone. P4a needs a separate
zombie/fencing experiment:

```text
Worker A owns lease token 41
SIGSTOP A
lease expires
reaper reclaims
Worker B gets token 42
B progresses
SIGCONT A
A attempts effect with token 41
```

Required measured values:

- stale-token attempts greater than 0
- stale-token accepted = 0
- corrupted final states = 0
- duplicate effects = 0

If no stale attempt occurred, the fencing test did not exercise fencing.

## Failure-Path Coverage

Add double-crash cases during:

- intent replay
- idempotency-result lookup
- recovered episode continuation

Add one intentionally poisoned episode with a deterministic condition that cannot
succeed. Verify:

- retries occur according to policy
- retry budget exhausts
- episode enters DLQ
- healthy episodes continue
- poisoned episode creates no duplicate effects

Malformed or corrupt recovery state must fail closed. The runtime must not invent
missing intents or effects.

## P4a Acceptance Criteria

For the complete clean deterministic matrix:

- duplicate side effects = 0
- lost required effects = 0
- incorrect final states = 0
- stale fenced effects accepted = 0
- orphan effect records = 0
- invariant violations = 0

These are absolute correctness criteria, not statistical thresholds. One
occurrence means protocol failure.

When a protocol bug is found:

- quarantine the failed development matrix
- write a tombstone naming the fault and detection mechanism
- fix the protocol
- rerun the entire matrix

Headline results may come only from the final clean full pass.

## Latency Reporting

Report detection latency separately from replay latency.

Detection latency:

```text
lease TTL + reaper scheduling behavior
```

Recovery/replay latency:

```text
reclaim -> useful execution resumes
```

Do not market configured TTL as an optimization result.

## Real-Agent Validation

After deterministic P4a passes, run a smaller LLM-agent set using P3 stateful
tasks and injected crashes in real trajectories.

Legal nondeterminism:

- If crash occurs before intent persistence, recovery may invoke the model again
  and choose a different valid action.
- If intent already exists, the action must not change.

Verify real-agent final state with the same P3 verifier.

Measure:

- successful recovery
- duplicates
- lost effects
- final-state correctness
- recovery/replay latency
- budget preservation

## P4b Java Integration

Document the polyglot ownership model before implementation:

```text
Java orchestration platform
  -> durable job / lease records
  -> Python agent worker
  -> P4 effect protocol
```

Prefer an external-worker protocol if the existing Java platform naturally
supports claim, heartbeat and fenced completion. The Python worker should speak
that protocol rather than Java synchronously invoking the whole Python agent as a
subprocess.

Persist:

- episode/job ID mapping
- lease/fencing token
- heartbeat
- checkpoint reference
- retry/DLQ state

The P4a effect protocol remains unchanged.

P4b required checks:

- bridge without injected failures produces the same deterministic final states as
  P4a
- representative crash subset covers before intent, after intent, after effect
  transaction before step completion, double crash and poison/DLQ
- zombie/fencing test through the real orchestrator proves an old Java/Python
  lease owner cannot mutate after a newer lease exists
- correctness remains identical to P4a

Separately measure integration overhead:

- claim latency
- heartbeat overhead
- reclaim/replay latency
- orchestration DB traffic, if useful

## Freeze Requirements

P4a freeze preserves:

- protocol specification
- schema
- store-ownership rules
- intent semantics
- idempotency semantics
- fencing semantics
- full crash matrix
- zombie matrix
- double-crash tests
- poison/DLQ case
- invariant-check results
- final-state verifier outputs

P4b freeze preserves:

- Java-to-Python ownership model
- job mapping
- bridge results
- representative fault matrix
- integration overhead

Claim boundary:

- P4a proves crash/idempotency/fencing correctness.
- P4b proves those guarantees survive integration with the existing distributed
  orchestration platform.
