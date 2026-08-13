# Claims and Evidence

Every headline claim made about this project, the artifact that backs it, and the
scope it is valid within. A claim that cannot name an artifact does not belong here.

Each entry records four things:

- **Claim** — the exact wording that may be used.
- **Evidence** — the measured numbers and the file they come from.
- **Scope** — what the claim does *not* cover.
- **Must not say** — the stronger version that the evidence does not support.

Status legend: **Verified** (artifact-backed) · **Partial** (some parts supported) ·
**Unsupported** (no artifact).

---

## 1. Retrieval — hybrid RRF over pgvector dense + Elasticsearch BM25

**Status: Verified, scoped to BEIR SciFact.**

### Claim

> Tuned reciprocal rank fusion over pgvector dense + Elasticsearch BM25 on BEIR
> SciFact, selecting k and candidate depth on the 809-query train split and
> confirming on 300 held-out queries: hybrid reached recall@10 0.878 / nDCG@10
> 0.739 against dense-only 0.854 / 0.716 and BM25-only 0.784 / 0.661 — and
> identified candidate depth, not k, as the dominant RRF parameter.

### Evidence

Held-out SciFact test split, 300 queries, config `k=1, depth=20` selected on the
809-query train split and never tuned on test:

| Strategy | recall@10 | nDCG@10 |
|---|---:|---:|
| BM25 only | 0.7843 | 0.6606 |
| Dense only | 0.8536 | 0.7164 |
| Hybrid RRF | 0.8777 | 0.7388 |

Lift over dense-only: +2.8% recall@10, +3.1% nDCG@10.
Lift over BM25-only: +11.9% recall@10, +11.8% nDCG@10.

Artifacts:

- `runs/retrieval_benchmark/scifact_rrf_sweep.json` — full 36-cell grid, test split
- `runs/retrieval_benchmark/scifact_train_rrf_sweep.json` — tuning grid, train split
- `runs/retrieval_benchmark/beir_scifact_benchmark.json` — default-config run
- `datasets/beir/scifact/labels.jsonl` — 339 human relevance judgments

Reproduce:

```powershell
python scripts/load_beir_dataset.py --dataset scifact
python scripts/index_chunks_to_elasticsearch.py --chunks datasets/beir/scifact/chunks.jsonl --index beir_scifact_chunks --recreate
python scripts/import_corpus_to_postgres.py --chunks datasets/beir/scifact/chunks.jsonl --from-chunks-only --truncate
python scripts/embed_chunks.py
python scripts/sweep_rrf_parameters.py --labels datasets/beir/scifact/labels.jsonl --index beir_scifact_chunks --result runs/retrieval_benchmark/scifact_rrf_sweep.json
```

### Scope

The claim is about **SciFact only** and says nothing about generality. That is
deliberate, because the result does not generalise:

| Corpus | Best single | Hybrid vs best single |
|---|---|---|
| Synthetic support corpus | BM25 | below — lands between the two inputs |
| BEIR SciFact | Dense | above: +2.8% recall, +3.1% nDCG |
| BEIR NFCorpus | Dense | tied: +0.1% recall, −0.3% nDCG |

The tuned depth did not transfer either: SciFact prefers depth 10–20, NFCorpus
50–100. Candidate depth dominates `k` on both, but its best value belongs to the
dataset.

A fourth corpus, **SQuAD v2**, is the cleanest fusion result and needed no tuning at
all — it uses the configured defaults (`k=60`, `depth=50`), so there is no
selection-on-test concern:

| Strategy | recall@10 | nDCG@10 |
|---|---:|---:|
| BM25 only | 0.9417 | 0.8808 |
| Dense only | 0.9583 | 0.8310 |
| **Hybrid RRF (default config)** | **0.9833** | **0.8991** |

