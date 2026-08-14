# Claims and Evidence

Every headline claim made about this project, the artifact that backs it, and the
scope it is valid within. A claim that cannot name an artifact does not belong here.

Each entry records four things:

- **Claim** — the exact wording that may be used.
- **Evidence** — the measured numbers and the file they come from.
- **Scope** — what the claim does *not* cover.
- **Unsupported wording** — a stronger version that the evidence does not support.

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

This scoped claim also states when a gain is expected, which a bare benchmark
number does not.

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

### Unsupported wording

- *"Hybrid retrieval beats both dense and BM25"* — unscoped, and true only where the
  retrievers are complementary. NFCorpus refutes the unscoped form.
- *"Lifted recall@10 from 0.69 to 0.84 using hybrid retrieval"* — never measured
  on any corpus. On SciFact dense alone reaches 0.8536, so that magnitude comes from
  the embedding model, not from fusion.
- *"k=60 is the tuned value"* — k=1 won on SciFact; k=5 on NFCorpus. Standard
  practice is k=60, and neither dataset chose it.
- Comparing numbers across corpus versions. The synthetic corpus BM25 figure moved
  from 0.0667 to 0.7417 to 0.3505 with no retriever change at all, purely from
  fixture differences.

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
| Runs | **79** | 60+ (met) |
| Candidate answers | **9,480** | 8K+ (met) |
| — self-hosted `mistral-7b-instruct-v0.3-awq` | 9,240 | |
| — OpenAI `gpt-4o-mini` | 120 | |
| — Anthropic `claude-haiku-4-5` | 120 | |
| Generation failures | **0** | |
| **Answers judged** | **9,480 of 9,480** | 8K+ (met) |
| **Judge failures** | **0** | |
| Trace span documents | **32,412** (13,950 traces) | 10K+ (met) |

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

### Unsupported wording

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

### Unsupported wording

- *"84% inter-judge agreement"* — measured 65.0%.
- *"16% sent to manual review"* — measured 43.3%.
- Presenting kappa 0.264 as validation that the 7B is a reliable judge. It measures
  the opposite: a 7B does not substitute for a stronger judge without calibration or
  substantial human review.

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

**The tuned configuration was rejected.** A 5% throughput gain cost 27 failed judgements, all
from the same cause: `max-model-len 2048` is below the prompt-length tail. Mean prompt is
1,350 tokens, but 2% of judge prompts exceed 2,048 and the server rejected them with
`HTTP 400: maximum context length is 2048 tokens`. The KV-cache budget saved by shrinking
the window did not buy enough batching to justify losing 2% of the data.

Prefix caching and chunked prefill are not implicated. The failure is attributable
to one setting: keep those two options, restore `max-model-len 4096`, and re-measure.

Latency and cost, from the baseline run (percentiles read from trace span durations):

| Measure | Value |
|---|---:|
| p50 / p90 / p95 / p99 | 25.86s / 33.32s / 35.62s / 41.42s |
| Cost per 1,000 judgements | $0.2433 |
| Cost per 1M tokens | $0.1677 |

### Unsupported wording

- No "5% faster" without the failure count beside it. The tuned configuration lost 27
  judgements; reporting the speedup alone would hide a correctness regression that the
  measurement exists to catch.
- No "145 tok/s" — never measured. Peak on the synthetic benchmark was 144.00; sustained
  on the real workload is 60.43.
- Do not attach the 9,480-answer scale total to this throughput measurement. The
  throughput and latency figures above come from one 1,320-answer workload.

---

## 5. Tracing, dashboard, and the CI regression gate

**Status: Verified.** Tracing carries real volume and the CI gate has executed on GitHub Actions.

### Claim

> Instrumented six service layers with OpenTelemetry exported through a Collector into
> Elasticsearch, built a React/TypeScript dashboard whose type system makes reading a
> metric's numeric value without narrowing its provenance status a compile error, and
> added a CI regression gate blocking changes that regress eval score >5% or
> latency/cost >15%.

### Evidence

