# Build Log

## Session 1

Goal: create the repository skeleton.

Completed:

- Created root project folders.
- Created `README.md`.
- Created project convention docs.

- Created documentation folders.

Measured results:

- None yet.

Notes:

- Project inputs are configuration targets, not measured outcomes.

- Verified repository skeleton exists.
- Filled in the initial `README.md`.
- Kept the project convention docs as persistent rule files.


## Session 2

created the backend virtual environment and verified a dependency import.

## Session 3 - Golden dataset v0.1

Created `datasets/golden/golden_rag_v0.1.jsonl` as the first versioned RAG evaluation dataset.

Validated:
- JSONL parsing succeeds
- Row count: 120
- Required fields present: `id`, `question`, `expected_answer`, `task_type`, `metadata`
- Unique IDs: 120
- Duplicate IDs: none

Notes:
- Dataset examples were iteratively created and polished.
- This dataset is intended as the initial stable input set for future retrieval and answer-generation evaluation.
- Future work should add an automated validator script and record dataset version in every eval run.

## Session 4 - Dataset Loader

Built a Python JSONL dataset loader for golden eval cases.

Implemented:
- `backend/app/eval_case.py` with a Pydantic `EvalCase` model and `TaskType` enum.
- `backend/app/dataset_loader.py` with line-by-line JSONL loading, row-numbered validation errors, and a small CLI.

Validation checks:
- Required fields: `id`, `question`, `expected_answer`, `task_type`, `metadata`.
- `task_type` must be one of the supported enum values.
- `id`, `question`, and `expected_answer` must not be blank.

Measured result:
- Command: `python -m backend.app.dataset_loader datasets/golden/golden_rag_v0.1.jsonl`
- Loaded 120 eval cases successfully.



## Session 5 - Eval Run Models

Created the first data models for recording evaluation runs and generated answers.

Implemented:
- `RunStatus` enum with `pending`, `running`, `completed`, and `failed`.
- `EvalRun` model for run-level metadata.
- `CandidateAnswer` model for generated answers.
- `JudgeScore` stub for later judge outputs.

Validation checks:
- `run_id`, `dataset_version`, and `provider_name` must not be blank on `EvalRun`.
- `run_id`, `case_id`, and `generated_answer` must not be blank on `CandidateAnswer`.
- `run_id` and `case_id` must not be blank on `JudgeScore`.

Manual checks:
- Created an `EvalRun` and `CandidateAnswer` in memory.
- Confirmed blank `run_id` raises a Pydantic validation error.
- Created a `JudgeScore` stub in memory.

Automated checks:
- Command: `.\.venv\Scripts\python.exe -m pytest tests/test_eval_run.py`
- Result: 4 passed
- Added coverage for `CandidateAnswer` and `JudgeScore` defaults.

Measured results:
- None yet.

Notes:
- `JudgeScore` intentionally does not include metric fields yet.
- Scores will be added only after the judge rubric and structured output schema are designed.


## Session 6 - Mock LLM Provider Design Note

Goal: create a mock LLM provider before calling real APIs.

A provider is anything that can generate an answer from a user query and retrieved context. The rest of the evaluation system should not need to know whether the answer came from a mock provider, OpenAI, Anthropic, or an optional self-hosted model.

Provider input:
- query id
- user question
- retrieved chunks
- provider name or provider config
- run id

Provider output:
- answer text
- provider name
- model name
- whether the provider is mock or real
- optional metadata such as latency, token counts, or error details

The provider should return more than just text because evaluation needs traceability. Later, I need to know which provider and model produced each candidate answer so that judging, regression tests, and dashboard metrics are honest.

A mock answer can be simple and deterministic. For example, for a question about a document, the mock provider can return a fake answer that mentions the query id and says it was generated from the retrieved chunks. This lets me test the generation pipeline without spending API money.

Mock provider runs must be clearly marked as mock. They are useful for rehearsal, debugging, checkpointing, and testing the run matrix, but they do not count as real OpenAI or Anthropic candidate generation.

Later, OpenAIProvider and AnthropicProvider can follow the same interface as MockProvider. That means generate_answer can call any provider through the same contract.

An optional self-hosted candidate provider may also follow this interface later, but self-hosted candidate generation is not required for my current resume claim. The required self-hosted model work is for the bulk judge, not necessarily for candidate generation.


Why is generate_answer(provider, request) better than calling OpenAI or Anthropic directly from the dataset loop?
Why should candidate generation avoid reading expected_answer?
What future metadata might we want in GenerationResponse.metadata?

Quiz Answers
generate_answer(provider, request) is better than calling OpenAI or Anthropic directly from the dataset loop because it keeps the dataset loop independent from provider details. The loop only knows “I need an answer.” The provider layer handles whether that answer comes from a mock, OpenAI, Anthropic, or a future self-hosted model.

Candidate generation should avoid reading expected_answer because that would leak the gold label into the model input. The candidate answer must be generated from the question and retrieved context only. The expected answer is for judging or scoring after generation.

Useful future metadata could include latency, input token count, output token count, total cost, provider request id, retry count, error message, retrieval strategy, prompt version, and trace id.

### Session 6 Completion - Mock LLM Provider

Completed the first mock candidate-generation path.

Built:
- provider interface using `LLMProvider`
- request/response models with `GenerationRequest` and `GenerationResponse`
- `MockProvider`
- `generate_answer(provider, request)` orchestration function
- tests for provider behavior and generation orchestration
- rehearsal script that loads real dataset rows and prints mock candidate answers

The mock provider is useful for rehearsing the pipeline before calling paid APIs or using GPU resources. Mock answers are clearly marked with `is_mock=True`.

Metric integrity note: mock provider outputs do not count as real OpenAI or Anthropic candidate generations and must be excluded from real provider-diversity claims.

Design note: OpenAI and Anthropic providers can later implement the same interface. An optional self-hosted candidate provider may also fit this interface, but self-hosted candidate generation is not required for the current resume claim.


## Session 7 - First Local End-to-End Eval Generation Run

Goal: build the first synchronous local eval-generation run.

Built:
- Loaded the golden eval dataset from `datasets/golden/golden_rag_v0.1.jsonl`.
- Created a unique local `run_id` for each run.
- Called `MockProvider` once for every eval case.
- Saved candidate answers to JSONL under `runs/`.
- Printed a run summary with dataset path, case count, saved answer count, and output path.
- Refactored the script into `run_local_mock_generation()` so it can be tested.
- Added a shared pytest import setup with `tests/conftest.py`.

Measured results:
- Dataset rows loaded: 120
- Candidate answers saved: 120
- Latest verified command: `python scripts\mock_generate_answers.py`
- Latest verified output included:
  - `cases_loaded=120`
  - `candidate_answers_saved=120`
- Full test suite: 7 passed

Important note:
- This was a mock-provider rehearsal only.
- These candidate answers do not count as real OpenAI or Anthropic API generations.
- No judge scores were produced in this session.

Design note:
- The current flow is synchronous and local:
  `load dataset -> create run_id -> generate mock answers -> save candidates -> print summary`
- Later, this will evolve into:
  `POST /runs -> Redis Queue -> worker -> evaluation pipeline`

Reliability note:
- Candidate answers are saved before judging so future judge runs can be reproduced, resumed, audited, and retried without regenerating answers.



## Session 8 - OpenAI Provider Interface

Goal: add an OpenAI provider interface while keeping mock generation safe as the default.

Built:
- Added `OPENAI_API_KEY` environment-variable lookup for OpenAI configuration.
- Added `OpenAIProvider` with the same `generate_answer(request)` interface as `MockProvider`.
- Added provider selection by name with `get_provider("mock")` and `get_provider("openai")`.
- Added safe configuration errors for missing API keys and unknown provider names.
- Added safe generation-error wrapping at the provider boundary.
- Added OpenAI prompt construction from `GenerationRequest`.
- Added CLI provider selection with `--provider mock` and `--provider openai`.
- Kept `mock` as the default provider so local rehearsal runs do not call paid APIs.

Validation:
- Full test suite passed: 13 passed.
- Safe mock run completed:
  - `cases_loaded=120`
  - `candidate_answers_saved=120`
  - output path: `runs\local_mock_20260730_045916_candidate_answers.jsonl`
- OpenAI missing-key path failed safely with `ProviderConfigurationError`.
- No real OpenAI API calls were made.

Metric integrity note:
- This session adds OpenAI provider plumbing only.
- It does not prove real OpenAI candidate generation yet.
- OpenAI API coverage should not be claimed until a real OpenAI run produces persisted candidate answers.
- Mock candidate answers remain useful for rehearsal and tests, but they do not count as real provider diversity.

Security note:
- API keys must come from environment variables such as `OPENAI_API_KEY`.
- API keys should never be hardcoded, printed, saved in JSONL outputs, or committed to version control.

## Session 9 - Anthropic and Optional Self-Hosted Provider Interfaces

Goal: add Anthropic and optional self-hosted model provider interfaces for candidate generation.

Built:
- Added `AnthropicProvider` with the same `generate_answer(request)` interface as the existing mock and OpenAI providers.
- Added `SelfHostedProvider` that sends generation requests to an HTTP endpoint.
- Added shared prompt construction so OpenAI, Anthropic, and self-hosted providers receive the same question/context format.
- Added config-based provider selection through `get_provider()`.
- Added CLI provider choices for `mock`, `openai`, `anthropic`, and `self-hosted`.
- Kept mock generation as the safe default for local rehearsal.

Configuration:
- Anthropic uses `ANTHROPIC_API_KEY`.
- Self-hosted candidate generation uses `SELF_HOSTED_MODEL_ENDPOINT`.
- OpenAI continues to use `OPENAI_API_KEY`.

Validation:
- Provider tests passed:
  - `python -m pytest tests/test_providers.py`
  - Result: 14 passed
- Mock generation rehearsal completed:
  - Command: `python scripts/mock_generate_answers.py --provider mock`
  - `cases_loaded=120`
  - `candidate_answers_saved=120`
  - output path: `runs\local_mock_20260730_054734_candidate_answers.jsonl`

Metric integrity note:
- This session completes provider-interface plumbing only.
- It does not prove real OpenAI or Anthropic candidate generation yet.
- The current resume requires real candidate-answer generation across OpenAI and Anthropic APIs.
- Mock runs are useful for testing but do not count as real provider diversity.
- The self-hosted provider is optional for candidate generation and should not be treated as required for the current resume claim.

Important distinction:
- The later Mistral-7B-Instruct-v0.3-AWQ vLLM work is required for the self-hosted judge path.
- Self-hosted candidate generation is only an optional interface for future experiments.

## Session 10 - Judge Score Format

Goal: design the structured judge score format.

Built:
- Expanded `JudgeScore` from a placeholder into a real structured score model.
- Added score fields for `correctness`, `faithfulness`, and `citation_quality`.
- Added `passed` for pass/fail evaluation.
- Added `explanation` for human-readable judge reasoning.
- Added `judge_name` to record the exact judge that produced the score.
- Added `JudgeType` with `rule_based`, `gpt4o_mini`, and `self_hosted_7b`.
- Made the score model JSON-compatible through Pydantic.
- Added validation so score fields must be between `0.0` and `1.0`.

Validation:
- Updated eval-run tests for the structured judge score.
- Added a validation test proving scores above `1.0` are rejected.
- Command: `pytest tests/test_eval_run.py`
- Result: 5 passed

Design notes:
- LLM evaluation needs judges because generated answers can be partially correct, unsupported, poorly cited, or difficult to grade with exact matching.
- Structured judge output is better than free text because storage, dashboards, regression checks, and CI gates need predictable fields.
- Correctness and faithfulness are separate because an answer can be factually correct but not supported by the retrieved context.
- Citation quality matters in RAG because users need to verify which retrieved chunks support the answer.
- Recording `judge_name` and `judge_type` keeps scores traceable and prevents mixing rule-based, GPT-4o-mini, and self-hosted 7B results as if they were identical.

Metric integrity note:
- No real judge scores were produced in this session.
- No GPT-4o-mini or self-hosted 7B judge validation was run yet.
- Agreement rate, manual-review routing rate, and bulk judged-answer count remain open questions until measured.


## Session 11 - Simple Rule-Based Judge

Goal: create a simple local judge for learning and pipeline testing.

Built:
- Added a rule-based judge that compares `generated_answer` with `expected_answer`.
- Produces a structured `JudgeScore`.
- Scores exact matches as `1.0`.
- Scores answers that contain the expected answer as `0.8`.
- Scores non-matching answers as `0.0`.
- Includes a human-readable explanation.
- Saves judge results to JSONL under `runs/`.
- Added tests for exact match, contained answer, and wrong answer.
- Added a script to judge a saved candidate-answer file.

Validation:
- Rule-based judge tests passed:
  - `python -m pytest tests/test_rule_based_judge.py`
  - Result: 3 passed
- Full test suite passed:
  - `python -m pytest`
  - Result: 25 passed

Measured results:
- Candidate answer file judged:
  - `runs\local_mock_20260730_054734_candidate_answers.jsonl`
- Judge scores saved: 120
- Output path:
  - `runs\local_mock_20260730_054734_rule_based_judge_scores.jsonl`

Design notes:
- Starting with a rule-based judge helps test the evaluation pipeline cheaply before using paid APIs or GPU time.
- This judge is intentionally simple and cannot reliably judge paraphrases, reasoning quality, factual support, or citation quality.
- `faithfulness` and `citation_quality` are set to `0.0` because this judge does not inspect retrieved context or citations.
- The same pipeline shape can later be reused with GPT-4o-mini for the 120-answer validation slice and the self-hosted 7B judge for bulk judging.

Metric integrity note:
- These are mock-provider candidate answers and rule-based judge scores.
- They do not count as real OpenAI or Anthropic candidate generation.
- They do not count as GPT-4o-mini or self-hosted 7B judge validation.
- Agreement rate, manual-review routing rate, and bulk judged-answer count remain open questions until measured with the real judge setup.

## Session 12 - Simple FastAPI Backend

Goal: create a simple FastAPI backend.

Built:
- Added FastAPI and Uvicorn dependencies.
- Turned `backend/main.py` into a FastAPI app.
- Added `GET /health`.
- Added temporary in-memory eval-run data.
- Added `GET /eval-runs` to list eval runs.
- Added `GET /eval-runs/{run_id}` to fetch one eval run by ID.
- Added a `404` response for missing eval runs.

Validation:
- Installed backend API dependencies successfully:
  - `fastapi`
  - `uvicorn`
- Ran the backend with:
  - `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload`
- Verified `GET /health` returned:
  - `{"status":"ok"}`
- Verified `GET /eval-runs` returned the placeholder eval-run list.
- Verified `GET /eval-runs/local_mock_001` returned the placeholder eval run.
- Verified `GET /eval-runs/does_not_exist` returned:
  - `{"detail":"Eval run not found"}`