Hybrid beats both on both metrics: +0.0250 recall over dense, +0.0183 nDCG over BM25.
The mechanism is visible in the baselines — **dense wins recall while BM25 wins nDCG**,
so the two are genuinely complementary rather than one dominating. That is precisely
the condition under which rank fusion should help, and it does.

Caveat: this is an easier retrieval task than the BEIR sets. The corpus is 1,204
paragraphs with one relevant paragraph per question, so absolute scores near 0.95 are
expected and are not comparable to SciFact or NFCorpus.

### The pattern across four corpora

| Corpus | Baselines | Hybrid vs best single |
|---|---|---|
| Synthetic support corpus | BM25 dominates | below — dragged down by a near-uninformative dense ranking |
| BEIR SciFact | Dense dominates | above only after tuning depth |
| BEIR NFCorpus | Dense dominates | tied |
| SQuAD v2 | **complementary** — dense wins recall, BM25 wins nDCG | **above both, untuned** |

The generalisation supported by all four:

> Reciprocal rank fusion beats both of its inputs when they are complementary, and
> tracks the stronger one when either dominates. It never requires knowing in advance
> which retriever suits the query mix.

That is the honest version of a fusion claim — and it explains *when* to expect a gain,
which a bare number does not.

### A better golden set for generation and judging

The synthetic golden sets carry the weakness the synthetic corpus had: this project wrote
both the questions and the answers. `scripts/load_squad_dataset.py` samples from SQuAD v2
instead — human-written questions, human-written answers, and genuinely adversarial
unanswerable cases.

`SQ-001` shows why those matter: *"What percentage of students enroll in public primary
school in the Philippines?"*, drawn from the **Private school** article. It reads as
answerable and is not. A synthetic abstention case ("what is the on-call phone number") is
obviously unanswerable and tests almost nothing; a SQuAD adversarial question separates a
model that reads its context from one that pattern-matches.

- 120 sampled questions (seeded, reproducible): 80 answerable, 40 requiring abstention
- 1,204 paragraphs as the corpus
- Registered as `golden_squad_v2_sampled` in `DATASET_PATHS`

### Must not say

- ❌ *"Hybrid retrieval beats both dense and BM25"* — unscoped, and true only where the
  retrievers are complementary. NFCorpus refutes the unscoped form.
- ❌ *"Lifted recall@10 from 0.69 to 0.84 using hybrid retrieval"* — never measured
  on any corpus. On SciFact dense alone reaches 0.8536, so that magnitude comes from
  the embedding model, not from fusion.
- ❌ *"k=60 is the tuned value"* — k=1 won on SciFact; k=5 on NFCorpus. Standard
  practice is k=60, and neither dataset chose it.
- ❌ Comparing numbers across corpus versions. The synthetic corpus BM25 figure moved
  from 0.0667 to 0.7417 to 0.3505 with no retriever change at all, purely from
  fixture differences.

### Interview answer

> "I got hybrid beating both retrievers on SciFact. Ran NFCorpus to check it and it
> tied instead — the tuned depth didn't transfer either. So the claim I can defend
> is that fusion matches the stronger retriever without knowing in advance which one
> it is, not that it wins."

### Notes for a reader skimming the numbers

NFCorpus recall@10 of 0.19 is not a failure. Its queries average **38.2** relevant
documents, so the theoretical maximum recall@10 is **0.6146** — only 10 results can
be returned. Measured 0.1875 is roughly 30% of what is achievable at that depth.
This is why BEIR treats nDCG@10 as the primary metric.

---

## 2. Scale — runs, candidate answers, judged answers

**Status: Verified.** All four original targets are met by measurement.

### Claim

> Built an LLM evaluation and regression-testing platform for RAG, running a versioned
> dataset through OpenAI, Anthropic, and a self-hosted vLLM Mistral-7B across 79 runs
> spanning 9 distinct retrieval/prompt configurations plus temperature-varied repeats,
> generating 9,480 candidate answers and judging all 9,480 with the self-hosted judge —
> zero generation failures, zero judge failures.

### Evidence