| Component | Status |
|---|---|
| Six instrumented layers | gateway, retrieval, provider, judge, tool, storage — verified in `backend/app/tracing.py` |
| Trace export path | Verified end to end into the `otel-traces` data stream |
| Trace volume | **32,412 span documents across 13,950 traces** |
| Dashboard | Builds; the `not_measured` variant has no `value` property, so reading a number without narrowing on `status` is a compile error |
| CI gate logic | 8 tests pass; exit 0 on committed fixtures, exit 1 on a fake regression |
| CI execution | **5 runs on `main`, all green** — Eval Regression Gate #1-#5, 25-41s each |

### Precision note on the dashboard claim

**Do not say** "rendering an unmeasured metric is a compile error." The dashboard
renders the unmeasured *state* deliberately — `ProvenanceBadge` exists for exactly
that. What the type system forbids is printing a **number** for something never
measured, because the `NotMeasured` variant has no `value` property.

The loose version collapses the moment someone asks how the dashboard shows a
not-yet-run benchmark. The precise version answers that question by itself.

The trace count read 0 for a long time because of three stacked faults, none visible to
the application: the OTLP gRPC exporter was declared but never installed; the Collector's
Elasticsearch exporter writes bulk `create` actions requiring a **data stream**, not a
plain index; and the count script aggregated on a `text`-mapped field. All three are
fixed, and `scripts/setup_trace_index.py` makes the data stream reproducible.

### Required qualification

- Do not describe 32,412 span documents as 32,412 traces. The repository contains
  **32,412 span documents across 13,950 traces**, emitted by real generation and
  judging runs.
- Each judgement is currently its own root span, so the two counts are relatively
  close. A different parent-span structure would change the trace count without
  changing the amount of evaluation work.

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
| **Spend, P0 implementation phase** | **$1.2780** — 2,139 episodes across 6 runs (`p0_v1`, `p0_v2`, `debug__step14`, `smoke__step13`, `smoke__step13_v2`, `single__step9`) |
| **Spend, all Spider runs to date** | **$6.8879** — 11,445 episodes across 15 real runs, as reported by the current cost ledger |

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

The P0 headline metric is **single-database execution accuracy**, which is what
the frozen baseline was measured and audited under.

The distilled test suite has since been installed and both frozen runs rescored
offline from their persisted SQL (no model re-run). On the canonical baseline:
**test-suite execution accuracy 65.38%** (676 / 1,034) against single-database
73.31%, a 7.93pp gap — meaning **10.82% of single-database passes are false
positives** under the tighter substrate. `fail → pass` was 0, as a strictly tighter
metric requires.

Quote the two together. Neither replaces the other, and neither may be called by
the other's name.

One run, one model, one prompt, one tool schema.

### Unsupported wording

- *"73.3% on Spider"* without stating the tool-discovery protocol.
- Calling the 73.31% figure *"test-suite execution accuracy"* — that name belongs
  to the 65.38% figure, measured on the distilled suite.
- Quoting 65.38% as "the" accuracy without the single-database figure beside it,
  or vice versa.
- *"0.51% SQL error rate"* — that was the superseded v1 figure; the current one
  is 1.16%, and either way it is a **tool-call** rate, not an episode outcome rate.
- *"9.36 steps per task"* — ambiguous. Say 4.67 model turns, or 9.34 trajectory
  records, and say which.
- *"$0.62 measured cost"* — estimated from list price, and it covers the
  benchmark run only. P0 implementation-phase spend was $1.2780 across 2,139
  episodes; the full Spider ledger now reads $6.8879 across 11,445 episodes,
  because P1 variance repeats, the validation ablation and the P2 runs came
  after that figure was published. Name the cohort whenever either is quoted.
- *"18% of the agent's passes are false positives"* — the collision rate
  describes the mutation set, not the agent's query distribution.
- Any claim of variance, confidence intervals, calibrated regression thresholds,
  pass^k, bounded SQL repair, MCP, durable execution, idempotent tool side effects,
  lease fencing, or crash recovery based on P0 alone. Later phases establish some
  of these separately.