Measured results:
- None yet.

Metric integrity note:
- The eval-run data is temporary placeholder API data.
- `total_cases=3` and `passed_cases=2` are not measured project metrics.
- This session proves API wiring only, not real benchmark performance.

Design notes:
- An API lets the frontend ask the backend for data.
- FastAPI maps Python functions to HTTP endpoints.
- GET endpoints are used for reading data without changing server state.
- Later, the React dashboard can call these endpoints to show run lists and run details.


## Session 13 - Docker Compose Backend

Goal: add Docker Compose slowly and run the backend inside Docker.

Built:
- Added `backend/Dockerfile` for the FastAPI backend.
- Added `docker-compose.yml` with a `backend` service.
- Configured the backend container to run Uvicorn on `0.0.0.0:8000`.
- Added a Docker health check that calls `GET /health` from inside the container.

Validation:
- Built the backend Docker image:
  - `docker build -f backend/Dockerfile -t llm-eval-backend:dev .`
- Ran the backend container directly with Docker.
- Verified `GET /health` returned:
  - `{"status":"ok"}`
- Started the backend through Docker Compose:
  - `docker compose up --build`
- Verified Compose reported the backend as:
  - `Up ... (healthy)`

Measured results:
- Docker backend health check status: healthy.
- API health endpoint response: `{"status":"ok"}`.

Notes:
- The first Compose attempt failed because host port `8000` was already used by a previous direct `docker run` container.
- Stopping the old container freed the port and Compose started successfully.
- This session proves backend containerization only.
- It does not measure retrieval, generation, judging, latency, cost, or benchmark quality.

Design notes:
- A Docker image is the packaged blueprint for running the app.
- A Docker container is a running instance of that image.
- Docker Compose manages project services from one YAML file.
- This project uses services because the full platform will eventually need separate components for the backend, frontend, databases, Elasticsearch, workers, and judge infrastructure.


## Session 14 - Data Services in Docker Compose

Goal: add local data services to Docker Compose and start the containers before writing application database logic.

Built:
- Added a PostgreSQL service using a pgvector-enabled image.
- Added an Elasticsearch service for local search and trace storage experiments.
- Added a Redis service for future queue, cache, and worker coordination experiments.
- Added named Docker volumes for persistent PostgreSQL and Elasticsearch data.

Validation:
- Started only the data services:
  - `docker compose up -d postgres elasticsearch redis`
- Verified containers were running:
  - PostgreSQL exposed on port `5432`
  - Elasticsearch exposed on port `9200`
  - Redis exposed on port `6379`
- Verified Elasticsearch responded on `http://localhost:9200`.
- Verified Redis responded with:
  - `PONG`
- Verified pgvector extension was available in PostgreSQL:
  - `extname = vector`

Measured results:
- Running data service containers: 3
- Verified pgvector extension rows returned: 1
- Redis ping response: `PONG`

Metric integrity note:
- This session verifies local infrastructure only.
- No application database tables were created.
- No retrieval benchmark was run.
- No Elasticsearch trace count was measured.
- No Redis queue or worker behavior was implemented yet.

Design notes:
- PostgreSQL will be the durable source of truth for structured eval data such as runs, cases, candidate answers, and judge scores.
- pgvector adds vector similarity support to PostgreSQL for future dense embedding retrieval.
- Elasticsearch will support BM25 search and trace querying.
- Redis will support temporary coordination needs such as queues, cache entries, locks, and job status.
- Starting containers first makes infrastructure problems visible before application code depends on them.


## Session 15 - Data Service Connection Tests

Goal: write simple Python connection tests for the local data services.

Built:
- Added a Postgres connection test script.
- Added an Elasticsearch connection test script.
- Added a Redis connection test script.
- Each script performs one minimal smoke test and prints a success message.
- Did not build retrieval, indexing, queues, workers, or benchmark logic.

Validation:
- Postgres connection test passed:
  - Command: `.\.venv\Scripts\python scripts\check_postgres_connection.py`
  - Output: `Postgres connection OK`
- Elasticsearch connection test passed:
  - Command: `.\.venv\Scripts\python scripts\check_elasticsearch_connection.py`
  - Output: `Elasticsearch connection OK`
- Redis connection test passed:
  - Command: `.\.venv\Scripts\python scripts\check_redis_connection.py`
  - Output: `Redis connection OK`

Bug fixes and debugging notes:
- Postgres initially failed with password authentication errors.
- The first suspected cause was an old Docker volume with stale Postgres credentials.
- After recreating the volume, the error continued.
- `netstat` showed two processes listening on host port `5432`.
- The project Postgres host port was changed from `5432` to `5433` to avoid the local port conflict.
- The final working host connection string uses `localhost:5433`.
- Elasticsearch initially failed from Python with `Remote end closed connection without response`.
- PowerShell verified Elasticsearch was healthy at `http://127.0.0.1:9200`.
- The Elasticsearch script was changed from `localhost` to `127.0.0.1` to avoid localhost/IPv6 ambiguity.

Measured results:
- Data service connection tests passed: 3
- Postgres reachable from host Python: yes
- Elasticsearch reachable from host Python: yes
- Redis reachable from host Python: yes

Metric integrity note:
- These are infrastructure smoke tests only.
- No retrieval benchmark was run.
- No documents were indexed.
- No candidate answers were generated in this session.
- No judge scores, latency, cost, or quality metrics were measured.

Design notes:
- Connection tests are useful because they isolate infrastructure problems before application logic depends on the services.
- A connection string tells client code which protocol, host, port, credentials, and database to use.
- Host-machine code should use published host ports such as `localhost:5433` or `127.0.0.1:9200`.
- Docker containers should use Compose service names such as `postgres:5432`, `elasticsearch:9200`, and `redis:6379`.


## Session 16 - Initial Postgres Schema and Chunk Storage Smoke Test

Goal: enable pgvector and create the first application database tables.

Built:
- Enabled the `pgvector` extension in the local PostgreSQL database.
- Created the `documents` table.
- Created the `chunks` table with a nullable `vector(1536)` embedding column.
- Created the `eval_runs` table.
- Created the `candidate_answers` table.
- Created the `judge_scores` table.
- Created the `review_cases` table.
- Added `scripts/test_chunk_storage.py` to insert and read one test chunk.

Validation:
- Ran the initial schema migration through Docker Compose and `psql`.
- Verified PostgreSQL listed 6 application tables:
  - `candidate_answers`
  - `chunks`
  - `documents`
  - `eval_runs`
  - `judge_scores`
  - `review_cases`
- Ran the chunk storage smoke test:
  - Command: `.\.venv\Scripts\python scripts\test_chunk_storage.py`
  - Output: `('chunk_test_001', 'doc_test_001', 0, 'This is a test chunk stored in PostgreSQL.')`

Measured results:
- Application database tables created: 6
- Test chunks inserted and read back: 1

Metric integrity note:
- This session proves database schema wiring and one basic insert/read path only.
- No embeddings were generated.
- No retrieval benchmark was run.
- No candidate answers were generated.
- No judge scores were produced.
- No dashboard, CI gate, latency, cost, trace count, or quality metric was measured.

Design notes:
- A database extension adds optional PostgreSQL capabilities; `pgvector` adds vector storage and similarity search support.
- A table stores structured records with columns, constraints, and relationships.
- Documents and chunks are separated because one source document can produce many searchable chunks.
- Chunk IDs must stay stable so retrieval experiments remain reproducible across runs.
- Eval runs should eventually move from JSONL files into durable storage so dashboards, workers, CI gates, and historical comparisons can query them reliably.
- Judge scores and review cases need storage so measured evaluations and human-review routing can be audited later.


## Session 17: Redis queue worker skeleton

Added the first real Redis-backed queue path for eval runs.

Implemented:

- `EvalRunJobPayload` as the queue contract for eval-run jobs.
- A simple Redis list queue named `eval_run_jobs`.
- `scripts/enqueue_eval_run_job.py` to enqueue validated eval-run job payloads.
- `scripts/run_eval_worker.py` as a long-running worker process.
- Worker result storage under `eval_run_result:<run_id>`.
- Tests for payload defaults, validation, and JSON round-trip serialization.

Current flow:

```text
enqueue script -> Redis eval_run_jobs queue -> worker -> eval_run_result:<run_id>



Session 18 - FastAPI Redis Queue Run Orchestration
Goal: connect FastAPI to Redis Queue for eval runs.
Built:
Added queued as the initial eval-run status.
Added Redis helper functions for saving, loading, updating, and enqueueing eval runs.
Added POST /runs to create an eval run, store it with status queued, and enqueue a Redis job.
Added GET /runs/{run_id} to read current run status.
Updated the Redis worker so queued jobs move through:queued
running
completed
failed if an exception occurs

Validation:
Eval run model tests passed:5 passed

Queue job tests passed:4 passed

Created a run through the API:run_id=eval_run_20260731_042205
initial status: queued

Worker processed queued Redis jobs:eval_run_20260731_042205
eval_run_20260731_042824

Verified GET /runs/eval_run_20260731_042205 returned:status: completed

Measured results:
Redis queued jobs processed in this session: 2
Verified completed run status through API: 1
Metric integrity note:
This session proves async orchestration only.
The worker still uses a placeholder pipeline.
No real candidate answers were generated by this worker path yet.
No judge scores, retrieval benchmark, latency, cost, or quality metrics were measured.
Design notes:
Async orchestration matters because eval runs can take much longer than a normal HTTP request.
The API should return quickly after creating and enqueueing the run.
Redis stores the queue item, while the run status lets clients poll progress.
This pattern supports real evaluation-platform workflows such as dashboards, retries, CI-triggered evals, long-running generation jobs, and later worker-based judging.
Redis is acceptable for this learning step, but Postgres should eventually become the durable source of truth for run history.


## Session 19 - Retrieval Corpus Assembly

Created a project-owned synthetic support corpus for the retrieval system.

Measured corpus counts:

- raw documents: 1,100
- chunks: 9,900
- chunk size: 650 characters
- chunk overlap: 100 characters

Storage locations:

- raw Markdown documents: `datasets/corpus/raw/`
- chunk JSONL file: `datasets/corpus/chunks.jsonl`
- Postgres tables: `documents`, `chunks`

Notes:

- The dossier target was about 1,100 documents and about 9,600 chunks.
- The measured chunk count is 9,900, so future claims should use the measured number.
- Chunk IDs use the pattern `{doc_id}_chunk_{chunk_index:04d}`.
- Embeddings have not been generated yet.


## Session 20 - Held-Out Retrieval Label Set

Goal: design and create a held-out 120-query labeled set for retrieval evaluation, with relevance labels created blind to judge outputs.

Built:

- Created `datasets/labels/retrieval_heldout_120_v0.1.jsonl`.
- Added 120 held-out retrieval queries.
- Added graded relevance labels using `0`, `1`, and `2`.
- Added stable relevant chunk IDs from `datasets/corpus/chunks.jsonl`.
- Added category metadata for difficulty, hop type, match type, and domain.
- Documented the labeling protocol in `docs/docs/retrieval-labeling-plan.md`.
- Added and tightened `scripts/validate_retrieval_labels.py`.

Measured validation:

- Total label records: 120
- Category cells: 8
- Records per category cell: 15
- Strict validator result: passed

Strict validation command:

```powershell
python scripts\validate_retrieval_labels.py --strict
```

Strict validation output:

```text
records: 120
category counts:
  ('easy', 'multi-hop', 'exact-term'): 15
  ('easy', 'multi-hop', 'semantic/paraphrase'): 15
  ('easy', 'single-hop', 'exact-term'): 15
  ('easy', 'single-hop', 'semantic/paraphrase'): 15
  ('hard', 'multi-hop', 'exact-term'): 15
  ('hard', 'multi-hop', 'semantic/paraphrase'): 15
  ('hard', 'single-hop', 'exact-term'): 15
  ('hard', 'single-hop', 'semantic/paraphrase'): 15
```

Metric integrity notes:

- This is a held-out query-and-label set, not a document train/test split.
- Labels are marked as created blind to GPT-4o-mini judge outputs, 7B judge outputs, generated answers, and retrieval benchmark scores.
- The label set is structurally complete, but it is an assistant-generated initial label set and should receive human review before using the metrics for strong claims.
- The synthetic corpus is highly templated, so near-duplicate relevant chunks may exist beyond the listed chunk IDs.
- No retrieval benchmark metrics were measured in this session.


## Session 21 - Retrieval Label Set Validation

Goal: validate the held-out labeled retrieval query set.

Built:

- Extended `scripts/validate_retrieval_labels.py` to print the actual labeled query count.
- Added relevance label distribution reporting.
- Added query category distribution reporting by difficulty, hop type, match type, domain, and combined category cell.
- Added an automatic short results note at `docs/docs/retrieval-label-validation-results.md`.
- Kept the existing chunk ID existence checks against `datasets/corpus/chunks.jsonl`.

Measured validation:

- Labeled queries measured: 120
- Dossier input target: 120
- Completion status: complete
- Relevant chunk references checked: 180
- Unknown relevant chunk IDs: 0
- Strict validator result: passed

Label distribution:

- Relevance 0: 0
- Relevance 1: 0
- Relevance 2: 180

Query category distribution:

- Difficulty: easy 60, hard 60
- Hop type: multi-hop 60, single-hop 60
- Match type: exact-term 60, semantic/paraphrase 60
- Combined category cells: 8 cells with 15 queries each

Domain distribution:

- accounts: 17
- api: 10
- billing: 12
- dashboards: 12
- exports: 12
- incidents: 12
- integrations: 12
- permissions: 12
- reports: 11
- troubleshooting: 10

Validation command:

```powershell
python scripts\validate_retrieval_labels.py --strict
```

Metric integrity notes:

- This validates label file structure and chunk ID references only.
- No retrieval quality, latency, cost, generation, or judge metrics were measured.
- The labeled set currently meets the 120-query target, so it is not documented as incomplete.
- All measured relevant chunk references currently use relevance `2`; there are no relevance `0` or `1` chunk references in the label file.


## Session 22 - Dense Retrieval with pgvector

Goal: implement dense retrieval with pgvector.

Dossier input configuration:

- Embedding model: `text-embedding-3-small`
- Embedding dimension: 1536
- pgvector index: HNSW
- Similarity: cosine
- Dense candidate depth: top 50
- Final dense benchmark output: top 10

Built:

- Added an embedding interface in `backend/app/embeddings.py`.
- Added `OpenAIEmbeddingProvider` using `text-embedding-3-small`.
- Kept the existing `chunks.embedding vector(1536)` storage design.
- Added `migrations/002_dense_retrieval_index.sql` for an HNSW cosine pgvector index.
- Added `backend/app/dense_retrieval.py` for pgvector dense retrieval.
- Added local tests for embedding provider behavior and vector formatting.
- Added `scripts/test_dense_retrieval.py` as a fake-embedding pgvector smoke test.

Measured validation:

- Embedding constants import output: `text-embedding-3-small 1536`
- Missing OpenAI API key behavior: `EmbeddingConfigurationError`
- Local embedding tests: `4 passed`
- Dense retrieval smoke test:
  - `results_returned: 3`
  - `top_chunk_id: chunk_dense_smoke_match`
  - `top_score: 1.000`

Commands run:

```powershell
.\.venv\Scripts\python -m pytest tests\test_embeddings.py
.\.venv\Scripts\python scripts\test_dense_retrieval.py