| Measure | Value | Original target |
|---|---:|---:|
| Runs | **79** | 60+ ✅ |
| Candidate answers | **9,480** | 8K+ ✅ |
| — self-hosted `mistral-7b-instruct-v0.3-awq` | 9,240 | |
| — OpenAI `gpt-4o-mini` | 120 | |
| — Anthropic `claude-haiku-4-5` | 120 | |
| Generation failures | **0** | |
| **Answers judged** | **9,480 of 9,480** | 8K+ ✅ |
| **Judge failures** | **0** | |
| Trace span documents | **32,412** (13,950 traces) | 10K+ ✅ |

Artifacts: `runs/candidate_generation/cgen__{night_v1,scale_v1,dual_judge_slice_v1}__*`,
`runs/self_hosted_bulk_judging/final_bulk_*`

The final judging pass scored 6,683 answers and skipped
2,797 already complete, at
35.11 judged/min and 58.96 output tok/s over
3.2 hours at concurrency 16. Checkpoint
resume meant an interrupted overnight pass cost no rework.

### What "79 runs" actually means

9 distinct configurations — 3 retrieval modes x 3 prompt versions — repeated at
`temperature=0.7`. The repeats are **not** duplicates: measured, 95 of 120 answers differ
between a temperature-0 baseline and a temperature-0.7 repeat of the same configuration,
so they are genuine regression-stability samples.

Describe it as configurations plus stability repeats, not as 79 independent experiments.
That distinction is the first thing a reviewer will probe, and it is defensible stated
plainly.

Both axes had to be made real first. `prompt_version` was a label that never reached the
prompt, and every provider posted `temperature=0`, so repeats would have been
byte-identical. Three genuinely distinct prompt variants and a `temperature` parameter
were added before the run; without them these 79 runs would have been padding.

### Scope

All three providers produced real, persisted answers on the same 120-question SQuAD v2
fixture, whose questions and answers are human-written. 960 answers from a superseded
synthetic fixture also carry judge scores and are excluded from these totals.

### Must not say

- Do not present 79 runs as 79 distinct experiments.
- Do not add the 960 superseded-fixture judgements to the 9,480. Those answers were
  generated against questions their corpus could not answer.

---

## 3. Judge validation — dual-judge agreement and manual review routing

**Status: Verified.** Measured on a real slice with two real judges. The number is
materially worse than originally claimed, and that is the finding.

### Claim

> Built a dual-judge cross-check over a 120-answer slice with human-written questions
> and answers, scoring gpt-4.1-mini against a self-hosted Mistral-7B-AWQ served by vLLM
> on an AWS T4. Measured 65.0% pass/fail agreement and Cohen's kappa 0.264 — fair
> agreement at best — with the 7B systematically harsher (53% pass rate vs 87%), and
> 43% of cases routed to manual review by a configurable disagreement threshold.

### Evidence

Artifact: `runs/dual_judge_squad/real_7b_report.json`

| Measure | Value |
|---|---:|
| Validation slice | 120 answers |
| Judge A | `gpt-4.1-mini` |
| Judge B | `mistral-7b-instruct-v0.3-awq` on vLLM, AWS g4dn.xlarge (T4) |
| Pass/fail agreement | **65.0%** |
| Cohen's kappa | **0.264** |
| Score agreement at threshold 0.25 | 56.7% |
| Judge A pass rate | 0.867 (104 pass / 16 fail) |
| Judge B pass rate | 0.533 (64 pass / 56 fail) |
| `agreement_is_degenerate` | **false** |
| Manual review routed | 52 cases (43.3%) |

Correctness distributions — both judges used the full range, which is what makes the
agreement figure meaningful:

- Judge A: 0.0 ×3, 0.5 ×12, 0.8 ×1, 1.0 ×104
- Judge B: 0.0 ×42, 0.5 ×14, 0.8 ×1, 1.0 ×63

### What the number means