### Debugging findings

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

---

## 7. Stateful agentic evaluation with declarative state verification (P3)

**Full results: [`docs/results/p3-frozen.md`](results/p3-frozen.md).** Frozen at
suite `2cfcaedbb400`, 80 tasks, budget 20 turns, model `gpt-4o-mini`.

| Claim | Measured | Artifact |
|---|---|---|
| 80-task stateful support-ticket agent benchmark, declarative state verification | 80 tasks, 35 core / 45 hard | `config/p3_frozen_manifest.json` |
| verifier QA with adversarial known-bad cases | **452/452** | `runs/support_verifier_qa/verifier_qa.json` |
| all reference solutions replay through the real runtime | **80/80**, zero model calls | `runs/support_reference_replay/` |
| baseline over 10 repeats | **90.25%**, sd 1.75% | `runs/support_baseline/frozen_baseline.json` |
| core / hard tiers (roles declared before baselines) | 97.7% / **84.4%** | same |
| invalid typed calls | 235/4,545 = **5.2%**, in 29.4% of episodes | same |
| pre-registered intervention run to a verdict | **NO EFFECT** | `runs/support_baseline/repair_experiment.json` |
| P3 episodes executed | **3,439** across 51 runs, $2.55 | `runs/support_benchmark/` |

### What must not be claimed

- **Do not** claim the schema-repair intervention improved anything. It did not.
  The pre-registered primary metric was **degenerate in both arms** - zero episodes
  ever emitted a second invalid call. Global success 90.25% -> 90.31%.
- **Do not** claim this benchmark discriminates between frontier models. It was
  measured against **one** model, and seven of eleven families sit at 100%.
- **Do not** quote the hard tier's earlier 49.2%. That figure was produced by
  three benchmark defects; after fixing them the same tasks measured 96.2%, and
  the suite was later expanded and re-frozen. The published hard-tier number is
  **84.4%** on the frozen 80-task suite.
- **Do** state that six benchmark defects were found and fixed, and that all were
  caught by repeats plus trajectory reading rather than by an aggregate score.

### The defensible headline

> Built an 80-task stateful agent benchmark where correctness is a verified state
> diff, not a judged answer. Ten repeats, 800 episodes, 90.25% +/- 1.75%. Found and
> fixed six benchmark defects that an aggregate score could not see, and ran a
> pre-registered intervention to a **null** verdict rather than to a number.

---

## 8. Deterministic P4a durability matrix

**Status: Verified, scoped to the Python-native P4a harness.**

### Claim

> Deterministic P4a durability matrix passed 915/915 clean and injected-crash
> cases with zero duplicate effects, lost effects, incorrect final states, or
> protocol invariant violations.

### Evidence

Full result: [`docs/results/p4a-matrix.md`](results/p4a-matrix.md).

| Measure | Value | Artifact |
|---|---:|---|
| model calls | 0 | `runs/p4a_matrix/p4a_matrix_20260813/p4a_matrix.json` |
| clean cases | 80 | same |
| injected-crash cases | 835 | same |
| total cases | 915 | same |
| passed cases | 915 / 915 | same |
| duplicate_side_effects | 0 | same + audit |
| lost_required_effects | 0 | same + audit |
| incorrect_final_states | 0 | same + audit |
| stale_fenced_effects_accepted | 0 | same + audit |
| orphan_effect_records | 0 | same + audit |
| invariant_violations | 0 | same + audit |

Matrix artifact SHA-256:
`9F60CE9E933EDBECBA5CE35199A8CCFED3336D2F44769FADF2C4FB585E6D4FD4`.

Audit artifact:
`runs/p4a_matrix/p4a_matrix_20260813/p4a_matrix_audit.json`.
The audit reconstructs the expected case set from the frozen 80-task P3 suite and
verifies every expected `(task_id, crash_window, step_index, tool_name)` row
appears exactly once. It also verifies every promised acceptance counter and
protocol invariant is zero row-by-row, not only through aggregate failure count.