## Session 23 - Retrieval Metrics

Goal: implement retrieval metrics.

Built:

- Added pure retrieval metric functions for `recall@10` and `nDCG@10`.
- Added a tiny worked example showing why the example nDCG score rounds to about `0.591`.
- Added tests covering recall and nDCG behavior.
- Added a dense retrieval benchmark script that reports real computed metrics only when the real embedding configuration is available.
- Added graceful benchmark output for missing `OPENAI_API_KEY`.

Measured validation:

- Retrieval metric tests: `2 passed`
- Dense benchmark helper test: `1 passed`
- Combined test run: `3 passed`
- Dense retrieval benchmark status without API key:
  - `status: not_run`
  - `mean_recall_at_10: not_measured`
  - `mean_ndcg_at_10: not_measured`

Commands run:

```powershell
.\.venv\Scripts\python -m pytest tests\test_retrieval_metrics.py
.\.venv\Scripts\python scripts\benchmark_dense_retrieval.py
.\.venv\Scripts\python -m pytest tests\test_retrieval_metrics.py tests\test_dense_retrieval_benchmark.py

```

## Session 24 - Elasticsearch BM25 Retrieval

Goal: add Elasticsearch BM25 lexical search.

Dossier input configuration:

- BM25 candidate depth: top 50
- Final BM25 benchmark output: top 10

Built:

- Added `backend/app/bm25_retrieval.py` with BM25 result objects matching dense retrieval format.
- Added Elasticsearch BM25 retrieval over the `llm_eval_chunks` index.
- Added `retrieve_candidates()` for top 50 BM25 candidates.
- Added `retrieve()` for top 10 metric results.
- Added `scripts/index_chunks_to_elasticsearch.py` to index corpus chunks into Elasticsearch.
- Added `scripts/test_bm25_retrieval.py` as a local BM25 smoke test.
- Added `scripts/benchmark_bm25_retrieval.py` for BM25 recall@10 and nDCG@10.
- Added tests for BM25 depth behavior and benchmark label mapping.

Measured validation:

- Elasticsearch connection check: `Elasticsearch connection OK`
- Loaded chunks from file: `9900`
- Indexed chunks in Elasticsearch: `9900`
- BM25 smoke test:
  - `Retrieved candidates: 50`
  - `Retrieved metric results: 10`
- BM25 benchmark on the held-out 120-query labeled retrieval set:
  - `queries_evaluated: 120`
  - `bm25_candidate_depth: 50`
  - `bm25_metric_depth: 10`
  - `mean_recall_at_10: 0.0667`
  - `mean_ndcg_at_10: 0.0377`
- BM25 tests: `2 passed`

Metric integrity notes:

- The measured indexed chunk count is `9900`; the dossier value of about `9600` remains an approximate input note, not the measured count.
- The BM25 benchmark metrics above are measured values from the current local run.
- BM25-only retrieval is expected to differ from dense retrieval because it ranks lexical term matches rather than embedding similarity.

Commands run:

```powershell
python scripts/check_elasticsearch_connection.py
python scripts/index_chunks_to_elasticsearch.py
python scripts/test_bm25_retrieval.py
python scripts/benchmark_bm25_retrieval.py
python -m pytest tests/test_bm25_retrieval.py tests/test_bm25_retrieval_benchmark.py
```


## Session 25 - Hybrid Retrieval with Reciprocal Rank Fusion

Goal: implement reciprocal rank fusion for hybrid retrieval.

Dossier input configuration:

- Dense candidate depth: top 50
- BM25 candidate depth: top 50
- RRF k: 60
- Final hybrid output: top 10

Built:

- Added `backend/app/hybrid_retrieval.py`.
- Added pure reciprocal rank fusion over dense and BM25 ranked candidate lists.
- Added `HybridRetrievalResult` with fused RRF score, dense rank, BM25 rank, text, and metadata.
- Added `HybridRetriever` that calls dense `retrieve_candidates()` and BM25 `retrieve_candidates()` before fusing.
- Added dense `retrieve_candidates()` so dense retrieval can expose top 50 candidates while `retrieve()` still returns top 10 metric results.
- Added `scripts/benchmark_hybrid_retrieval.py` to benchmark dense-only, BM25-only, and hybrid RRF in one run using the same held-out label set and same metric functions.
- Benchmark output includes exact command, label dataset version, corpus version, and retriever config.

Validation:

- Hybrid retrieval tests passed:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_hybrid_retrieval.py`
  - Result: `2 passed`
- Hybrid benchmark helper and retrieval metric tests passed:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_hybrid_retrieval.py tests\test_hybrid_retrieval_benchmark.py tests\test_retrieval_metrics.py`
  - Result: `5 passed`

Benchmark status:

- Command:
  - `.\.venv\Scripts\python.exe scripts\benchmark_hybrid_retrieval.py`
- Status: `not_run`
- Reason:
  - `OPENAI_API_KEY` was not set, so dense retrieval and hybrid retrieval could not be measured.
- Dense-only recall@10: `not_measured`
- Dense-only nDCG@10: `not_measured`
- BM25-only recall@10: `not_measured` in this combined benchmark run
- BM25-only nDCG@10: `not_measured` in this combined benchmark run
- Hybrid recall@10: `not_measured`
- Hybrid nDCG@10: `not_measured`

Metric integrity notes:

- The resume retrieval numbers remain previous claims until measured in the current benchmark.
- Do not claim dense-only recall@10 `0.69`, hybrid recall@10 `0.84`, dense-only nDCG@10 `0.62`, or hybrid nDCG@10 `0.79` as current measured values yet.
- Dense-only and hybrid metrics must be measured on the same 120-query held-out labeled set with the same metric implementation before updating the resume.
- If the measured values differ from the previous resume numbers, update the resume to the measured values.

Design notes:

- Rank fusion combines ranked result lists rather than raw scores.
- RRF score is computed as `sum(1 / (k + rank))` across retrievers.
- `k=60` is a stable default because it reduces over-sensitivity to tiny rank differences while still rewarding items that appear near the top of multiple retrievers.
- Hybrid retrieval can beat dense-only retrieval because dense search handles semantic similarity while BM25 handles exact lexical matches, identifiers, and rare terms.
- Hybrid retrieval tradeoffs include extra latency, more infrastructure, more configuration, and more complex debugging.



## Session 26 - Connect Retrieval to Answer Generation

Goal: connect hybrid retrieval results to RAG answer generation.

Dossier input configuration:

- Retrieve hybrid top 10.
- Generate using about top 4 chunks.
- Use about 2,000 context tokens.
- Store all top 10 retrieved chunk IDs.
- Store actual generation context chunk IDs.
- Save citation fields for faithfulness judging.

Built:

- Added generation context selection with an approximate token budget.
- Added citation metadata fields:
  - `retrieved_chunk_ids`
  - `generation_context_chunk_ids`
  - `generation_context_citations`
- Added a RAG request builder that sends only selected context chunks to the provider.
- Updated the shared RAG prompt to request chunk-ID citations and avoid guessing when context is insufficient.
- Updated local generation script to optionally accept retrieved chunks or a retriever object.
- Added real hybrid retriever factory wiring:
  - OpenAI embeddings
  - Postgres dense retrieval
  - Elasticsearch BM25 retrieval
  - RRF hybrid retrieval
- Added CLI flags:
  - `--use-hybrid-retrieval`
  - `--limit`

Validation:

- Generation tests passed:
  - `python -m pytest tests/test_generation.py`
  - Result: `5 passed`
- Local generation script tests passed:
  - `python -m pytest tests/test_mock_generate_answers_script.py`
  - Result: `7 passed`
- Combined tested path passed:
  - Result observed during session: `9 passed`
- Mock generation without retrieval completed:
  - Run ID: `local_mock_20260802_061445`
  - Cases loaded: `120`
  - Candidate answers saved: `120`
- Hybrid retrieval to mock generation rehearsal completed:
  - Command: `python scripts/mock_generate_answers.py --provider mock --use-hybrid-retrieval --limit 3`
  - Run ID: `local_mock_20260802_063757`
  - Cases loaded: `3`
  - Candidate answers saved: `3`

Metric integrity notes:

- The 3-case hybrid run validates retrieval-to-generation plumbing only.
- Because provider was `mock`, this does not count as real OpenAI or Anthropic candidate generation.
- Do not claim OpenAI/Anthropic RAG candidate generation until real provider runs persist candidate answers.
- Do not claim full 120-case RAG generation from the hybrid run; only 3 cases were run with `--limit 3`.
- Retrieval IDs and generation context IDs are audit fields, not quality metrics.



## Session 27 - Basic Agentic Tool-Calling Evaluation

Goal: add basic agentic tool-calling evaluation.

Built:

- Added `agentic_tool_calling` as an eval task type.
- Added a simple local tool registry in `backend/app/agent_tools.py`.
- Added two deterministic tools:
  - `calculator`
  - `mock_search`
- Added a small agentic tool-calling dataset:
  - `datasets/golden/golden_agentic_tools_v0.1.jsonl`
- Added optional `tool_call` storage on candidate answers.
- Added rule-based agentic grading in `backend/app/agentic_judge.py` for:
  - tool choice
  - tool arguments
  - final answer
- Added a composite agentic judge result that reports all three scores independently.

Validation:

- Existing eval and rule-based judge tests passed:
  - Result: `8 passed`
- Agentic judge tests passed after adding tool-choice grading:
  - Result: `3 passed`
- Agentic judge tests passed after adding argument grading:
  - Result: `5 passed`
- Agentic judge plus rule-based judge tests passed after adding final-answer grading:
  - Result: `9 passed`
- Full agentic judge test file passed after composite pass/fail coverage:
  - Result: `8 passed`
- Agentic dataset loaded successfully:
  - Cases loaded: `2`
  - Case IDs: `AT-001`, `AT-002`

Design notes:

- Tool-calling means a model chooses a named tool, passes structured arguments, receives a tool result, and then produces a final answer.
- Agentic evaluation grades intermediate behavior because a final answer alone can hide important failures.
- Tool choice and tool arguments are graded separately because a model can choose the right tool with wrong inputs, or choose the wrong tool while still producing a lucky final answer.
- Tool argument grading currently uses exact dictionary equality. This is simple and deterministic, but later sessions may add normalization for equivalent arguments such as `18*7` and `18 * 7`.

Metric integrity notes:

- These tests validate local grading logic only.
- The `mock_search` tool is deterministic test infrastructure, not a real search system.
- The calculator and mock-search cases do not measure production agent quality.
- Do not claim real agentic model performance until real provider candidate tool calls are generated, persisted, and judged.


## Session 28 - Manual Review Data Model

Goal: build the manual review data model for dual-judge disagreement cases.

Built:

- Added `ReviewStatus` with `pending`, `reviewed`, and `resolved`.
- Added `ReviewCase` with:
  - `run_id`
  - `case_id`
  - `answer`
  - `judge_a_score`
  - `judge_b_score`
  - `disagreement_reason`
  - `human_label`
  - `final_decision`
  - `status`
- Added validation that judge scores must be between `0.0` and `1.0`.
- Added a migration draft for the `review_cases` table.

Validation:

- Eval run model tests passed:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_eval_run.py`
  - Result: `7 passed`

Design notes:

- Manual review matters because automated judges can disagree or be wrong.
- A reviewer needs the candidate answer, both judge scores, the disagreement reason, and space for a human label and final decision.
- Review queues are common in evaluation systems because humans usually inspect ambiguous or high-impact cases instead of reviewing every answer.
- The later dual-judge validation harness will compare GPT-4o-mini and self-hosted 7B judge outputs, route large disagreements into `review_cases`, and use human decisions as the trusted resolution.

Metric integrity notes:

- No GPT-4o-mini judge validation was run in this session.
- No self-hosted 7B judge validation was run in this session.
- No agreement rate or manual-review routing rate was measured yet.
- Do not claim judge agreement or review-routing percentages until both real judges score the same validation slice and persisted review cases are counted.

## Session 29 - Manual Review API

Goal: expose manual review cases through the API.

Built:

- Added temporary in-memory `REVIEW_CASES` data for API rehearsal.
- Added `GET /review-cases` to list review cases.
- Added `GET /review-cases/{review_case_id}` to fetch one review case.
- Added `PATCH /review-cases/{review_case_id}/decision` to update:
  - `human_label`
  - `final_decision`
- Added `PATCH /review-cases/{review_case_id}/status` to update review workflow state.
- Restricted review status values to:
  - `pending`
  - `reviewed`
  - `resolved`

Validation:

- Manually verified `GET /review-cases/review_case_001` returned the expected review case.
- Manually verified the decision endpoint updated:
  - `human_label: correct`
  - `final_decision: accept`
- Existing test suite passed:
  - Command: `python -m pytest tests`
  - Result: `60 passed`

Design notes:

- A review queue holds cases where automated judging needs human inspection, such as disagreement between two judges.
- Review state should be stored so decisions are auditable, resumable, and available for later regression analysis.
- `human_label` and `final_decision` are separate from `status` because judgment content and workflow state answer different questions.
- The dashboard can later call these endpoints to show a review queue table, review-case detail view, and controls for resolving cases.

Metric integrity notes:

- The review API currently uses in-memory data only.
- Review updates are not durable across server restarts yet.
- No GPT-4o-mini or self-hosted 7B judge agreement was measured in this session.
- No manual-review routing rate was measured in this session.
- The `60 passed` result proves existing tests still pass, but these new review API endpoints do not yet have automated test coverage.

## Session 30 - GPT-4o-mini Judge Rubric and Parser

Goal: build the GPT-4o-mini judge and judge rubric prompt for the 120-answer validation slice.

Built:

- Added `backend/app/gpt4o_mini_judge.py`.
- Added a rubric prompt for:
  - `correctness`
  - `faithfulness`
  - `citation_quality`
- Added structured JSON response format with:
  - `correctness`
  - `faithfulness`
  - `citation_quality`
  - `passed`
  - `explanation`
- Added `GPT4oMiniJudgeOutput` for strict schema validation.
- Added safe JSON parsing with `JudgeOutputParseError`.
- Added `GPT4oMiniJudge`.
- Added retry behavior for malformed judge output.
- Added fail-safe behavior that returns `JudgeScore(status=FAILED)` when parsing still fails.
- Added fake-client tests so retry behavior can be tested without calling the OpenAI API.
- Added `scripts/gpt4o_mini_judge_answers.py` for small validation-slice judge runs.

Validation:

- Parser and judge tests passed:
  - Command: `python -m pytest tests/test_gpt4o_mini_judge.py`
  - Result: `6 passed`
- Broader judge test set passed:
  - Command: `python -m pytest tests/test_gpt4o_mini_judge.py tests/test_rule_based_judge.py tests/test_agentic_judge.py`
  - Result: `17 passed`
- Ran a small GPT-4o-mini smoke test on 3 mock candidate answers:
  - Command: `python scripts/gpt4o_mini_judge_answers.py runs\local_mock_20260802_063757_candidate_answers.jsonl --limit 3`
  - Result: `gpt4o_mini_judge_scores_saved=3`
  - Output: `runs\local_mock_20260802_063757_gpt4o_mini_judge_scores.jsonl`

Design notes:

- An LLM judge grades candidate answers using a rubric instead of exact string matching.
- The rubric separates correctness, faithfulness, and citation quality because an answer can be correct but unsupported, supported but incomplete, or cited poorly.
- Structured JSON is useful for automation but fragile because models can return prose, markdown, missing fields, wrong types, or out-of-range scores.
- Invalid JSON is retried once, then recorded as a failed judge score instead of being silently converted into a metric.
- GPT-4o-mini is scoped to the 120-answer validation slice, not the full bulk judging workload.

Metric integrity notes:

- The 3-answer smoke test used mock candidate answers, so it proves plumbing only.
- The smoke test does not count as real judge validation.
- No GPT-4o-mini versus self-hosted 7B agreement rate was measured in this session.
- No 8K+ bulk judging was performed in this session.
- GPT-4o-mini should not judge the full 8K bulk set if the project claim is reduced API dependency; the self-hosted 7B judge must carry bulk judging.

## Session 31 - Self-Hosted 7B Judge Interface with Mock Endpoint

Goal: build the self-hosted 7B judge interface using a mock endpoint before renting GPU time.

Built:

- Added `backend/app/self_hosted_judge.py`.
- Added `SelfHostedJudgeConfig` with HTTP endpoint configuration:
  - `SELF_HOSTED_JUDGE_URL`
  - `SELF_HOSTED_JUDGE_MODEL`
  - `SELF_HOSTED_JUDGE_TIMEOUT_SECONDS`
  - `SELF_HOSTED_JUDGE_MAX_RETRIES`
  - `SELF_HOSTED_JUDGE_RETRY_BACKOFF_SECONDS`
  - optional `SELF_HOSTED_JUDGE_API_KEY`
- Added `SelfHostedJudge`.
- Reused the GPT-4o-mini judge prompt and output parser so both judges share the same score schema:
  - `correctness`
  - `faithfulness`
  - `citation_quality`
  - `passed`
  - `explanation`
- Added endpoint error handling.
- Added timeout handling.
- Added retry handling for transient HTTP failures:
  - `429`
  - `500`
  - `502`
  - `503`
  - `504`
- Added failed-score behavior that returns `JudgeScore(status=FAILED)` instead of silently converting failures into passing metrics.
- Added `backend/app/mock_self_hosted_judge_server.py`.
- Added an OpenAI-compatible mock endpoint:
  - `/v1/chat/completions`
- Added tests in `tests/test_self_hosted_judge.py`.

Validation:

- Focused judge tests passed:
  - Command: `python -m pytest tests\test_self_hosted_judge.py tests\test_gpt4o_mini_judge.py`
  - Result: `11 passed`
- Re-ran focused tests with pytest cache disabled/localized:
  - Command: `python -m pytest tests\test_self_hosted_judge.py tests\test_gpt4o_mini_judge.py -o cache_dir=runs\pytest_cache`
  - Result: `11 passed`
- Attempted full test suite:
  - Command: `python -m pytest tests -p no:cacheprovider`
  - Result: blocked during collection by missing `openai` package in the active Python environment.

Design notes:

- The self-hosted judge is an HTTP adapter around a judge endpoint, not a separate scoring schema.
- Sharing the GPT-4o-mini schema is important because agreement math, review routing, dashboards, and persistence should compare the same fields across judges.
- vLLM can later expose an OpenAI-compatible HTTP endpoint, so the mock endpoint uses the same `/v1/chat/completions` response shape.
- Building against a mock first tests the contract, parsing, retries, and failure paths before renting a GPU.
- Non-retryable client errors should fail fast; transient server or network errors can be retried.

Metric integrity notes:

- The mock 7B endpoint is test infrastructure only.
- Mock 7B scores are not real judge-validation results.
- No real self-hosted Mistral-7B-Instruct-v0.3-AWQ judge was run in this session.
- No GPT-4o-mini versus real self-hosted 7B agreement rate was measured.
- No throughput, cost, agreement, or manual-review routing percentage from this session should be used as a resume metric.

## Session 32 - Dual-Judge Validation Harness

Goal: build the dual-judge validation harness using GPT-4o-mini and mock 7B.

Built:

- Added `backend/app/dual_judge_validation.py`.
- Added a reusable `run_dual_judge_validation(...)` harness.
- Added support for running two judges on the same `CandidateAnswer` slice.
- Added pass/fail agreement comparison.
- Added correctness score delta comparison with a default threshold of `0.25`.
- Added agreement percentage calculation.
- Added inter-judge Cohen's kappa calculation.
- Added optional judge-vs-human kappa calculation when human labels exist.
- Added disagreement detection.
- Added manual-review routing into `ReviewCase` objects.
- Added validation report models:
  - `DualJudgeCaseResult`
  - `DualJudgeValidationReport`
  - `DualJudgeValidationResult`
- Added `save_validation_artifacts(...)` for:
  - validation report JSON
  - manual review queue JSONL
- Added `scripts/dual_judge_validate.py`.
- Added tests in `tests/test_dual_judge_validation.py`.

Validation:

- Focused dual-judge, self-hosted judge, and GPT-4o-mini judge tests passed:
  - Command: `python -m pytest tests\test_dual_judge_validation.py tests\test_self_hosted_judge.py tests\test_gpt4o_mini_judge.py -p no:cacheprovider`
  - Result: `17 passed`

Design notes:

- Inter-judge agreement measures whether two judges make the same decision on the same answers.
- Agreement does not prove correctness because two judges can agree and both be wrong.
- Single-judge bias is risky because one model's scoring habits can become hidden ground truth.
- Disagreement routing is useful because it focuses human review on unstable or high-risk cases.
- Cohen's kappa adjusts observed agreement for agreement expected by chance.
- Pass/fail agreement and score agreement are separate because judges can agree on the final decision while disagreeing about severity.

Metric integrity notes:

- The harness is real architecture.
- The mock 7B agreement number is only a harness test.
- Mock agreement is not the final measured judge agreement.
- Final real agreement must be measured after GPT-4o-mini and the real self-hosted 7B judge score the same validation answers.
- Do not claim `84%` agreement or a manual-review routing percentage until measured with GPT-4o-mini and the real self-hosted 7B judge on the same 120-answer validation slice.

## Session 33 - Pre-GPU Judge Validation Rehearsal

Goal: rehearse the judge validation pipeline on the real 120-answer validation slice before the GPU window.

Built:

- Added `scripts/rehearse_judge_validation.py`.
- Added a rehearsal slice builder based on:
  - `datasets/labels/retrieval_heldout_120_v0.1.jsonl`
- Added validation that the selected held-out rows are marked:
  - `split=heldout`
  - `labels_created_blind_to_judge_outputs=true`
- Added conversion from the held-out 120-query set into 120 rehearsal `EvalCase` rows.
- Added one label-derived rehearsal candidate answer per held-out query.
- Added a deterministic GPT-4o-mini stand-in for no-cost local rehearsal.
- Added an in-process mock 7B judge using the same `SelfHostedJudge` interface.
- Added report metadata fields to `DualJudgeValidationReport` so mock/non-final numbers are clearly marked.
- Added tests in `tests/test_judge_validation_rehearsal.py`.

Validation:

- Focused rehearsal and judge tests passed:
  - Command: `python -m pytest tests\test_judge_validation_rehearsal.py tests\test_dual_judge_validation.py tests\test_self_hosted_judge.py tests\test_gpt4o_mini_judge.py -p no:cacheprovider`
  - Result: `19 passed`
- Ran the local no-cost rehearsal:
  - Command: `python scripts\rehearse_judge_validation.py --limit 120`
  - Result:
    - `validation_slice_cases=120`
    - `candidate_answers=120`
    - `judge_a=rehearsal-gpt4o-mini-standin-v0`
    - `judge_b=self-hosted-7b-bulk-v0`
    - `pass_fail_agreement_percentage=0.00 (NON-FINAL)`
    - `manual_review_case_count=120 (NON-FINAL with mock 7B)`
- Saved rehearsal artifacts:
  - `runs\judge_validation_rehearsal\judge_validation_rehearsal_20260806_051145_heldout_120_eval_cases.jsonl`
  - `runs\judge_validation_rehearsal\judge_validation_rehearsal_20260806_051145_candidate_answers.jsonl`
  - `runs\judge_validation_rehearsal\judge_validation_rehearsal_20260806_051145_rehearsal_report.json`
  - `runs\judge_validation_rehearsal\judge_validation_rehearsal_20260806_051145_manual_review_queue.jsonl`

Design notes:

- Rehearsal reduces GPU-window risk by testing slice selection, candidate loading, judge invocation, parsing, agreement math, review routing, and artifact saving before paid GPU time.
- The validation slice is for judge agreement, not retrieval-label creation.
- Relevance labels must be created before judge outputs so judge behavior does not contaminate the labeled retrieval set.
- Judge agreement is measured after candidate answers exist.
- GPT-4o-mini and the self-hosted 7B judge must score the same validation answers for agreement to mean anything.
- The real GPU run should keep the same pipeline shape and swap the mock 7B endpoint for the real vLLM endpoint.

Metric integrity notes:

- The 120 held-out query slice is real project input.
- The Session 33 candidate answers are label-derived rehearsal placeholders, not real OpenAI or Anthropic candidate generations.
- The Session 33 GPT-4o-mini path used a deterministic stand-in unless `--use-gpt4o-mini` is intentionally passed.
- The Session 33 7B path used mock 7B, not the real self-hosted Mistral-7B-Instruct-v0.3-AWQ judge.
- The `0.00%` agreement and `120` manual-review cases from the rehearsal are non-final mock numbers.
- Mock 7B agreement is not a resume metric.
- A future `84%` agreement on 120 answers would still have uncertainty and should be described as validation evidence, not universal ground truth.
- Final judge agreement must be measured during the GPU window after swapping in the real self-hosted 7B vLLM endpoint and scoring the same 120 validation answers.

## Session 34 - OpenTelemetry Tracing Basics

Goal: add OpenTelemetry tracing basics and connect trace IDs to eval run IDs.

Built:

- Added OpenTelemetry dependencies to `requirements.txt`:
  - `opentelemetry-api`
  - `opentelemetry-sdk`
- Added `backend/app/tracing.py`.
- Added a basic tracing setup with:
  - `TracerProvider`
  - `ConsoleSpanExporter`
  - `SimpleSpanProcessor`
  - service name `llm-eval-regression-platform`
- Added helper functions:
  - `configure_tracing(...)`
  - `get_tracer()`
  - `current_trace_id()`
  - `format_trace_id(...)`
- Added eval worker spans in `scripts/run_eval_worker.py`:
  - `eval_runner.handle_eval_run`
  - `eval_runner.load_eval_run`
  - `eval_runner.update_eval_run_status`
  - `eval_runner.connect_trace_to_run`
  - `eval_runner.store_eval_run_result`
- Added trace attributes such as:
  - `eval.run_id`
  - `eval.dataset_version`
  - `eval.provider_name`
  - `eval.status`
  - `eval.trace_id`
  - `eval.result_key`
- Added `update_eval_run_trace_id(...)` in `backend/app/queue_jobs.py`.
- Stored the OpenTelemetry `trace_id` on:
  - `eval_run:{run_id}`
  - `eval_run_result:{run_id}`
- Added simple API spans in `backend/main.py`:
  - `api.create_eval_run`
  - `api.get_eval_run`
- Added tests in `tests/test_eval_worker_tracing.py`.
- Updated queue job tests to verify `trace_id` storage.

Validation:

- Installed project dependencies after adding OpenTelemetry:
  - Command: `pip install -r requirements.txt`
  - Result: completed successfully after network approval.
- Focused tracing and queue tests passed:
  - Command: `python -m pytest tests\test_eval_worker_tracing.py tests\test_queue_jobs.py -p no:cacheprovider`
  - Result: `6 passed`
- Attempted full test suite:
  - Command: `python -m pytest tests -p no:cacheprovider`
  - Result: `76 passed`, then blocked by a Windows pytest temp-directory permission issue in tests using `tmp_path`.
- Retried full test suite with workspace-local base temp:
  - Command: `python -m pytest tests -p no:cacheprovider --basetemp runs\pytest_tmp_session34`
  - Result: still blocked by Windows permission cleanup on the pytest temp directory.

Design notes:

- A trace is the full story of one operation.
- A span is one timed step inside that story.
- A trace ID is the observability ID that ties spans together.
- An eval run ID is the business ID that identifies the evaluation run.
- Storing both `run_id` and `trace_id` lets a developer move from product data to trace data during debugging.
- The current console exporter is intentionally simple for local learning.
- Later sessions can replace or add an exporter for Elasticsearch/OpenTelemetry Collector storage.

Metric integrity notes:

- Tracing basics were added and verified locally.
- Console-exported spans are not the same as persisted Elasticsearch trace documents.
- No Elasticsearch trace storage was implemented in this session.
- No `10K+ traces` claim can be made from this work.
- Future trace-count claims must be measured by counting real persisted trace documents in Elasticsearch.

## Session 35 - Six Service-Layer OpenTelemetry Spans

Goal: instrument the six service layers with OpenTelemetry.

The six layers are:

1. gateway
2. retrieval
3. provider
4. judge
5. tool
6. storage

Built:

- Added canonical service-layer names in `backend/app/tracing.py`:
  - `gateway`
  - `retrieval`
  - `provider`
  - `judge`
  - `tool`
  - `storage`
- Added `set_common_span_attributes(...)` so layer spans consistently include:
  - `service.layer`
  - `eval.run_id`
  - `eval.trace_id`
- Added one eval-worker span for each required layer:
  - `gateway.accept_eval_run_job`
  - `retrieval.fetch_context`
  - `provider.generate_candidate_answer`
  - `judge.score_candidate_answer`
  - `tool.execute_agent_tool`
  - `eval_runner.store_eval_run_result`
- Added useful layer attributes:
  - gateway:
    - `messaging.system`
    - `messaging.destination`
    - `eval.job_type`
    - `eval.dataset_version`
    - `eval.provider_name`
  - retrieval:
    - `retrieval.strategy`
    - `retrieval.dense_top_k`
    - `retrieval.bm25_top_k`
    - `retrieval.rrf_k`
    - `retrieval.final_top_k`
  - provider:
    - `llm.provider`
    - `llm.candidate_count`
    - `eval.dataset_version`
  - judge:
    - `judge.primary`
    - `judge.validation`
    - `judge.score_count`
  - tool:
    - `tool.enabled`
    - `tool.call_count`
  - storage:
    - `eval.result_key`
    - `eval.status`
    - `eval.run_found`
- Marked placeholder layers with `eval.layer_status=placeholder` where the current worker does not yet execute the real full pipeline.
- Kept completed storage/gateway spans marked as completed where real worker work exists.
- Added tests that verify the eval worker emits spans for all six service layers.
- Verified the OpenTelemetry `trace_id` is still connected to:
  - `eval_run:{run_id}`
  - `eval_run_result:{run_id}`

Validation:

- Focused tracing and queue tests passed:
  - Command: `python -m pytest tests\test_eval_worker_tracing.py tests\test_queue_jobs.py -p no:cacheprovider`
  - Result: `7 passed`

Design notes:

- Gateway spans show how work entered the system.
- Retrieval spans show what context search strategy was used.
- Provider spans show which model/provider generated candidate answers.
- Judge spans show which judge path scored answers.
- Tool spans show whether agentic tool execution happened.
- Storage spans show what was read or written and where run/result state lives.
- The same `trace_id` across all layer spans lets a developer follow one eval run across service boundaries.

Metric integrity notes:

- Session 35 adds tracing instrumentation shape, not production trace persistence.
- Some layer spans are placeholders because the current eval worker still contains a tiny placeholder pipeline.
- No Elasticsearch trace storage was added in this session.
- No trace-volume claim can be made from these spans.
- Do not claim `10K+ traces` until Elasticsearch contains at least 10,000 real trace documents.

## Session 36 - Export Traces to Elasticsearch

Goal: add an OpenTelemetry Collector export path from the backend to Elasticsearch.

Built:

- Added `opentelemetry-exporter-otlp-proto-grpc` to `requirements.txt`.
- Updated `backend/app/tracing.py` so tracing has two modes:
  - local console export when `OTEL_EXPORTER_OTLP_ENDPOINT` is not set
  - OTLP gRPC export when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- Added OTLP configuration environment variables:
  - `OTEL_EXPORTER_OTLP_ENDPOINT`
  - `OTEL_EXPORTER_OTLP_INSECURE`
- Added `force_flush_traces(...)` for smoke scripts and short-lived tracing runs.
- Added `infra/otel-collector-config.yml`.
- Configured the OpenTelemetry Collector to:
  - receive OTLP over gRPC on `4317`
  - receive OTLP over HTTP on `4318`
  - batch trace data
  - export traces to Elasticsearch
  - write trace span documents into static index `otel-traces`
- Added `otel-collector` to `docker-compose.yml`.
- Wired the backend container to send OTLP spans to:
  - `http://otel-collector:4317`