Kappa 0.264 sits in the "fair" band. Two judges agreeing 65% of the time on a binary
decision is not much above chance once base rates are accounted for, which is exactly
what kappa corrects for.

The mechanism is visible in the pass rates: the 7B fails 56 of 120 where gpt-4.1-mini
fails 16. It is not randomly disagreeing — it is **systematically harsher**. That is a
calibration gap, not noise, and it is the more useful diagnosis because calibration can
be addressed with prompt work or thresholding while noise cannot.

**Judge A was deliberately not the model that generated the candidates.** `gpt-4o-mini`
wrote the answers; `gpt-4.1-mini` judged them. A model grading its own output carries a
documented self-preference bias, which would have confounded the agreement number.

### Must not say

- ❌ *"84% inter-judge agreement"* — measured 65.0%.
- ❌ *"16% sent to manual review"* — measured 43.3%.
- ❌ Presenting kappa 0.264 as validation that the 7B is a reliable judge. It measures
  the opposite: a 7B does not substitute for a stronger judge without calibration or
  substantial human review.

### Interview answer

> "I wanted to know whether a 7B could carry bulk judging, so I ran it against
> gpt-4.1-mini on 120 answers with human-written ground truth. Agreement was 65% and
> kappa 0.264 — fair at best. The 7B fails 56 of 120 where the larger model fails 16,
> so it is systematically harsher rather than noisy. My read is that a 7B judge is
> usable for triage but not as an unsupervised scorer, which is why the harness routes
> disagreements to review rather than trusting either judge outright."

### Provenance fix made during this run

`DualJudgeValidationReport.mock_7b_warning` was a class default, so every report —
including real ones — carried the text "Mock 7B agreement is only a harness test." That
is a provenance error in the opposite direction from the usual one: it discredits a
sound measurement. The field is now populated only when `judge_b_is_mock=True`, the
rehearsal scripts pass that flag, and a test covers both directions.

## 4. Self-hosted judge — vLLM Mistral-7B on AWS T4

**Status: Verified.** Throughput and volume are now a single measurement.

### Claim

> Served an AWQ-quantized Mistral-7B judge with vLLM on a single on-demand AWS
> g4dn.xlarge (T4, 16 GB), sustaining 60.43 output tok/s
> (871.15 total) at concurrency 16 across 1,320 bulk-judged
> answers in 37 minutes, with zero failed scores.

### Evidence

| Measure | Value |
|---|---:|
| Answers judged | 1,320 |
| Failed scores | 0 |
| Concurrency | 16 |
| Wall clock | 2198s (36.6 min) |
| Judged per minute | 36.04 |
| Output tokens | 132,801 |
| Prompt tokens | 1,781,745 |
| **Output tok/s** | **60.43** |
| **Total tok/s** | **871.15** |

Artifact: `runs/self_hosted_bulk_judging/scale_bulk_*_status.json`

### Why this supersedes the earlier figure

Previously throughput came from a 64-request synthetic benchmark at concurrency 16
(56.18 output tok/s) while the answer count came from a *different* run at concurrency 1.
Quoting them in one sentence misrepresented both, which the project's own rules forbade.
Token usage is now accumulated from the judging workload itself, so tok/s, concurrency,
and answer count describe one run.

The two agree closely — 60.43 tok/s measured on the real workload
against 56.18 on the synthetic benchmark — which is a useful cross-check that the
instrumentation is sound.

The workload is prefill-dominated (1,781,745 prompt vs
132,801 output tokens), which is why output tok/s reads modest
while total token throughput is 871.15.

### Inference tuning: measured, and mostly a negative result

The workload is **prefill-bound**: 1350 prompt tokens
against 101 completion tokens per judgement,
a ratio of 13.4 : 1. Roughly 93% of every
request is prompt the model must read before emitting a token, which is why output tok/s
reads modest while the GPU processes 871 total tok/s.

