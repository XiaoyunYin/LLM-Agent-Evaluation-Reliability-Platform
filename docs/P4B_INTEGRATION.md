# P4b Integration Seam

P4b connects the frozen P4a Python durability protocol to the distributed Java
job orchestration platform. This document is the seam contract. It exists before
bridge code so P4b does not accidentally create two competing durability
protocols.

P4a remains the protocol-correctness proof. P4b should prove that Java/Python
integration does not break it.

## Source Inspection

The Java platform was inspected from the sibling repository:

`D:\vscode project rebuild\distributed_job_orchestration_platform`

Relevant implementation files:

| Area | Source |
|---|---|
| job schema | `migrations/001_create_job_tables.sql`, `002_add_claimed_at_to_jobs.sql`, `003_create_job_recovery_events.sql`, `004_create_job_dlq.sql`, `005_add_runnable_jobs_ordered_partial_index.sql` |
| state enum | `services/shared/src/main/java/com/example/orchestration/shared/JobState.java` |
| job creation/API payload | `services/api/src/main/java/com/example/orchestration/api/jobs/JobRepository.java`, `JobController.java`, `CreateJobRequest.java` |
| scheduler claim | `services/scheduler/src/main/java/com/example/orchestration/scheduler/jobs/SchedulerJobRepository.java` |
| Kafka dispatch | `services/scheduler/src/main/java/com/example/orchestration/scheduler/jobs/JobDispatchPublisher.java`, `JobDispatchMessage.java` |
| reaper/reclaim | `services/scheduler/src/main/java/com/example/orchestration/scheduler/jobs/ReaperLoop.java`, `ReaperLeaseService.java` |
| worker lease | `services/worker/src/main/java/com/example/orchestration/worker/jobs/WorkerLeaseService.java` |
| worker protocol | `services/worker/src/main/java/com/example/orchestration/worker/jobs/JobDispatchListener.java` |
| completion/failure | `services/worker/src/main/java/com/example/orchestration/worker/jobs/WorkerJobRepository.java` |
| worker config | `services/worker/src/main/resources/application.properties` |

Observed Java behavior, not assumed:

- Jobs are created through `POST /jobs` with an idempotency key and a JSON string
  payload stored in `jobs.payload`.
- Runnable states are `QUEUED` and `RETRY_READY`.
- Scheduler claim uses `SELECT ... FOR UPDATE SKIP LOCKED`, moves jobs to
  `DISPATCHED`, increments `dispatch_version`, sets `claimed_at`, and publishes a
  Kafka dispatch message.
- The Kafka dispatch message contains only `jobId`, `attemptCount`, and
  `dispatchVersion`. It does not carry job payload.
- Worker processing uses manual Kafka ack with `max.poll.records=1` and consumer
  concurrency 1 by default.
- If a worker cannot acquire the Redis lease, it blocks the current Kafka message
  rather than skipping and committing past it.
- Redis lease key is `job:lease:{jobId}`; the value is a UUID token with
  configured TTL `worker.lease-ttl=10s`.
- Heartbeat refreshes the Redis lease when the stored token still matches.
- `markRunning` requires current `DISPATCHED` state plus matching
  `dispatch_version`; it increments `attempt_count`, stores `worker_id` and
  `lease_token`, and moves the job to `RUNNING`.
- Completion is required to transition the `jobs` row to `SUCCEEDED` and insert
  `job_results` atomically. The fixed seam shape is a single SQL statement where
  `UPDATE jobs ... RETURNING` feeds the `job_results` insert. The transition
  requires matching `job_id`, `dispatch_version`, `worker_id`, `lease_token`, and
  `RUNNING` state.
- Failure moves a `RUNNING` job to `RETRY_READY` if attempts remain, otherwise to
  `DLQ` and `job_dlq`.
- Stale `DISPATCHED` jobs are recovered to `RETRY_READY` after
  `reaper.dispatch-timeout`.
- Stale `RUNNING` jobs are candidates after `reaper.running-timeout`; the reaper
  checks Redis and recovers only if no lease key exists.
- Reclaim does not directly dispatch. It makes the job runnable again; the
  scheduler later claims it and increments `dispatch_version`.

## Ownership

### Java Job Orchestrator

The Java platform owns job-level durability and distributed ownership:

- job creation
- job idempotency key
- job claim
- Kafka dispatch
- worker lease acquisition
- heartbeat
- lease expiry detection
- stale `DISPATCHED` reclaim
- stale `RUNNING` reclaim
- retry count through `attempt_count`
- retry scheduling through `available_at`
- Java DLQ state and `job_dlq`
- durable fencing generation through `dispatch_version`
- active worker ownership through `(worker_id, lease_token)`
- job completion row in `job_results`