- Added `scripts/count_trace_documents.py`.
- Added a simple trace-count query that reports:
  - `span_document_count`
  - `unique_trace_count`
- Added `scripts/emit_trace_smoke.py` so a small known trace can be emitted through the collector once Docker is running.
- Added tests in `tests/test_trace_export.py`.

Validation:

- Focused trace export, worker tracing, and queue tests passed:
  - Command: `python -m pytest tests\test_trace_export.py tests\test_eval_worker_tracing.py tests\test_queue_jobs.py -p no:cacheprovider`
  - Result: `11 passed`
- Docker Compose config validation passed:
  - Command: `docker compose config`
  - Result: Compose accepted the `otel-collector` service and mounted collector config.
- Installed the OTLP gRPC exporter:
  - Command: `pip install opentelemetry-exporter-otlp-proto-grpc`
  - Result: install completed.
  - Note: pip reported a global Anaconda environment dependency conflict because `streamlit` requires `protobuf<6`, while the OpenTelemetry exporter installed `protobuf 7.35.1`.
- Attempted to start Elasticsearch and the OpenTelemetry Collector:
  - Command: `docker compose up -d elasticsearch otel-collector`
  - Result: blocked because Docker Desktop / Docker daemon was not running.
- Attempted to count trace documents while Elasticsearch was down:
  - Command: `python scripts\count_trace_documents.py`
  - Result: failed with a clean message that Elasticsearch was not reachable.

Design notes:

- The OpenTelemetry Collector is a telemetry relay.
- The backend sends OTLP spans to the Collector.
- The Collector receives, batches, and exports those spans to Elasticsearch.
- Elasticsearch stores each span as a searchable trace document.
- A trace normally contains multiple span documents, so the honest count should distinguish:
  - span document count
  - unique trace count
- Indexing traces supports dashboard search by fields such as:
  - `trace_id`
  - `eval.run_id`
  - `service.layer`
  - span name
  - provider name
  - judge path
  - storage key

Metric integrity notes:

- The export path was implemented and config-validated.
- Indexed trace documents were not verified in this session because Docker was not running.
- No Elasticsearch trace count was measured in this session.
- No `10K+ traces` claim can be made.
- Trace count should be measured only by querying Elasticsearch after real spans have been exported and indexed.
- `span_document_count` is not the same as `unique_trace_count`; one trace can produce many span documents.

Next verification commands when Docker is running:

```powershell
docker compose up -d elasticsearch otel-collector
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4317"
$env:OTEL_EXPORTER_OTLP_INSECURE = "true"
python scripts\emit_trace_smoke.py
python scripts\count_trace_documents.py
```

## Session 37 - React/TypeScript Dashboard

Goal: build the React/TypeScript dashboard over the existing backend.

Process note:

- The normal tutoring rules (1-3: no direct file edits, no full-project
  generation) were explicitly suspended by me for this session. I asked for the
  frontend to be built directly so I could add real metrics afterwards.
- Metric-integrity rules 17-21 and 40-46 stayed in force and shaped the design.

Built:

- Scaffolded `frontend/` with Vite + React 19 + TypeScript.
- Added `react-router-dom` and a layout route so the shell mounts once.
- Configured a dev proxy in `frontend/vite.config.ts` mapping `/api/*` to
  `http://127.0.0.1:8000/*`.
- Added the provenance type model in `frontend/src/types/provenance.ts`:
  - `MeasuredMetric` carries `value`, `source`, `measuredAt`, optional `command`
  - `PlaceholderMetric` carries a value that means nothing
  - `NotMeasuredMetric` deliberately has **no `value` field**
- Added `frontend/src/data/metricsSnapshot.ts` as the single place every
  displayed number comes from.
- Added `frontend/src/data/claims.ts`, which computes claim verdicts from the
  snapshot instead of storing hand-ticked booleans.
- Added `frontend/src/api/client.ts` as the only `fetch` call site, with typed
  DTOs in `frontend/src/types/api.ts`.
- Added `frontend/src/hooks/useApi.ts` with an `idle | loading | success | error`
  discriminated union and `AbortController` cleanup.
- Added shared components: `AppShell`, `Panel`, `StatTile`, `ProvenanceBadge`,
  `StatusPill`, `ThemeToggle`, and explicit loading/empty/error states.
- Added `frontend/src/components/charts/BarComparison.tsx`, a dependency-free
  HTML bar chart with a table-view toggle.
- Added `frontend/src/styles/tokens.css` and `global.css` with light and dark
  themes.
- Added five pages: Overview, Retrieval, Judges, Runs, Review queue.
- Added `frontend/README.md`.

Snapshot contents transcribed from this build log and verified against files on
disk:

- corpus documents: 1,100
- corpus chunks: 9,900
- chunks indexed in Elasticsearch: 9,900
- held-out labeled queries: 120
- relevant chunk references: 180
- BM25 recall@10: 0.0667 (measured)
- BM25 nDCG@10: 0.0377 (measured)
- dense recall@10 / nDCG@10: not measured
- hybrid recall@10 / nDCG@10: not measured
- mock candidate answers persisted: 849
- full 120-case candidate-answer runs on disk: 7 (all mock provider)
- rule-based judge scores persisted: 120
- GPT-4o-mini judge scores persisted: 3
- instrumented service layers: 6
- bulk judged answers: not measured
- dual-judge agreement: not measured
- manual-review routing rate: not measured
- trace span documents in Elasticsearch: not measured
- vLLM tok/s: not measured
- CI regression gate: not built

Measured validation:

- Production build passed:
  - Command: `npm run build` (runs `tsc -b && vite build`)
  - Result: 42 modules transformed, `dist/assets/index-*.js` 278.64 kB
    (87.21 kB gzip), CSS 15.36 kB (3.71 kB gzip)
- Lint run: `npx oxlint src`
  - Result: 4 `only-export-components` fast-refresh warnings, 0 errors
- All 11 source modules returned HTTP 200 through the Vite transform pipeline.
- Proxied API paths verified with the backend running:
  - `GET /api/health` -> `{"status":"ok"}`
  - `GET /api/eval-runs` -> 1 placeholder row
  - `GET /api/review-cases` -> 1 fixture row
  - `GET /api/eval-runs/nope` -> `{"detail":"Eval run not found"}`
  - `PATCH /api/review-cases/review_case_001/decision` -> updated row
  - `PATCH /api/review-cases/review_case_001/status` -> updated row
  - `PATCH .../status` with an invalid value -> `{"detail":"Invalid review status"}`
  - `POST /api/runs` -> `500` (Redis not running)
- Claim-readiness checklist currently computes **0 of 8** claims backed by a
  measurement.

Bug fixes and debugging notes:

- `npm create vite` failed with `EPERM` writing to the global npm cache; solved
  by pointing `npm_config_cache` at a writable directory.
- `uvicorn backend.main:app` failed with `ModuleNotFoundError: No module named
  'opentelemetry'`. The packages were added to `requirements.txt` in Session 34
  but had never been installed into `.venv`. Installed
  `opentelemetry-api` and `opentelemetry-sdk` into `.venv`. No new dependency
  was introduced; a declared one was satisfied.
- The Vite dev server binds `::1` only, so `curl 127.0.0.1:5173` was refused
  while `curl localhost:5173` worked. Same IPv6/localhost ambiguity recorded in
  Session 15. Browsers are unaffected.
- With the backend stopped, the Vite proxy answers `502` rather than causing
  `fetch` to reject. The client originally reported this as an HTTP error
  ("Request failed (502)"), which points a developer at FastAPI logs that do
  not exist. `502/503/504` are now classified as backend-unreachable and the
  UI prints the uvicorn start command.
- `POST /runs` returns a bare `Internal Server Error` with no JSON `detail`
  when Redis is down. The Runs page now names Redis as the likely cause and
  prints the `docker compose up -d redis` and worker commands.
- Agreement and routing rates are stored as 0-1 fractions to match the Python
  side. A `unit="%"` tile without a formatter would have rendered `0.84` as
  `0.84%`. Fixed by routing those tiles through an `asPercent` formatter and
  passing targets as fractions.
- Three TypeScript errors in `BarComparison.tsx` were the provenance union
  refusing reads of `.value` on a possibly-unmeasured metric. Fixed by
  narrowing explicitly rather than by weakening the type.
- `measuredValue<T>` inferred `T` as `unknown` for `NotMeasuredMetric` inputs
  because that variant offers no inference site, producing `{}` comparison
  errors in `claims.ts`. Fixed with a `T = number` generic default.

Design notes:

- Vite was chosen over Next.js and CRA. Next.js adds SSR, file routing, and API
  routes, none of which are useful when FastAPI is already the API server and
  the dashboard is internal; it would also require a Node process in
  production. The accepted tradeoff is no SSR, so no SEO and a brief blank
  frame on load.
- A dev proxy was chosen over adding `CORSMiddleware` to FastAPI. The proxy
  needs no backend change and cannot leak a permissive `*` origin into
  production. Production builds set `VITE_API_BASE_URL` instead.
- The provenance union makes it a compile error to render a number for an
  unmeasured metric. A `value: number | null` field would not, because
  `value ?? 0` compiles and silently turns a missing measurement into a zero.
- Async state is a four-case union rather than `data`/`loading` booleans, so
  "still loading" and "loaded and genuinely empty" cannot collapse into the
  same render.
- Claim verdicts are computed from the snapshot rather than stored, so the
  checklist cannot drift from the data it describes.
- The bar chart uses a fixed 0-1 domain rather than scaling to the largest
  value present. Auto-scaling would stretch BM25's 0.0667 across the full width
  and make a weak lexical result read as a strong one.
- An unmeasured strategy renders as a hatched, dashed track labeled "not
  measured", not a zero-length bar, which would read as "measured and scored
  nothing".
- Series colour follows the strategy, never its rank, so a filter that changes
  the series count cannot repaint the survivors.
- The categorical palette was validated for colour-vision deficiency before any
  component was written: all-pairs CVD separation ΔE 9.2 light / 9.4 dark,
  normal-vision floor 24.0 light / 20.9 dark. Light-mode aqua measures 2.74:1
  against the chart surface, below the 3:1 bar, so every bar carries a direct
  label and every chart ships a table view as the required mitigation.
- No charting library was added. The only chart form needed is a bar
  comparison, and Recharts would have plotted unmeasured series as zeroes,
  which is the exact failure this dashboard exists to prevent.

Metric integrity notes:

- The dashboard displays measurements; it does not produce any.
- No retrieval, generation, judging, tracing, throughput, or CI metric was
  measured in this session.
- The Runs page renders `total_cases` and `passed_cases` greyed out because
  they are literals in `backend/main.py`, not computed evaluation results.
- The claim-readiness checklist reporting 0 of 8 is a description of the
  current project state, not a dashboard defect.
- Screenshots of this dashboard do not constitute evidence for any resume
  claim. Only the underlying measurements do.

Verification gaps:

- The rendered page was not visually inspected in a browser during this
  session. Build, module transforms, and API paths were verified; layout,
  colour rendering, and responsive behaviour in a real viewport were not.
- The `POST /runs` success path was not exercised because Redis was not
  running. Only its failure path was verified.
- `react-router-dom` carries advisory GHSA-qwww-vcr4-c8h2 (high). It applies to
  RSC server mode only; this is a client-side SPA with no server actions, so it
  does not apply here. Recorded so a future `npm audit` result is not
  misread.

Commands run:

```powershell
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom
npm run build
npx oxlint src
npm run dev
```

Backend used during verification:

```powershell
.\.venv\Scripts\python.exe -m pip install opentelemetry-api opentelemetry-sdk
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Next steps:

- Open the dashboard in a browser and check layout, dark mode, and the table
  view toggle.
- Start Redis and the eval worker, then verify a run moves
  `queued -> running -> completed` on the Runs page.
- Set `OPENAI_API_KEY` and run `scripts/benchmark_hybrid_retrieval.py` so dense
  and hybrid stop rendering as "not measured".
- Investigate whether BM25 recall@10 of 0.0667 understates real quality because
  near-duplicate chunks in the templated corpus outrank the specific chunk IDs
  named in the label file.

## Session 38 - Eval Run List Page

Goal: build the eval run list page.

Built:

- Expanded the backend `GET /eval-runs` response shape in `backend/main.py`.
- Added `EvalRunSummaryResponse` with dashboard-oriented fields:
  - `run_id`
  - `dataset_version`
  - `provider_name`
  - `score`
  - `latency_ms`
  - `created_at`
  - `status`
  - optional `total_cases`
  - optional `passed_cases`
- Kept `score` and `latency_ms` nullable because no real persisted score or
  latency measurement exists yet.
- Updated frontend API type `EvalRunSummary`.
- Rebuilt `frontend/src/pages/RunsPage.tsx` as clean ASCII because the previous
  file contained mojibake text from earlier sessions.
- Added an eval run list table with columns:
  - Run ID
  - Dataset
  - Provider
  - Score
  - Latency
  - Created
  - Status
- Added explicit display for unmeasured fields:
  - `Not measured` for missing score
  - `Not measured` for missing latency
  - `Unknown` for missing created time
- Kept loading state using `LoadingRows`.
- Kept error state using `ErrorState`.
- Kept empty state using `EmptyState`.
- Preserved the session-local queued-runs panel for the Redis-backed `POST /runs`
  polling path.
- Added `tests/test_eval_runs_api.py`.

Validation:

- Backend endpoint test passed:
  - Command: `python -m pytest tests\test_eval_runs_api.py -p no:cacheprovider`
  - Result: `1 passed`
- Frontend production build passed:
  - Command: `npm run build`
  - Working directory: `frontend`
  - Result: build succeeded.

Design notes:

- Frontend state separates loading, success, empty, and error so the dashboard
  does not confuse "still loading" with "there are no runs".
- API data becomes a table by mapping each `EvalRunSummary` object into one row.
- Loading states matter because the backend may be slow or unavailable.
- Error states matter because a failed API call should not look like an empty
  dataset.
- A recruiter should understand that the page is a run-history surface for an
  eval platform: it shows datasets, providers, run status, and where score and
  latency will appear once measured.

Metric integrity notes:

- The page does not invent score or latency.
- `score` and `latency_ms` are currently nullable placeholders.
- No new eval score was measured in this session.
- No latency benchmark was measured in this session.
- The page is real UI plumbing, but the displayed placeholder run is not a
  measured evaluation result.

## Session 39 - Metrics Page and Manual Review Queue Page

Goal: build the metrics page and manual review queue page.

Built:

- Added `backend/app/dashboard_metrics.py`.
- Added `GET /metrics-summary`.
- The metrics endpoint returns the seven dashboard metrics requested:
  - `recall_at_10`
  - `ndcg_at_10`
  - `judge_agreement_percentage`
  - `disagreement_percentage`
  - `judged_answer_count`
  - `eval_run_count`
  - `trace_count`
- Each metric includes:
  - `value`
  - `unit`
  - `status`
  - `source`
  - `measured_at`
  - `command`
  - `note`
- Added a `non_final` metric status for saved mock rehearsal numbers.
- Updated the overview page to fetch metrics from `GET /metrics-summary`
  instead of relying on static dashboard values.
- Updated the metrics page to show loading and error states.
- Updated the metrics page to show a provenance table explaining each value.
- Updated `GET /review-cases` so it includes saved
  `*_manual_review_queue.jsonl` artifacts in addition to the in-memory demo row.
- Added session-local PATCH support for saved artifact review cases by loading
  the selected artifact row into memory before updating.
- Rebuilt the review queue table with the requested fields:
  - Case ID
  - Run ID
  - Judge disagreement
  - Human label
  - Final decision
  - Status
- Kept judge scores in the detail panel, where they support human review
  without crowding the queue table.
- Added `tests/test_dashboard_metrics_api.py`.

Measured/sampled from the new endpoint:

- `recall_at_10`: not measured
- `ndcg_at_10`: not measured
- `judge_agreement_percentage`: `0.0`, non-final mock rehearsal
- `disagreement_percentage`: `100.0`, non-final mock rehearsal
- `judged_answer_count`: `123`, counted from persisted judge-score JSONL rows
- `eval_run_count`: `12`, counted from saved candidate-answer artifact run IDs
- `trace_count`: not measured
- `review_cases`: `121`, from the in-memory row plus saved manual review queue
  artifacts

Validation:

- Backend endpoint tests passed:
  - Command: `python -m pytest tests\test_dashboard_metrics_api.py tests\test_eval_runs_api.py -p no:cacheprovider`
  - Result: `3 passed`
- Frontend production build passed:
  - Command: `npm run build`
  - Working directory: `frontend`
  - Result: build succeeded.

Metric integrity notes:

- The metrics page does not hardcode fake dashboard numbers.
- Retrieval recall@10 and nDCG@10 remain not measured because no
  machine-readable saved retrieval benchmark artifact exists yet.
- The Session 33 judge agreement and disagreement values are shown as
  non-final because they came from a stand-in GPT judge and a mock 7B endpoint.
- Mock agreement is harness evidence only. It is not final judge-validation
  evidence and is not a resume metric.
- Trace count remains not measured because Elasticsearch trace documents have
  not been counted and saved as a trace-count artifact.
- Persisted judge-score count is a real artifact count, but it is not the
  self-hosted bulk-judge count unless those rows were produced by that run.

Concept notes:

- For recruiter scanning, the highest-signal metrics are retrieval quality
  (`recall@10`, `nDCG@10`), judge validation stability, judged-answer volume,
  eval-run volume, and trace availability.
- A simple dashboard should lead with a few tiles and attach provenance, not
  bury the user in charts.
- Misleading metrics are avoided by keeping missing values null, labeling mock
  values non-final, and showing the source artifact for every number.
- Real measured values are better than impressive fake values because they are
  reproducible, defensible in interviews, and safe to put on a resume.

## Session 40 - CI Regression Gates

Goal: implement CI regression gates.

Built:

- Added baseline metric fixture:
  - `metrics/baseline_metrics.json`
- Added current metric fixture:
  - `metrics/current_metrics.json`
- Added regression comparison script:
  - `scripts/compare_regression_metrics.py`
- Added GitHub Actions workflow:
  - `.github/workflows/eval-regression-gate.yml`
- Added regression gate tests:
  - `tests/test_regression_gate.py`
- Added explicit CI path-coverage anchor files:
  - `config/retrieval_config.json`
  - `config/model_provider_config.json`
  - `prompts/judge_rubric.md`

Regression rules:

- Fail if `eval_score` drops by more than `5%`.
- Fail if `latency_ms` increases by more than `15%`.
- Fail if `cost_usd` increases by more than `15%`.
- `eval_score` is treated as higher-is-better.
- `latency_ms` and `cost_usd` are treated as lower-is-better.
- The script exits:
  - `0` when the gate passes
  - `1` when a regression fails the gate
  - `2` when metric files are missing or invalid

CI coverage:

- The GitHub Actions workflow runs for changes to:
  - prompt files under `prompts/**`
  - retrieval/model/provider config under `config/**`
  - judge and evaluation pipeline code under `backend/app/**`
  - backend API code in `backend/main.py`
  - eval/retrieval scripts under `scripts/**`
  - metric files under `metrics/**`
  - the regression gate test itself
  - the workflow file itself

Validation:

- Gate behavior tests passed:
  - Command: `python -m pytest tests\test_regression_gate.py -p no:cacheprovider`
  - Result: `8 passed`
- Committed fixture metrics passed:
  - Command: `python scripts\compare_regression_metrics.py --baseline metrics\baseline_metrics.json --current metrics\current_metrics.json`
  - Result: passed
  - `eval_score`: baseline `0.8`, current `0.79`, regression `1.25%`
  - `latency_ms`: baseline `1000`, current `1100`, regression `10.00%`
  - `cost_usd`: baseline `1`, current `1.1`, regression `10.00%`
- Intentional fake regression failed as expected:
  - Command: `python scripts\compare_regression_metrics.py --baseline runs\test_regression_gate\failing_baseline.json --current runs\test_regression_gate\failing_current.json`
  - Result: failed with exit code `1`
  - `eval_score`: regression `12.50%`
  - `latency_ms`: regression `30.00%`
  - `cost_usd`: regression `40.00%`

Metric integrity notes:

- These metric files are CI gate fixtures, not resume performance metrics.
- The workflow is real GitHub Actions wiring, so this is more than a local
  script.
- A CI gate claim becomes meaningful once the repository is pushed to GitHub
  and GitHub Actions runs this workflow on a branch or pull request.
- The current fixture values demonstrate gate mechanics. Replace them with real
  measured eval metrics before making quality, latency, or cost claims.

Concept notes:

- CI means continuous integration: automated checks run when code changes.
- Regression testing means checking that a new change did not make an important
  metric worse compared with a baseline.
- Eval platforms need gates because prompt, retrieval, model, provider, rubric,
  and pipeline changes can silently reduce quality or increase latency/cost.
- CI failure protects quality by blocking the change before it merges.

## Session 41 - Candidate Answer Run Matrix

Goal: design the candidate answer run matrix for OpenAI/Anthropic candidate
generation before judging.

Built:

- Added candidate generation matrix config:
  - `config/candidate_answer_run_matrix.json`
- Added matrix summarizer and validator:
  - `scripts/summarize_candidate_run_matrix.py`
- Added matrix tests:
  - `tests/test_candidate_answer_run_matrix.py`

Run matrix dimensions:

- Real candidate providers:
  - OpenAI `gpt-4o-mini`
  - Anthropic `claude-3-5-haiku-20241022`
- Primary RAG dataset:
  - `golden_rag_v0.1`
  - `120` cases
- Agentic tool-calling dataset:
  - `golden_agentic_tools_v0.1`
  - `2` cases
- Retrieval mode variation:
  - `dense_top50_context4`
  - `bm25_top50_context4`
  - `hybrid_rrf_k60_top10_context4`
  - `hybrid_rrf_k60_top10_compressed_context4`
  - `tool_calling_no_retrieval` for agentic cases
- Prompt version variation:
  - `rag_prompt_v1`
  - `rag_prompt_v2`
  - `rag_prompt_v3`
  - `rag_prompt_v4`
  - `agentic_prompt_v1`
  - `agentic_prompt_v2`
- Repeat IDs:
  - `repeat_01`
  - `repeat_02`
  - `repeat_03` for the small hybrid calibration block

Scale math:

- Primary RAG matrix:
  - `64` balanced RAG runs from provider x retrieval x prompt x repeat
  - `4` extra hybrid calibration RAG runs
  - `68` primary RAG runs total
  - `120` RAG cases x `68` runs = `8,160` candidate answers
- Agentic tool-calling add-on:
  - `4` runs
  - `2` cases x `4` runs = `8` candidate answers
- Total generation matrix:
  - `72` candidate generation runs
  - `8,168` candidate answers before judging

Provider coverage:

- OpenAI candidate answers:
  - `4,084`
- Anthropic candidate answers:
  - `4,084`
- Mock provider:
  - excluded from real provider-diversity claim
- Self-hosted Mistral:
  - not required as a candidate provider for the current resume scope
  - still scoped as the self-hosted judge

Estimated API cost before running:

- Token assumptions:
  - RAG: about `2,400` input tokens and `350` output tokens per answer
  - Agentic tool-calling: about `1,500` input tokens and `500` output tokens
    per answer
- OpenAI estimated generation cost:
  - `$2.3277`
- Anthropic estimated generation cost:
  - `$13.5584`
- Total estimated generation cost:
  - `$15.89`
- Total estimated generation cost with `20%` buffer:
  - `$19.06`

Validation:

- Matrix validation command passed:
  - Command: `python scripts\summarize_candidate_run_matrix.py --validate`
  - Result:
    - `primary_rag_run_count=68`
    - `agentic_tool_run_count=4`
    - `total_run_count=72`
    - `primary_rag_candidate_answer_count=8160`
    - `agentic_tool_candidate_answer_count=8`
    - `total_candidate_answer_count=8168`
    - `candidate_answer_count[openai]=4084`
    - `candidate_answer_count[anthropic]=4084`
- Matrix tests passed:
  - Command: `python -m pytest tests\test_candidate_answer_run_matrix.py -p no:cacheprovider`
  - Result: `6 passed`

Metric integrity notes:

- This phase only designs candidate generation.
- It does not judge answers yet.
- `8,168` is an expected candidate-answer count from the planned matrix, not a
  persisted candidate-answer count.
- Do not claim `8K+ judged answers` until the self-hosted judge has produced
  at least `8,000` persisted judge-score rows.
- Mock-provider runs do not count toward OpenAI/Anthropic provider diversity.
- The cost numbers are pre-run estimates, not measured spend.

Concept notes:

- A run matrix is the structured set of dataset, provider, model, retrieval,
  prompt, and repeat combinations to execute.
- Candidate generation must happen before judging because judges score persisted
  answers; they cannot score planned answers.
- The OpenAI/Anthropic API wording is earned only when both providers produce
  real persisted candidate answers.
- Self-hosted Mistral-7B is the judge in the current resume scope, not a
  required candidate generator.
- The matrix stays honest by separating primary RAG scale math from small
  agentic coverage and by labeling all counts as expected until artifacts exist.

## Session 42 - Async Candidate Answer Generation Pipeline

Goal: execute the OpenAI/Anthropic candidate answer run matrix through the async
pipeline.

Built:

- Added candidate-generation runtime module:
  - `backend/app/candidate_generation.py`
- Extended `POST /runs` request/response fields for matrix-driven runs:
  - optional deterministic `run_id`
  - `model_name`
  - `task_family`
  - `retrieval_mode`
  - `prompt_version`
  - `repeat_id`
  - `matrix_id`
  - `expected_case_count`
- Extended Redis job payload metadata in:
  - `backend/app/queue_jobs.py`
- Updated the Redis worker in:
  - `scripts/run_eval_worker.py`
- Added bounded worker execution flags:
  - `--max-jobs`
  - `--idle-timeout-seconds`
- Added matrix submission script:
  - `scripts/submit_candidate_run_matrix.py`
- Added candidate-generation status reporter:
  - `scripts/report_candidate_generation_status.py`
- Added candidate-generation pipeline tests:
  - `tests/test_candidate_generation_pipeline.py`
- Saved candidate-generation status report:
  - `docs/results/candidate-generation.md`

Pipeline behavior:

- Matrix rows are submitted through `POST /runs`.
- Each submitted run is enqueued into Redis.
- The worker consumes Redis jobs.
- Real OpenAI/Anthropic jobs call candidate generation.
- Candidate answers are stored as JSONL:
  - `runs/candidate_generation/{run_id}_candidate_answers.jsonl`
- Per-run status is stored as JSON:
  - `runs/candidate_generation/{run_id}_status.json`
- Resume safety:
  - existing completed case IDs are read from the run JSONL
  - already completed answers are skipped
  - the status file is updated after each generated answer
  - a failed case does not erase completed answers

Execution result:

- The balanced mini matrix was completed in the follow-up execution below.
- Final mini-matrix counts:
  - `8` completed runs
  - `960` completed candidate answers
  - `openai: 480`
  - `anthropic: 480`

Validation:

- Focused pipeline tests passed:
  - Command: `python -m pytest tests\test_candidate_generation_pipeline.py tests\test_candidate_answer_run_matrix.py tests\test_queue_jobs.py tests\test_eval_worker_tracing.py -p no:cacheprovider`
  - Result: `15 passed`
- API regression tests passed:
  - Command: `python -m pytest tests\test_eval_runs_api.py tests\test_dashboard_metrics_api.py -p no:cacheprovider`
  - Result: `3 passed`
- Frontend production build passed:
  - Command: `npm run build`
  - Working directory: `frontend`
  - Result: build succeeded
- Matrix validation still passed after correcting the Anthropic model name:
  - Command: `python scripts\summarize_candidate_run_matrix.py --validate`
  - Result:
    - `primary_rag_run_count=68`
    - `agentic_tool_run_count=4`
    - `total_run_count=72`
    - `primary_rag_candidate_answer_count=8160`
    - `agentic_tool_candidate_answer_count=8`
    - `total_candidate_answer_count=8168`
    - `candidate_answer_count[openai]=4084`
    - `candidate_answer_count[anthropic]=4084`
    - `estimated_total_generation_cost_usd=19.28`
    - `estimated_total_generation_cost_with_20_percent_buffer_usd=23.13`

Metric integrity notes:

- The completed mini matrix supports the claim that real candidate answers were
  generated from both OpenAI and Anthropic APIs.
- Do not claim `60+ eval runs` yet.
- Do not claim `8K+ judged answers` yet.
- Candidate generation is complete for the mini matrix only; judging still
  happens later.

Concept notes:

- Long generation scripts must be checkpoint-resumable because thousands of API
  calls can be interrupted by network errors, rate limits, local crashes, or
  budget pauses.
- Failed runs should not force a restart from zero because completed answers are
  already paid for and already useful.
- Candidate generation and judging are separate phases: providers create
  answers first; judges score persisted answers later.
- The honest way to verify thousands of candidate answers is to count completed
  rows in persisted candidate-answer JSONL files and break that count down by
  provider.

## Session 42 Follow-Up - Completed Balanced Mini Matrix

Goal: complete the balanced mini matrix with real OpenAI and Anthropic
candidate-generation runs.

Ran:

- Command:
  - `python scripts\submit_candidate_run_matrix.py --mini-balanced --allow-paid-api`
- Worker commands:
  - `python scripts\run_eval_worker.py --max-jobs 8`
  - `python scripts\run_eval_worker.py --max-jobs 4`
- Providers:
  - `openai`
  - `anthropic`
- Models:
  - `gpt-4o-mini`
  - `claude-haiku-4-5-20251001`
- Retrieval modes:
  - `bm25_top50_context4`
  - `hybrid_rrf_k60_top10_context4`
- Prompt versions:
  - `rag_prompt_v1`
  - `rag_prompt_v2`

Result:

- Mini-matrix run count:
  - `8`
- Mini-matrix completed run count:
  - `8`
- Mini-matrix completed candidate-answer count:
  - `960`
- Mini-matrix completed candidate answers by provider:
  - `openai: 480`
  - `anthropic: 480`
- Redis queue after worker:
  - `eval_run_jobs_length=0`

Updated aggregate report:

- Path:
  - `docs/results/candidate-generation.md`
- Aggregate completed candidate answers:
  - `openai: 480`
  - `anthropic: 490`
  - total: `970`
- Note:
  - The aggregate Anthropic count includes the earlier 10-case Anthropic sample
    plus the 480 completed Anthropic mini-matrix answers.

Metric integrity notes:

- It is now accurate to say the mini matrix produced real candidate answers
  from both OpenAI and Anthropic APIs.
- It is not accurate to claim `60+` completed runs yet.
- It is not accurate to claim `8K+` judged answers yet.
- These are candidate answers only; judging has not happened yet.

## Session 43 - GPU Window Preparation and Mock Rehearsal

Goal: prepare one consolidated AWS GPU window for the real self-hosted 7B judge
work, while rehearsing the full flow locally against mock 7B infrastructure.

Built:

- Added reusable bulk judging module:
  - `backend/app/bulk_judging.py`
- Added checkpoint-resumable bulk judge CLI:
  - `scripts/bulk_self_hosted_judge_answers.py`
- Added local GPU-window rehearsal CLI:
  - `scripts/rehearse_gpu_window.py`
- Added focused checkpoint/resume tests:
  - `tests/test_bulk_judging.py`
- Added cost-aware GPU runbook:
  - `docs/runbooks/gpu-window.md`
- Added required result files:
  - `docs/results/scale-runs.md`
  - `docs/results/vllm-benchmark.md`

Bulk judging behavior:

- Reads persisted candidate-answer JSONL files.
- Skips candidate rows that are not `completed`.
- Skips already completed `(run_id, case_id, judge_name)` scores.
- Appends each judge score to JSONL immediately.
- Writes status checkpoint JSON after every scored answer.
- Keeps failed scores retryable because only completed score keys are treated
  as done.
- Logs progress with `newly_scored`, `skipped`, and `rows_seen`.

Local mock rehearsal:

- Command:
  - `python scripts\rehearse_gpu_window.py --validation-limit 12 --bulk-limit 24 --progress-every 8`
- Result:
  - `gpu_window_rehearsal_completed=true`
  - Mock validation report:
    - `runs\gpu_window_rehearsal\gpu_window_validation_mock_12_validation_report.json`
  - Mock manual review queue:
    - `runs\gpu_window_rehearsal\gpu_window_validation_mock_12_manual_review_queue.jsonl`
  - Mock bulk judge scores:
    - `runs\gpu_window_rehearsal\gpu_window_bulk_mock_20260807_035526_judge_scores.jsonl`
  - Mock bulk status checkpoint:
    - `runs\gpu_window_rehearsal\gpu_window_bulk_mock_20260807_035526_status.json`

Mock scale report:

- Path:
  - `docs/results/scale-runs.md`
- Mock rehearsal counts:
  - Candidate files scanned: `8`
  - Candidate rows seen during this invocation: `26`
  - Eligible completed candidate answers seen: `24`
  - Skipped already judged answers: `0`
  - Newly scored answers in this invocation: `24`
  - Latest completed judge-score count in output: `24`
  - Latest failed judge-score count in output: `0`
- Important:
  - These are mock 7B rehearsal counts, not real self-hosted judge results.

vLLM benchmark report:

- Path:
  - `docs/results/vllm-benchmark.md`
- Current status:
  - Benchmark not measured yet.
  - Output tok/s at concurrency `16` is not measured yet.

GPU runbook commands included:

- vLLM serving command for:
  - `Mistral-7B-Instruct-v0.3-AWQ`
  - `AWQ`
  - `max_model_len=4096`
  - `gpu_memory_utilization=0.90`
  - port `8001`
- Health checks:
  - `/health`
  - `/v1/models`
- Real validation-slice command:
  - `scripts/dual_judge_validate.py`
- Real bulk judging command:
  - `scripts/bulk_self_hosted_judge_answers.py`
- Dedicated vLLM benchmark command:
  - `vllm bench serve ... --max-concurrency 16`
- Teardown checklist.

Validation:

- Focused tests passed:
  - Command:
    - `python -m pytest tests\test_bulk_judging.py tests\test_self_hosted_judge.py tests\test_dual_judge_validation.py tests\test_judge_validation_rehearsal.py -p no:cacheprovider -o cache_dir=runs\pytest_cache_session43`
  - Result:
    - `15 passed`

Measurement-boundary notes:

- Mock 7B numbers are useful for rehearsal only.
- Mock 7B numbers are not final judge-validation results.
- Bulk judged-answer count belongs in:
  - `docs/results/scale-runs.md`
- Dedicated vLLM tok/s belongs in:
  - `docs/results/vllm-benchmark.md`
- Do not say `145 tok/s across 8K+ bulk-judged answers` unless the bulk
  judging run itself logs sustained output tok/s over the whole bulk run.
- Without that bulk-run instrumentation, use semicolon wording:
  - `sustaining 145 tok/s at concurrency 16; bulk-judged 8K+ answers on the same vLLM setup`

## Session 44 - Real AWS T4 Self-Hosted Judge Window

Goal: run the real self-hosted 7B judge work in one consolidated AWS
`g4dn.xlarge` / T4 window without leaving idle resources running.

Measured:

- Instance type: `AWS g4dn.xlarge`
- GPU: `Tesla T4, 15360 MiB`
- Model source: `solidrust/Mistral-7B-Instruct-v0.3-AWQ`
- Served model name: `mistral-7b-instruct-v0.3-awq`
- Quantization: `AWQ`
- Serving runtime: `vLLM 0.27.0` via `vllm/vllm-openai:latest`
- vLLM settings:
  - `max_model_len=4096`
  - `gpu_memory_utilization=0.90`

Real validation slice:

- Artifact:
  - `runs/gpu_window/real_7b_validation_report.json`
- Validation cases: `120`
- GPT-4o-mini use: validation slice only
- Self-hosted judge: Mistral-7B-Instruct-v0.3-AWQ
- Pass/fail agreement: `100.00%`
- Score agreement at threshold `0.25`: `92.50%`
- Manual-review routed cases: `9`
- Inter-judge kappa: `1.00`

Real bulk judging:

- Artifact:
  - `runs/self_hosted_bulk_judging/self_hosted_7b_bulk_20260811_061841_judge_scores.jsonl`
- Status checkpoint:
  - `runs/self_hosted_bulk_judging/self_hosted_7b_bulk_20260811_061841_status.json`
- Candidate files scanned: `8`
- Candidate rows seen: `964`
- Eligible completed candidate answers: `960`
- Newly scored answers: `960`
- Completed judge scores: `960`
- Failed judge scores: `0`
- Bulk judging started:
  - `2026-08-11T06:18:41.758408+00:00`
- Bulk judging finished:
  - `2026-08-11T07:00:12.419631+00:00`

Dedicated vLLM benchmark:

- Artifact:
  - `runs/vllm_benchmark/mistral_7b_awq_t4_c16_n64.json`
- Benchmark prompts: `64`
- Max concurrency: `16`
- Input tokens: `131,320`
- Generated tokens: `16,384`
- Duration: `291.63` seconds
- Successful requests: `64`
- Failed requests: `0`
- Sustained output throughput: `56.18 tok/s`
- Peak output throughput: `144.00 tok/s`

AWS teardown:

- EC2 instance was terminated.
- Temporary security group was deleted.
- Temporary EC2 key pair was deleted.
- Local temporary `.pem` file was deleted.
- Final EC2 check showed no pending, running, stopping, or stopped instances in
  `us-west-1`.

Metric integrity notes:

- Do not claim `145 tok/s sustained`; the measured sustained benchmark result
  was `56.18 output tok/s`.
- `144.00 tok/s` was only peak output throughput in the dedicated benchmark.
- Do not claim `8K+ judged answers`; this run measured `960`.
- Bulk judged-answer count and vLLM benchmark throughput are separate
  measurements.

## Session 45 - Scale Number Reconciliation

Goal: reconcile current resume scale targets against actual persisted project
artifacts.

Resume story targets checked:

- `60+ eval runs`
- `8K+ candidate answers`
- `8K+ judged answers`
- `10K+ traces`

Measured production counts:

- Production eval run artifacts: `8`
- Full completed 120-case production runs: `4`
- Production completed candidate answers: `960`
- Failed candidate rows: `4`
- Production candidate answers by provider:
  - OpenAI: `480`
  - Anthropic: `480`
- Bulk judged answers: `960`
- Failed bulk judge scores: `0`
- Elasticsearch trace documents: `0`
- Unique Elasticsearch traces: `0`

Additional artifact count:

- All candidate artifacts including the 10-row Anthropic sample: `970`
- The sample run should not be used to support the production scale claim.

How counts were produced:

- Candidate counts were measured from:
  - `runs/candidate_generation/*_candidate_answers.jsonl`
- Production scope excluded:
  - `cgen_sample__...`
- Judged-answer count was measured from:
  - `runs/self_hosted_bulk_judging/self_hosted_7b_bulk_20260811_061841_judge_scores.jsonl`
- Trace count was checked by starting local Elasticsearch and querying the
  expected `otel-traces` index.
- The `otel-traces` index did not exist.
- Elasticsearch did contain `llm_eval_chunks` with `9,900` documents, but those
  are retrieval chunk documents, not trace documents.

Resume reconciliation:

- `60+ eval runs`: does not match; actual production run artifacts are `8`.
- `8K+ candidate answers`: does not match; actual production completed
  candidate answers are `960`.
- `8K+ judged answers`: does not match; actual judged answers are `960`.
- `10K+ traces`: does not match; actual Elasticsearch trace documents are `0`.
- `OpenAI/Anthropic APIs`: supported, because both providers produced real
  completed candidate answers.

Safer resume wording:

- `Ran 8 real OpenAI/Anthropic eval configurations over 960 candidate answers,
  then bulk-judged 960 answers with a self-hosted
  Mistral-7B-Instruct-v0.3-AWQ judge on AWS g4dn.xlarge/T4.`

Concept notes:

- Repeated runs support regression testing when each run changes a meaningful
  axis such as provider, model, retrieval mode, prompt version, dataset version,
  or repeat seed.
- Meaningless benchmark inflation happens when duplicate or fake runs are added
  only to raise counts.
- A legitimate run needs a defined config, real candidate generation, persisted
  output rows, status metadata, and reproducible inputs.
- Candidate-answer count and judged-answer count are different because answers
  must be generated before they can be scored.
- Trace count depends on real instrumentation exporting spans to Elasticsearch;
  configured tracing alone is not the same as persisted trace documents.

## Session 46 - Recruiter README Polish

Goal: polish the README for a fast recruiter scan and a deeper hiring-manager
review.

Updated:

- Replaced the initial README skeleton with a portfolio-style project summary.
- Added an architecture diagram section using Mermaid.
- Added key features, local run instructions, evaluation methodology,
  retrieval benchmark status, candidate run matrix status, judge validation,
  tracing, Redis worker, CI gate, limitations, and lessons learned.
- Added a measured-metrics table using only supported results from result
  artifacts and reconciliation notes.

Metric integrity notes:

- Did not claim `60+ eval runs`; the measured production run-artifact count is
  `8`.
- Did not claim `8K+ candidate answers`; the measured production completed
  candidate-answer count is `960`.
- Did not claim `8K+ judged answers`; the measured self-hosted judged-answer
  count is `960`.
- Did not claim `10K+ traces`; the measured Elasticsearch trace-document count
  is `0`.
- Did not claim `145 tok/s sustained`; the measured sustained vLLM benchmark at
  concurrency `16` is `56.18 output tok/s`, while `144.00 tok/s` is only the
  measured peak output throughput.

Remaining presentation gap:

- Dashboard screenshots are not yet committed. The README names the intended
  screenshot set and keeps the status honest until image artifacts exist.

## Session 47 - Fixture Defect Diagnosis and Kappa Correction

Goal: before publishing the repository, measure why retrieval recall is low and
why the dual-judge slice reported perfect agreement.

Built:

- Added `scripts/analyze_corpus_duplication.py` to measure duplicate chunk text
  and the recall ceiling those duplicates impose on the label set.
- Added `scripts/recompute_validation_report.py` to re-derive validation summary
  fields from persisted per-case scores without re-running any judge.
- Added `.env.example` documenting every environment variable the code reads.
- Hardened `.gitignore` for `node_modules/`, `dist/`, and pytest temp dirs.

Measured - corpus duplication:

- Command: `python scripts/analyze_corpus_duplication.py`
- Total chunks: `9,900`
- Distinct normalized texts: `2,262`
- Duplication factor: `4.38x`
- Largest duplicate cluster: `330` byte-identical chunks
- Chunks in a cluster of size 1: `2,200`
- Labeled chunks sitting in a cluster larger than 1: `180 of 180`
- Cluster size of labeled chunks: min `110`, median `110`, max `330`
- Theoretical max recall@10 given these labels: `0.0846`

Interpretation:

- Measured BM25 recall@10 was `0.0667`, which is 79% of the `0.0846` ceiling the
  fixture allows. BM25 is behaving correctly; the fixture is the limiting factor.
- The resume target of recall@10 `0.84` is not merely unmeasured, it is
  arithmetically unreachable on this label set.
- The `2,200` cluster-size-1 chunks are unique only because the document title
  embeds a document number. Their body text is identical boilerplate, so
  relabeling cannot repair this. The corpus must be regenerated with genuinely
  document-specific facts before any retrieval quality claim is meaningful.
- All `180` labels are grade 2, so the label set is binary in substance and
  nDCG@10 currently carries no more information than recall@10.

Fixed - Cohen's kappa on a single-category slice:

- `calculate_cohens_kappa_from_pairs` returned a hardcoded `1.0` when expected
  agreement was `1.0`. That case means both raters used one category, where
  kappa is undefined; returning `1.0` manufactured a perfect-agreement signal.
- The function now returns `None`.
- Added `judge_a_pass_rate`, `judge_b_pass_rate`, and `agreement_is_degenerate`
  to `DualJudgeValidationReport` so a degenerate slice is visible in every report.
- Added a regression test covering the all-fail and all-pass label cases.
- Command: `python -m pytest tests/test_dual_judge_validation.py tests/test_judge_validation_rehearsal.py -p no:cacheprovider`
- Result: `9 passed`

Corrected artifact:

- Command: `python scripts/recompute_validation_report.py runs/gpu_window/real_7b_validation_report.json --write`
- Stored `inter_judge_kappa`: `1.0`
- Recomputed `inter_judge_kappa`: `None`
- `judge_a_pass_rate`: `0.0000`
- `judge_b_pass_rate`: `0.0000`
- `agreement_is_degenerate`: `true`

Measured - free metrics derived from existing artifact timestamps:

- Bulk judging sustained throughput: `23.2` judgments/min over 960 answers in
  `41.5` minutes.
- Bulk judging per-answer latency: p50 `2.62s`, p95 `3.37s`, max `3.78s`.
- 1/p50 equals the observed throughput, confirming the bulk run executed at
  concurrency `1`, not `16`. It must not be attributed to the concurrency-16
  benchmark.
- End-to-end per-case pipeline latency, p50: `gpt-4o-mini` `1.95s`,
  `claude-haiku-4-5` `2.16s`.
- Hybrid RRF costs roughly `0.65-0.90s` p50 over BM25-only.
- vLLM total token throughput at concurrency 16: `506.48 tok/s` (the run was
  prefill-heavy at 2,052 input vs 256 output tokens per request, which is why
  output throughput reads as `56.18 tok/s`).

Metric integrity notes:

- No new model, judge, or retrieval measurement was performed in this session.
  Every number above is either derived from persisted artifacts or recomputed
  from persisted per-case scores.
- The retrieval benchmark remains not meaningful until the corpus is regenerated.
- The dual-judge slice does not support a judge-agreement claim.

Open work, in order:

1. Regenerate the corpus with per-document distinguishing facts.
2. Rebuild the RAG golden set so questions are answerable from that corpus.
3. Re-label, re-index, then re-run the retrieval benchmark.
4. Re-run the dual-judge slice for a non-degenerate agreement number.
5. Run CI on GitHub so the regression gate has actually executed.

## Session 48 - Fixture Repair: Corpus, Labels, Golden Set, Retrieval Routing

Goal: repair the four fixture defects measured in Session 47 so retrieval and
judging measure real behaviour.

### 1. Corpus regenerated with document-specific facts

Rewrote `scripts/generate_synthetic_corpus.py`. The previous version
interpolated only `{category}` and `{number}` into a fixed template. Each
document now carries values that appear in no other document: a unique error
code, config key, CLI invocation, metric name, runbook reference, workspace,
owning team, and ten numeric thresholds. Generation stays deterministic - every
value derives from the document's global index, so re-running reproduces the
corpus byte for byte.

Measured, before and after:

| | Before | After |
|---|---:|---:|
| Documents | 1,100 | 1,100 |
| Chunks | 9,900 | 8,926 |
| Distinct chunk texts | 2,262 | 8,926 |
| Duplication factor | 4.38x | 1.00x |
| Largest duplicate cluster | 330 | 1 |

Commands:

```powershell
python scripts/generate_synthetic_corpus.py --clean
python scripts/chunk_corpus.py
python scripts/analyze_corpus_duplication.py
```

### 2. Retrieval labels regenerated and genuinely graded

Added `scripts/generate_retrieval_labels.py`, producing
`datasets/labels/retrieval_heldout_120_v0.2.jsonl`. Labels are derived rather
than asserted: the script knows which fact answers each query, then searches the
corpus for the chunk that actually contains it, and raises if the anchor is
absent. Relevance is graded 2 for the chunk holding the answer and 1 for a
same-document chunk sharing the topic without answering.

- Labeled queries: `120`, balanced 15 per category cell across 8 cells
- Relevant chunk references: `382`
- Relevance 2: `202`; relevance 1: `180`; unknown chunk IDs: `0`
- Strict validator: passed

The v0.1 label file was deleted rather than kept. Its chunk IDs still existed
after regeneration but pointed at different text, so it would have silently
produced wrong benchmark numbers.

### 3. Measured retrieval on the repaired fixture

- Command: `python scripts/benchmark_bm25_retrieval.py`
- `queries_evaluated: 120`
- `mean_recall_at_10: 0.7417` (was `0.0667`)
- `mean_ndcg_at_10: 0.8300` (was `0.0377`)

The theoretical recall@10 ceiling rose from `0.0846` to `1.0000`, so this is the
first BM25 measurement on this project that reflects retrieval quality rather
than fixture duplication.

Dense and hybrid remain not measured; both need `OPENAI_API_KEY` to embed 8,926
chunks. That is the one remaining paid step and it was deliberately not run.

### 4. Corpus-grounded golden RAG dataset

Added `scripts/generate_golden_rag_dataset.py`, producing
`datasets/golden/golden_rag_v0.2.jsonl`. Every answerable question targets a
fact verified present in exactly one document; the script fails if an expected
answer is not found in the corpus.

- Cases: `120`
- Answerable from corpus: `108`
- Expecting abstention: `12`
- Categories: exact_fact 27, single_hop 36, specificity 18, no_answer_abstention
  12, distractor_robustness 9, lexical_gap 9, multi_hop 9

The abstention rows are deliberate. Without questions whose answers the corpus
does not contain, a judge cannot separate a model that retrieves well from one
that fabricates confidently.

`golden_rag_v0.1.jsonl` was left in place. Versioned datasets should be
immutable, and its 95 non-RAG rows remain valid for the dimensions they test.
Only its 25 `rag_qa` rows were mismatched, and v0.2 supersedes those.

### 5. Retrieval routing decided per case

`build_request_for_case` previously applied retrieval to every case in a run
configured `task_family="rag"`. Added `case_requires_retrieval(case)`: only
`rag_qa` cases receive retrieved context, and a dataset row may override with an
explicit `requires_retrieval` metadata flag. This is what stopped support
runbook chunks being handed to arithmetic questions.

Added three tests covering the routing rule, the metadata override, and the
guarantee that a non-retrieval case never invokes the retriever.

### Validation

- Full suite: `python -m pytest tests -p no:cacheprovider` -> `112 passed`
- Frontend production build: `npm run build` -> succeeded
- Fixed `tests/test_judge_validation_rehearsal.py`, which hardcoded a chunk ID
  from the old label set. It now derives the expected chunk from the label file
  so fixture regeneration cannot break it.

### Metric integrity notes

- `0.7417` / `0.8300` are measured BM25 results on the repaired fixture. They
  are not dense or hybrid results and must not be reported as such.
- The resume target of recall@10 `0.84` was arithmetically unreachable on the
  old fixture (ceiling `0.0846`). It is now reachable in principle but has not
  been measured for any retriever.
- No judge run happened in this session. The recorded dual-judge slice is still
  degenerate; re-running it needs a GPU window.
- Elasticsearch trace documents remain `0`.

### Open work

1. Run dense and hybrid retrieval benchmarks (needs `OPENAI_API_KEY`).
2. Re-run the dual-judge validation slice on `golden_rag_v0.2` for a
   non-degenerate agreement number.
3. Export real spans and count persisted Elasticsearch trace documents.
4. Push to GitHub so the CI regression gate actually executes.

## Session 49 - Dense Embeddings and the Three-Way Retrieval Benchmark

Goal: embed the regenerated corpus and measure dense, BM25, and hybrid RRF on
the same held-out query set.

Built:

- Added `scripts/embed_chunks.py`. Checkpoint-resumable by construction: pending
  work is derived from `WHERE embedding IS NULL` in the database rather than a
  local progress file that can drift. Each batch commits before the next request,
  so an interruption costs at most one batch.
- Added `--estimate-only` so cost is visible before any paid call.
- Added a machine-readable benchmark artifact at
  `runs/retrieval_benchmark/hybrid_retrieval_benchmark.json`. Session 39 reported
  retrieval as not measured because no such artifact existed; the dashboard now
  reads it.
- Added per-facet score breakdowns (match_type, hop_type, difficulty) to the
  benchmark, since a single mean hides the dense/lexical tradeoff.
- Fixed `benchmark_hybrid_retrieval.py` and `benchmark_dense_retrieval.py`, which
  never called `load_dotenv()`. This is why Session 25 recorded `status: not_run`
  with "Missing OPENAI_API_KEY" even though the key was present in `.env`.

Measured - embedding run:

- Chunks embedded: `8,926` of `8,926`
- Model: `text-embedding-3-small`, 1536 dimensions
- Approx tokens: `1,398,713`
- Estimated cost: `$0.028`
- Wall time: `474.4s`
- Failures: `0`

Measured - three-way retrieval benchmark:

- Command: `python scripts/benchmark_hybrid_retrieval.py`
- Queries: `120`; dense/BM25 candidate depth `50`; RRF k `60`; metric depth `10`

| Strategy | recall@10 | nDCG@10 |
|---|---:|---:|
| BM25 only | 0.7417 | 0.8300 |
| Hybrid RRF | 0.5782 | 0.5097 |
| Dense only | 0.0663 | 0.0732 |

Recall@10 by match type:

| Query type | Dense | BM25 | Hybrid |
|---|---:|---:|---:|
| exact-term | 0.0250 | 0.8667 | 0.7333 |
| semantic/paraphrase | 0.1075 | 0.6167 | 0.4231 |

Finding: **hybrid retrieval reduces quality on this corpus.** BM25 alone is the
best retriever, and fusing dense into it costs 0.16 recall@10.

Dense is not broken. Verified directly: a query consisting of a chunk's own text
returns that chunk at rank 1 with score `0.9555`, clear of the next result at
`0.8499`. The failure is a corpus property. Every document is the same runbook
template describing a different procedure, so the Escalation section of all 1,100
documents reads near-identically apart from its embedded values. For the query
"What is the escalation acknowledgement target for error ATL-4100?" the top five
dense hits are all `chunk_0005` from five different documents, scored `0.6554`,
`0.6515`, `0.6496`, `0.6493`, `0.6492` - effectively tied. Embeddings capture
topic; here the topic is identical and the discriminating signal is a rare
identifier, which is BM25's strength. RRF then dilutes a good lexical ranking
with a near-uninformative dense one.

Metric integrity notes:

- The resume claim "lifted recall@10 from 0.69 to 0.84 over a dense-only baseline
  using hybrid retrieval" is now measured and the direction is **wrong**. Dense
  measures `0.0663`, BM25 `0.7417`, hybrid `0.5782`. Hybrid does not beat the
  best single retriever here and must not be claimed to.
- These numbers describe this synthetic corpus. A heterogeneous corpus with real
  topical variety would give dense far more to work with. The finding is not a
  general claim about hybrid retrieval.
- Corpus regeneration is the reason BM25 moved from `0.0667` to `0.7417`, not any
  change to the retriever.

Validation:

- Full suite: `python -m pytest tests -p no:cacheprovider` -> `112 passed`
- Frontend production build: succeeded
- Updated `tests/test_dashboard_metrics_api.py`, which asserted
  `recall_at_10 == "not_measured"`. That pinned a run state rather than an
  invariant and failed the moment a benchmark succeeded. It now asserts that a
  measured metric carries a value and a source, and an unmeasured one carries no
  value.

Open work:

1. Re-run the dual-judge validation slice on `golden_rag_v0.2` (needs a GPU window).
2. Export real spans and count persisted Elasticsearch trace documents.
3. Push to GitHub so the CI regression gate actually executes.
4. If a dense contribution matters, the corpus needs genuine topical variety
   rather than one template with substituted values.