Four vLLM options were tested against that profile, re-judging the identical 1,320 answers:
`--enable-prefix-caching`, `--enable-chunked-prefill`, `--max-model-len 2048` (down from
4096), and client concurrency 32 (up from 16).

| Metric | Baseline (c16) | Tuned (c32) | Change |
|---|---:|---:|---:|
| Judged/min | 36.04 | 37.87 | +5.1% |
| Output tok/s | 60.43 | 62.23 | +3.0% |
| Total tok/s | 871.15 | 893.08 | +2.5% |
| Wall clock | 2198s | 2091s | -4.8% |
| **Failed scores** | **0** | **27** | **regression** |

**The tuning is not worth adopting.** A 5% throughput gain cost 27 failed judgements, all
from the same cause: `max-model-len 2048` is below the prompt-length tail. Mean prompt is
1,350 tokens, but 2% of judge prompts exceed 2,048 and the server rejected them with
`HTTP 400: maximum context length is 2048 tokens`. The KV-cache budget saved by shrinking
the window did not buy enough batching to justify losing 2% of the data.

Prefix caching and chunked prefill are not implicated — they are free and directionally
correct for a prefill-bound job. The failure is attributable to one knob, and the honest
conclusion is to keep those two, restore `max-model-len 4096`, and re-measure.

Latency and cost, from the baseline run (percentiles read from trace span durations):

| Measure | Value |
|---|---:|
| p50 / p90 / p95 / p99 | 25.86s / 33.32s / 35.62s / 41.42s |
| Cost per 1,000 judgements | $0.2433 |
| Cost per 1M tokens | $0.1677 |

### Must not say

- No "5% faster" without the failure count beside it. The tuned configuration lost 27
  judgements; reporting the speedup alone would hide a correctness regression that the
  measurement exists to catch.
- No "145 tok/s" — never measured. Peak on the synthetic benchmark was 144.00; sustained
  on the real workload is 60.43.
- No "8K+ bulk-judged answers" — 1,320.

---

## 5. Tracing, dashboard, and the CI regression gate

**Status: Verified.** Tracing carries real volume and the CI gate has executed on GitHub Actions.

### Claim

> Instrumented six service layers with OpenTelemetry exported through a Collector into
> Elasticsearch, built a React/TypeScript dashboard whose type system makes rendering an
> unmeasured metric a compile error, and added a CI regression gate blocking changes that
> regress eval score >5% or latency/cost >15%.

### Evidence

| Component | Status |
|---|---|
| Six instrumented layers | gateway, retrieval, provider, judge, tool, storage — verified in `backend/app/tracing.py` |
| Trace export path | Verified end to end into the `otel-traces` data stream |
| Trace volume | **32,412 span documents across 13,950 traces** |
| Dashboard | Builds; provenance union makes an unmeasured metric a compile error |
| CI gate logic | 8 tests pass; exit 0 on committed fixtures, exit 1 on a fake regression |
| CI execution | **5 runs on `main`, all green** — Eval Regression Gate #1-#5, 25-41s each |

The trace count read 0 for a long time because of three stacked faults, none visible to
the application: the OTLP gRPC exporter was declared but never installed; the Collector's
Elasticsearch exporter writes bulk `create` actions requiring a **data stream**, not a
plain index; and the count script aggregated on a `text`-mapped field. All three are
fixed, and `scripts/setup_trace_index.py` makes the data stream reproducible.

### Must not say

- "10K+ traces" is now supported: **32,412 span documents across 13,950 traces**, emitted as a byproduct of real generation and judging. State which of the two figures is meant.
- Distinguish **span documents** from **traces**. Each judgement is currently its own
  root span, so the two counts are near 1:1. Nesting per-case spans under a run-level
  parent would give few traces and many spans, and a claim phrased as "10K traces"
  would then be far harder to reach than "10K span documents". State which one is meant.

### What 10K+ would actually require