Java does not own Python episode reasoning, Python tool intent identity, or
support-ticket business mutation semantics.

### Python Agent Runtime

The Python runtime owns agent episode durability:

- episode execution
- model turns
- step state
- durable tool intents
- resume from persisted intent
- budget accounting
- checkpoint reference interpretation
- P3/P4 support verifier invocation

Python does not perform scheduler claims, does not generate job-level fences,
does not run an independent job reaper, and does not decide Java retry or DLQ
state. It may acquire a Redis lease and mark an already-dispatched job `RUNNING`
as part of the Java worker contract.

P4a's intent rule survives unchanged:

```text
before durable intent:
  model may be called again

after durable intent:
  model must not be consulted again for that logical tool call
```

Java retry/reclaim must resume the persisted Python episode. It must not restart
reasoning from scratch after an intent exists.

### Effect / Ticket Sandbox

The effect sandbox owns exactly-once business effects inside the P4 support world:

- fencing validation for effectful tool calls
- idempotency check
- business mutation
- effect result record
- duplicate-effect detection
- stale-fence rejection evidence

The P4a effect idempotency key remains:

```text
(episode_id, step_index, call_index)
```

It must not be replaced with `job_id`.

## Chosen Cross-Language Interface

Use the existing Java orchestration contract with a Python agent worker:

```text
Java API creates job
  -> Java scheduler claims and dispatches job
  -> Python worker consumes Kafka dispatch
  -> Python worker acquires Redis lease
  -> Python worker marks job RUNNING in PostgreSQL
  -> Python worker executes/resumes P4 episode
  -> Python worker heartbeats during execution
  -> Python worker marks job SUCCEEDED or failed/DLQ through the same fenced SQL contract
```

Do not use this as the default P4b seam:

```text
Java worker launches Python subprocess and waits synchronously
```

Reason: the current platform already expresses worker ownership as a distributed
Kafka/Postgres/Redis contract. A synchronous subprocess model would make Java the
long-running episode supervisor and would likely duplicate Python checkpoint and
resume semantics inside a Java process wrapper.

The Python worker should be a peer implementation of the worker contract, not a
child process hidden behind the existing Java synthetic worker.

## Java Completion Transactionality

P4b requires Java job completion to be atomic:

```text
job_results row exists <=> job reached SUCCEEDED through the fenced completion path
```

Audit finding:

- `WorkerJobRepository.markSucceededWithResult` was Spring `@Transactional`, so
  its two statements shared a transaction.
- The old shape inserted `job_results` first and then updated `jobs` to
  `SUCCEEDED`.
- If the second statement ever returned 0 without throwing, Spring would commit
  the transaction and preserve a completion result without a `SUCCEEDED` job.

Required fixed shape:

```sql
WITH completed_job AS (
  UPDATE jobs
  SET status = 'SUCCEEDED',
      updated_at = now()
  WHERE id = ?
    AND dispatch_version = ?
    AND worker_id = ?
    AND lease_token = ?
    AND status = 'RUNNING'
  RETURNING id, dispatch_version
),
result_insert AS (
  INSERT INTO job_results (job_id, dispatch_version, result_payload)
  SELECT id, dispatch_version, '{}'::jsonb
  FROM completed_job
  ON CONFLICT (job_id) DO NOTHING
  RETURNING job_id
)
SELECT job_id FROM result_insert
```

This preserves the existing Java fenced transition contract while making the
`SUCCEEDED` update the serialization point for result creation.

Verification status:

- `mvn -pl services/worker clean compile -DskipTests` passed after the change.
- `mvn -pl services/worker -Dtest=WorkerJobRepositoryTest test` could not run
  behaviorally because local Postgres on `localhost:55432` was unavailable.
- `docker compose -f infra/docker-compose.yml up -d postgres` failed because the
  host could not bind TCP port `55432`.

Run the worker repository tests once the local Postgres dependency is available.

## Job Payload

Keep `jobs.payload` small. The Kafka dispatch message already carries only job
identity and fence metadata, so the worker should fetch payload by `job_id`.

Recommended P4b payload shape:

```json
{
  "job_type": "agent_eval_episode",
  "run_id": "p4b_clean_bridge_001",
  "episode_id": "p4b_SUP-policy-001_0001",
  "task_id": "SUP-policy-001",
  "agent_config_id": "p4b_deterministic_reference_v1",
  "checkpoint_ref": {
    "kind": "sqlite",
    "episode_store": "p4b_episode_store.sqlite"
  }
}
```

Do not send full trajectories, support fixture contents, full before/after state,
or large checkpoints through Kafka.