Crash-window coverage:

| Window | Cases |
|---|---:|
| clean | 80 |
| before_intent_insert | 167 |
| after_intent_before_effect | 167 |
| inside_before_effect_application | 167 |
| after_effect_before_step_completion | 167 |
| after_step_before_next_model | 167 |

Tool/window coverage:

| Tool | Cases per crash window |
|---|---:|
| update_ticket | 80 |
| assign_ticket | 77 |
| add_comment | 10 |

Supplemental artifact:
`runs/p4a_supplemental/p4a_supplemental_20260813/p4a_supplemental.json`.
It separately measured double-crash recovery, stale-worker fencing-token
rejection, and poison-to-DLQ after three failed attempts: 3/3 passed, zero model
calls.

### Scope

The 915-case matrix covers deterministic replay of frozen P3 reference
trajectories through the Python-native P4a protocol, with every supported crash
window injected at every effectful step.

Stale-worker fencing and poison/DLQ are **not** part of the 915-case matrix; they
are measured only by the supplemental artifact. The stale-worker case is a
fencing-token simulation, not an OS SIGSTOP test.

This claim does not cover P4b or the distributed Java substrate.

### Unsupported wording

- Do not claim P4b is implemented.
- Do not claim the 915-case matrix contains zombie/stale-worker or poison/DLQ
  rows; those are separate supplemental scenarios.
- Do not claim OS-level SIGSTOP coverage.
- Do not generalize exactly-once behavior beyond the Python-native harness until
  P4b is implemented and measured.

---

## 9. Implemented stack

Each entry names the code or artifact that verifies its use in the repository.

| Claimed | Evidence | Check |
|---|---|---|
| FastAPI | `backend/main.py` | `grep -rl fastapi backend/` |
| LangGraph | `backend/app/support/agent.py`, `backend/app/spider/agent.py` | `StateGraph` agent loop in both |
| OpenTelemetry | span emission + trace↔trajectory reconciliation | 10,432 records vs 13,832 spans, §6 |
| Elasticsearch | BM25 retrieval + `otel-traces` data stream | §1, §5 |
| SQLite/Postgres | per-episode read-only Spider DBs; mutable P3 support fixture; pgvector dense index | §1, §6, §7 |
| pytest | 181 tests | `pytest tests -q` |
| **GitHub Actions** | **`.github/workflows/eval-regression-gate.yml` — this is where the regression gates run** | file exists; 5 green runs recorded in §5 |

**Recorded decisions (2026-08-13).** FastAPI and GitHub Actions are included
because they are execution dependencies: FastAPI serves the API, and GitHub
Actions runs the CI regression gate.

---

## 10. The armed Spider regression gate — what runs in CI

**Status: Verified.** Previously this repo had two separate things that were easy
to conflate: a CI workflow that ran on GitHub Actions against *fixtures*, and a
threshold policy derived from measured variance that **nothing executed**. They are
now the same system.

### What executes

`.github/workflows/eval-regression-gate.yml` runs `scripts/check_spider_gate.py`
against real measured metrics on every PR and push touching agent code, prompts,
config, scripts or metrics.

| Armed metric | Threshold | Derived from |
|---|---:|---|
| `test_suite_task_success` | 0.027079 | measured spread 0.013540 across 4 same-commit repeats |
| `mean_model_turns_per_success` | 0.055692 | measured spread 0.027846 |
| `tool_validity_rate` | 0.001912 | measured spread 0.000956 |
| `estimated_cost_per_success` | 0.000080 | measured spread 0.000040 |

Formula, fixed before any family run executed:
`max(2 x observed_spread, minimum_detectable_change)`.

`consistency_pass_pow_4` is reported and **not armed** — it needs k repeats per
side, which a single CI run cannot produce.

**Always-fail conditions** (no thresholds — infrastructure correctness is not a
tunable metric): wrong episode count, any `RATE_LIMITED` / `MODEL_ERROR` /
`TOOL_ERROR` episode, evaluator failures, gold-query failures, missing
trajectories, duplicate task ids, or trace/trajectory reconciliation mismatch.