The blocker was never volume, it was instrumentation coverage. `candidate_generation.py`
and `bulk_judging.py` — the modules doing the real work — emitted **zero** spans; only
the API layer and the Redis worker were instrumented, and the worker emits 10 spans per
*job* rather than per case. Reaching 10K at that granularity would have meant 1,000
worker jobs, which is span farming rather than evaluation.

Both modules are now instrumented per case. Measured emission rate:

| Path | Spans |
|---|---:|
| Generation, per case | 3 (provider parent, retrieval child, storage child) |
| Judging, per answer | 1 (measured: 120 answers produced exactly 120 spans) |
| **Full cycle, per case** | **4** |

So 10,000 span documents needs **2,500 cases processed end to end** — about 21 cycles of
the 120-case set. That is real evaluation work, and it is the same work claim 2 needs:
generating and judging 8,168 answers would emit roughly 32,700 spans as a byproduct.

Traces must come from real evaluation runs. Looping a smoke script to reach a round
number is the same failure as any other inflated metric.
- "Gated CI" is now supported: the workflow has executed 5 times on `main`, all passing.
  Note what the gate compares — `metrics/baseline_metrics.json` against
  `metrics/current_metrics.json`, which are committed fixtures, not live eval output.
  The gate mechanism is real and blocks a deliberate regression with exit 1; wiring it to
  real measured scores is a further step that has not been taken.

### Interview answer

> "The gate blocks on >5% eval-score regression and >15% latency or cost, and I verified
> it fails a deliberate regression with exit code 1. Tracing covers six layers and the
> export path is proven into Elasticsearch, but I've only generated a smoke test's worth
> of spans — so I'd claim the instrumentation, not a trace count."

---

## 6. Tool-using SQL agent evaluation with execution-based verification

**Status: Verified, scoped to Spider 1.0 dev under a tool-discovery protocol.**

**Canonical P0 baseline: run `spider_full__p0_v2`** — "the P0 baseline" means that
run ID and no other; `spider_full__p0_v1` is a repeat run, never the baseline.
Every number is recomputed from the raw
artifact by `scripts/audit_p0_claims.py`, which reports MISMATCH if a published
figure and its source disagree. Current status: **all_reconciled: True**.

### Claim

> Built an execution-verified evaluation harness for a tool-using LangGraph SQL
> agent over the full pinned Spider 1.0 dev set (1,034 tasks, 20 databases). The
> agent is given no schema: it discovers structure through `inspect_schema` and
> validates candidate queries through `execute_sql` against per-episode isolated
> read-only SQLite copies, and its final answer is scored by the official Spider
> evaluator using single-database execution accuracy. Measured **73.31%** with
> **zero** model, tool, or evaluator infrastructure failures, across 10,432
> persisted trajectory records reconciling exactly against 13,832 OpenTelemetry
> spans.

### Benchmark facts

Configuration: `gpt-4o-mini` at temperature 0, prompt `sql_agent_v1`, tools
`spider_tools_v2`, `max_steps=10` (**a model-turn cap**), dataset version
`spider-1.0:dev:30d64a3fccde`, 72.4 min sequential.

**Primary metric — single-database execution accuracy: 758 / 1,034 = 73.31%.**

Complete termination breakdown, summing exactly to 1,034:

| Termination | Count | Share |
|---|---:|---:|
| `SUCCESS` | 758 | 73.31% |
| `VERIFICATION_FAILED` | 226 | 21.86% |
| `MAX_STEPS` | 48 | 4.64% |
| `SQL_ERROR` | 2 | 0.19% |
| `MODEL_ERROR` | 0 | 0.00% |
| `TOOL_ERROR` | 0 | 0.00% |
| `NO_FINAL_SQL` | 0 | 0.00% |

Step metrics — three distinct quantities, per successful task. The previously
published "9.36 steps" conflated the first two:

| Quantity | Definition | Mean | Median |
|---|---|---:|---:|
| Model turns | one model API call; **what `max_steps` caps** | 4.67 | 4.00 |
| Tool calls | one tool invocation | 4.67 | 4.00 |
| Trajectory records | rows in `steps.jsonl` = turns + tool calls | 9.34 | 8.00 |

SQL errors — two metrics, two denominators, never combined:

| | Value | Denominator |
|---|---:|---|
| `execute_sql` error rate | 16 / 1,379 = **1.16%** | tool calls |
| `SQL_ERROR` terminations | 2 / 1,034 = **0.19%** | episodes |

The gap is recovery: 9 episodes contained a failed `execute_sql`; 3 still
succeeded.

Economics — estimated from published list price, **not billed**, and re-derivable
because cached-input tokens are persisted:

| | |
|---|---:|
| Input / cached / output tokens | 3,782,629 / 478,848 / 141,545 |
| Benchmark-only estimated cost | **$0.616408** |
| Per episode | $0.000596 |
| Per successful episode ($0.616408 / 758) | $0.000813 |
| **Total real API spend across all P0 dev+test runs** | **$1.2780** (2,139 episodes) |

Verifier QA, frozen before any agent ran, and bit-for-bit reproducible:

| | |
|---|---:|
| Gold queries passing | 1,034 / 1,034 |
| Frozen exclusions | 0 |
| Mutations attempted | 166 |
| Detected as wrong | 136 / 136, 0 leaks |
| Execution-result collisions | 30 (18.07% of attempted) |

Observability: 10,432 trajectory records, 13,832 indexed spans, all seven span
types reconciling exactly. Spans exceed step records because `eval.run`,
`agent.episode`, `sqlite.query`, and `verifier.execution` are not agent steps:
10,432 + 1 + 1,034 + 1,379 + 986 = 13,832.

Artifacts, all under `runs/spider_benchmark/spider_full__p0_v2/`: `config.json`,
`episodes.jsonl`, `steps.jsonl`, `payloads.jsonl`, `p0_metrics.json`,
`failure_analysis.json`, `claims_audit.json`, `p0_completion.json`,
`baseline_manifest.json`. Verifier QA: `runs/spider_verifier_qa/verifier_qa_dev.json`.
Frozen pins: `docs/LOCKED_INPUTS.md`, `docs/P0_BASELINE.md`.

### Scope

**The 73.31% is not comparable to a published Spider leaderboard number.** Most
published systems receive the full schema in the prompt and emit SQL in one
generation. This agent receives only a question and a database ID and must
discover the schema through tool calls. Different task.

The metric is **single-database execution accuracy**. It is never to be called
test-suite accuracy: the distilled multi-database test suite was not used.

One run, one model, one prompt, one tool schema.

### Must not say

- ❌ *"73.3% on Spider"* without stating the tool-discovery protocol.
- ❌ *"test-suite execution accuracy"* — the test-suite databases were not used.
- ❌ *"0.51% SQL error rate"* — that was the superseded v1 figure; the current one
  is 1.16%, and either way it is a **tool-call** rate, not an episode outcome rate.
- ❌ *"9.36 steps per task"* — ambiguous. Say 4.67 model turns, or 9.34 trajectory
  records, and say which.
- ❌ *"$0.62 measured cost"* — estimated from list price, and it covers the
  benchmark run only. Total P0 spend was $1.2780.
- ❌ *"18% of the agent's passes are false positives"* — the collision rate
  describes the mutation set, not the agent's query distribution.
- ❌ Any claim of variance, confidence intervals, calibrated regression thresholds,
  pass^k, bounded SQL repair, MCP, durable execution, idempotent tool side effects,
  lease fencing, or crash recovery. None are established.

### Debugging findings — not résumé claims

**A tool that answered the wrong question convincingly.** `spider_tools_v1` of
`inspect_schema` read only `table_name` and silently ignored other keys, so
`inspect_schema({"table": "course"})` returned the *table list* — a
successful-looking answer to a question never asked. The agent could not detect it
and looped to its step cap. On 10 task IDs (selected with a fixed task-sampling
seed) with `tool_schema_version` verified as the only differing config field,
success went 5/10 to 8/10.