The existing API accepts `payload` as an arbitrary JSON string; no Java schema
currently validates this shape.

P4b defines `agent_eval_episode` as the job type for one evaluation episode. One
evaluation run becomes one Java job per task:

```text
evaluation run
   |-- task 1  -> job 1
   |-- task 2  -> job 2
   ...
   `-- task 80 -> job 80
```

The payload carries references only. `run_id`, `episode_id`, `task_id`,
`agent_config_id`, and `checkpoint_ref` are sufficient for the first bridge.

## Identity Mapping

There are three identity layers:

```text
job_id
  Java orchestration identity.
  Owns dispatch, lease, retry, DLQ, and job_results.

episode_id
  Python agent episode identity.
  Owns model decisions, intents, checkpoints, budget, and verifier output.

(step_index, call_index)
  Python logical tool-call identity inside one episode.
  Combined with episode_id, this is the effect idempotency key.
```

Relationship:

```text
one job_id -> one episode_id -> many (step_index, call_index)
```

For P4b, use one evaluation episode per Java job. Avoid many jobs per episode
and avoid many episodes per job. If either becomes necessary later, amend this
document before measuring it.

## Fencing Propagation

The Java platform has two ownership values:

```text
dispatch_version
  durable, monotonic PostgreSQL fence incremented by scheduler claim

lease_token
  temporary Redis ownership token generated by the worker lease service
```

P4b effectful tool calls must receive the current orchestrator ownership:

```text
job_id
dispatch_version
worker_id
lease_token
episode_id
step_index
call_index
```

Conceptually:

```text
Java scheduler claim:
  job 123 -> dispatch_version 57

Python worker:
  episode ABC
  durable fence = 57
  active lease token = redis UUID

effect call:
  (ABC, step=4, call=1, dispatch_version=57, lease_token=<uuid>)
```

If the job is reclaimed:

```text
new scheduler claim -> dispatch_version 58
new worker lease -> new lease_token
```

Then any old effect attempt carrying `dispatch_version=57` must be rejected by
the effect sandbox transaction before mutation.

The minimum P4b requirement is dispatch-version fencing, because this is the
monotonic value that changes after reclaim. The stronger preferred check is to
validate both:

```text
dispatch_version == current jobs.dispatch_version
lease_token == current jobs.lease_token
status == RUNNING
```

If the effect sandbox cannot transactionally read the Java `jobs` row, the Python
worker must install the current Java `dispatch_version` into the sandbox fence
before resuming the episode. That fallback is acceptable only if the zombie test
proves stale workers with old fences are rejected.

## Resume Semantics

On each dispatch, the Python worker must:

1. Fetch the job payload by `job_id`.
2. Acquire Redis lease.
3. Mark the job `RUNNING` with matching `dispatch_version`.
4. Load or create the Python episode checkpoint by `episode_id`.
5. Install/validate the current Java fence for effect execution.
6. Resume from the next incomplete Python step.

The Python worker lifecycle interface is intentionally minimal:

```text
receive Kafka dispatch
fetch job payload
acquire/heartbeat lease
mark job RUNNING
execute/resume existing P4a episode runner
complete/fail the job
```

Prefer wrapping the existing Java fenced state-transition logic over rewriting
that SQL independently in Python. If P4b implements native Python access to
PostgreSQL/Redis/Kafka, its SQL must remain byte-for-byte or behaviorally
equivalent to the Java transition contract and must be covered by the P4b fault
subset.

For a logical tool call:

```text
if no durable intent exists:
  call model if needed
  persist intent before any effect

if durable intent exists:
  do not call model again for that logical call
  reuse the persisted tool name and arguments

if effect result exists:
  reuse result
  do not mutate again

if effect result is absent:
  execute effect once under current fence
  persist result atomically with mutation
```

The dangerous window is:

```text
intent persisted
effect committed
worker dies before Java job completion
```

Recovery requirement:

```text
new worker reads persisted intent
new worker discovers stored effect result
new worker continues
new worker does not execute the effect again
```

Use shared durable storage for Python episode state. Persist:

- checkpoint
- budget
- durable intent
- effect result / idempotency record

P4b must connect the existing P4a episode runner. Do not create a new agent
runtime.

The intended flow is:

```text
Kafka job
   -> load episode
   -> existing P4a execution/resume
   -> verifier/result