### Baseline provenance

`metrics/spider_baseline_metrics.json` is extracted from **`spider_p2__treat_2`**,
the median test-suite-accuracy run of the adopted-configuration family — chosen by
that rule, not by which number looked best. It satisfies every always-fail
condition, including exact trace reconciliation across all seven span types.

### Evidence

| Check | Result |
|---|---|
| Gate tests | **23 passing**, including one failing case per armed metric and per always-fail condition |
| Full suite | 219 passing |
| Simulated 4pp regression | correctly **FAILS**, exit 1 |
| Committed baseline/current | **PASSES**, exit 0 |

### Two defects found by building this

1. **Silent default in the metrics extractor.** `bad_argument_tool_calls` was added
   in P1, so P0-era runs do not carry it — and `.get(field, 0)` rendered "never
   recorded" as "zero malformed calls", producing `tool_validity_rate = 1.0` for a
   run that never measured it. That false green would have made every future real
   run look like a 0.004 regression, over the 0.001912 threshold. The extractor now
   **raises** rather than defaulting. This is the twelfth instance of the
   absent-data-as-plausible-value pattern.

2. **Trace verdicts were stale, not wrong.** Several runs recorded
   `matches_trajectory: false` because the check ran moments after the run, before
   Elasticsearch finished ingesting. Re-queried, `spider_p2__treat_2` reconciles
   **exactly** on all seven span types. The extractor now recomputes the verdict
   live and stamps it, leaving the frozen run artifact untouched.

   Not everything was lag: `spider_rpt__on_1` returns 19,840 spans with
   `eval.run: 3` and 2,322 `agent.episode` spans, which is genuine span bleed from a
   reused run id. That run **cannot** serve as a gate baseline, and the gate says so
   rather than averaging it away.

### A reproducibility defect this found

CI regenerated the P3 fixture and got a **different hash than the freeze**, with
identical rows. The cause: `sha256` over the `.sqlite` file. SQLite's page layout
and encoding defaults vary by library version and platform, so the same seed
produces byte-different files on Windows and Linux.

That matters more than a red build. The fixture hash is stamped into **every task
spec**, and the specs roll up into `suite_sha256` — so the entire frozen benchmark
was verifiable **only on the machine that created it**. "Frozen by content hash"
was true of the artifact and false of the property it was meant to guarantee.

The fix hashes the fixture's **content** — every table in name order, its columns,
and every row in primary-key order — which is identical anywhere the data is. The
suite fingerprint changed as a consequence:

| | |
|---|---|
| fixture pin | file bytes → `fixture_content_sha256` = `e561689ec552…` |
| suite hash | `2cfcaedbb400` → `0bba80938319` |
| what changed in the data | **nothing** — no task, required change, or measurement |

Re-verified after the change with the fixture deleted from disk: 452/452 verifier
QA checks, 80/80 references replayed, 219 tests, and `assert_p3_frozen` green.

This is the thirteenth defect of the same family: a check that appeared to hold
because it was keyed on something that only looked stable.

### Unsupported wording

- *"CI re-runs the benchmark on every PR"* — it does not. 1,034 tasks is ~72
  minutes and real money. The gate compares **recorded** metrics; a PR that changes
  agent behaviour must re-run the benchmark and update
  `metrics/spider_current_metrics.json`, and the gate blocks the update if it
  regressed.
- *"The gate has caught a production regression"* — it has caught a simulated
  one and every case in its test suite. No real regression has occurred since it
  was armed.

---

## Cross-cutting

Two rules apply across the claims in this file:

- **Provenance.** Every result in the README links to its report or source, and
  unmeasured dashboard metrics render as "not measured" rather than zero. The
  dashboard type system enforces the latter rule.
- **Negative results are recorded.** The degenerate kappa, corpus duplication
  defect, discarded label set, and NFCorpus non-replication remain in the relevant
  result reports.