**n=10, so the effect size is not established** — 34 of 1,034 tasks change outcome
between two runs of an identical recorded configuration, which is more churn than a
10-task comparison can resolve. What is established is the *mechanism*, visible
directly in the trajectories, and that it persists at scale: the model still sent
`{"table": ...}` 19 times in 1,034 episodes, each now returning a corrective error
naming the right parameter.

**Empty results read as failure.** By coded rule, 39 of 48 max-step episodes
(81.2%) executed a valid query returning zero rows and no error; **25 of 48
(52.1%)** executed a query that **passes the evaluator** and never submitted it,
established by re-verification rather than inspection. That is **2.42pp of the
benchmark** — *observed theoretical headroom*, not recoverable accuracy.

Exact cohort overlap: **23 of those 25** are also in the empty-result cohort, and in
**23 of 25** the passing query itself returned zero rows. **17 of 25** re-ran an
equivalent query after already having a passing one. The first passing query
appeared at model turn 3–6, leaving 4–7 turns unused; all 25 spent the full budget.
Frozen as a baseline finding and deliberately unfixed.

**Three observability defects found by auditing our own numbers**: span
reconciliation checked only 4 hand-listed span types and missed 1,009 tool steps
that had no span at all; rejected tool calls persisted an empty payload;
Elasticsearch capped the span count at exactly 10,000 and that cap was published as
a total. All three are fixed with regression tests.

### Two identical runs

`spider_full__p0_v1` (repeat) and `spider_full__p0_v2` (**canonical baseline**)
have **zero differing recorded identity fields**; only `run_id` and `started_at`
differ in the config.

Both runs recorded commit `ff9a4945` with a **dirty working tree**, and the changes
between them were observability-only (span placement, persisted fields) — provably
unable to alter agent behaviour, but they mean this is **not a same-commit
comparison**. It is two runs of an identical *recorded configuration* whose working
trees differed. A true same-commit repeat measurement is P1 (`docs/P1_PREREGISTRATION.md`).

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

No seed was sent, so these are **repeated runs under an identical recorded
configuration**, not seeded runs. `top_p` was not sent either; the provider default
applied. The resolved model revision behind the `gpt-4o-mini` alias was not captured
for these runs — it is captured going forward.

**This is n=2 and is not a variance estimate.** It is recorded as direct evidence
for why a regression threshold cannot be set from a single run.

### Future hypotheses — unmeasured

Prompting that an empty result may be correct might convert some max-step episodes
(ceiling 77.95%, actual effect unknown). A larger `max_steps` might convert some,
or might just spend more tokens on the same loops. Test-suite databases would
tighten the metric's blind spot by an unquantified amount.

### Interview answer

> "The agent doesn't get the schema — it finds it with `inspect_schema`, tests
> queries with `execute_sql`, and decides when to submit. Correctness is execution
> against gold using the official Spider evaluator, so no judge opinion is
> involved. 73.3% over all 1,034 dev tasks, zero infrastructure failures. I won't
> compare that to the leaderboard, because those systems get the schema in the
> prompt — different task. The thing I'd actually point at: I ran the same config
> twice and the aggregate moved 0.4 points, but 34 tasks changed pass/fail — 19 one
> way, 15 the other. That's why I won't set a CI threshold off one run — measuring
> that variance properly is next."

---

## Cross-cutting

Two claims that hold across every bullet and are worth making explicitly:

- **Provenance.** Every number in the README names the artifact it came from, and
  unmeasured metrics render as "not measured" rather than zero — enforced by the type
  system, not by convention.
- **Negative results are recorded.** The degenerate kappa, the corpus duplication defect,
  the discarded label set, and the NFCorpus non-replication are all in
  `docs/build-log.md` rather than removed.