```

## First Bridge: No Faults

Build the smallest deterministic bridge before adding crash injection:

1. Create a small set of Java jobs with P4 payloads.
2. Let the Java scheduler claim and dispatch them.
3. Let the Python worker acquire leases and mark jobs `RUNNING`.
4. Execute deterministic P4 references.
5. Heartbeat while running.
6. Mark jobs `SUCCEEDED`.
7. Compare final support-ticket states with P4a verifier output.

Required checks:

- job claim occurred through Java scheduler
- heartbeat succeeded during Python execution
- Python episode completed
- Java job reached `SUCCEEDED`
- `job_results` contains one row per job
- P4 verifier result is identical to P4a
- no duplicate effects
- no lost effects
- budget accounting is persisted

No crash injection in this first bridge.

## Fault Subset for P4b

P4b does not need another 915-case matrix. P4a already proves the Python
protocol. P4b proves that the Java/Python seam preserves it.

Minimum representative subset:

| Case | Purpose |
|---|---|
| clean execution | base Java/Python lifecycle |
| crash before intent | reclaim resumes before model decision is fixed |
| crash after intent | persisted intent prevents re-reasoning |
| crash after effect commit before Java completion | stored effect result prevents duplicate mutation |
| double crash | repeated reclaim remains resumable |
| stale zombie | old `dispatch_version`/lease cannot mutate after reclaim |
| poison/DLQ | Java retry/DLQ integrates with Python effect invariants |

## Reclaim Test

Scenario:

```text
worker A claims episode
A executes partially
A stops heartbeating / dies
Java lease expires
reaper moves RUNNING -> RETRY_READY
scheduler reclaims RETRY_READY -> DISPATCHED and increments dispatch_version
worker B resumes
```

Require:

- same final verified support state as P4a
- zero duplicate effects
- zero lost required effects
- persisted budget preserved
- previous intent records reused
- `job_recovery_events` records `LEASE_EXPIRED`
- final Java job state is `SUCCEEDED`

## Stale Worker Fencing Test

Scenario:

```text
A gets dispatch_version 100 and lease token A
A pauses
lease expires
reaper recovers job to RETRY_READY
scheduler reclaims job with dispatch_version 101
B gets lease token B and proceeds
A resumes
A attempts effect with dispatch_version 100 / lease token A
```

Require:

- stale attempts > 0
- accepted stale effects = 0
- duplicate business mutations = 0
- final verifier passes
- Java stale completion, if attempted, is rejected by the existing completion SQL

This is a real zombie fencing test at the protocol level. It is not an OS
SIGSTOP claim unless the test actually pauses a process with OS facilities and
records that evidence.

## Poison / DLQ Test

Use one deterministic poison episode with an invalid effect, such as assignment
to a missing team.

Require:

```text
attempt 1 -> failed/retryable
attempt 2 -> failed/retryable
attempt 3 -> Java DLQ
```

Checks:

- Java `attempt_count` reaches `max_attempts`
- job status is `DLQ`
- `job_dlq` has one row
- Python effect result count is 0
- duplicate effects are 0
- stale accepted effects are 0
- no successful business mutation occurred

## Integration Metrics

P4b metrics should be integration-specific:

- job claim latency
- dispatch publish latency
- Kafka receive latency, if measurable
- heartbeat interval and overhead
- lease-expiry detection time
- reclaim-to-resume latency
- completion latency
- retry/DLQ transition behavior

Keep configured TTLs separate from observed recovery work. For example,
`worker.lease-ttl=10s` is configuration; `lease expired -> job reclaimed ->
episode resumed` is a measured recovery path.

## Required P4b Artifacts

When P4b is eventually frozen, preserve it separately from P4a:

```text
P4a:
  protocol correctness proof
  tag: p4a-frozen

P4b:
  Java/Python integration proof
  tag: p4b-frozen
```

Expected P4b result artifacts:

- bridge config
- Java platform commit/tag
- LLM/Python repo commit/tag
- job payload fixture
- raw job rows before/after
- Python episode checkpoint/effect records
- verifier results
- integration metrics
- failure/reclaim evidence
- quarantine tombstone for any failed or contaminated run

## Open Implementation Decisions

These are not settled by the current Java implementation:

- Whether to implement the Python worker as a native Kafka/Postgres/Redis client
  or add a small Java-owned worker lifecycle API. The current architecture favors
  native participation, but native participation means duplicating the fenced SQL
  contract in Python.
- Whether effect sandbox fencing should query the Java `jobs` row transactionally
  or install `dispatch_version` into a sandbox-local fence table on each resume.
  The former is stronger; the latter is closer to P4a.
- Where Python episode checkpoints live for multi-process workers. The first
  bridge should use an explicit shared checkpoint reference rather than local
  process memory.
- How to record Python budget accounting in relation to Java retry attempts.
  Budget belongs to `episode_id`, not to `job_id` or `attempt_count`.

No P4b measurement should be called frozen until these decisions are made in code
and verified by the representative fault subset above.
