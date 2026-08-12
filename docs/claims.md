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

**Status: Partial.** Provider diversity is real; the volume is roughly 8x smaller than
originally claimed.

### Claim

> Built an LLM evaluation and regression-testing platform for RAG and agentic
> tool-calling, running versioned datasets through OpenAI and Anthropic APIs and scoring
> output with a self-hosted vLLM Mistral-7B judge; a checkpoint-resumable pipeline
> generated 960 candidate answers across 8 configurations (provider x retrieval mode x
> prompt version) and judged all 960 with zero failed scores.

### Evidence

| Measure | Value |
|---|---:|
| Production run artifacts / distinct run IDs | 8 |
| Completed candidate answers | 960 |
| OpenAI (`gpt-4o-mini`) | 480 |
| Anthropic (`claude-haiku-4-5`) | 480 |
| Failed candidate rows | 4 |
| Persisted judge scores | 960 |
| Failed judge scores | 0 |

Artifacts: `runs/candidate_generation/cgen__*_candidate_answers.jsonl`,
`runs/self_hosted_bulk_judging/self_hosted_7b_bulk_20260811_061841_judge_scores.jsonl`

The designed matrix is larger and is validated, but was never executed:
`config/candidate_answer_run_matrix.json` defines 72 runs / 8,168 answers, confirmed by
`python scripts/summarize_candidate_run_matrix.py --validate`. Describing it as *designed*
is accurate; describing it as *run* is not.

### Scope

Both providers produced real, persisted answers, so OpenAI/Anthropic coverage is earned.
The 8 configurations vary provider x retrieval mode x prompt version — a real matrix, just
a small one.

### Must not say

- No "60+ runs" — 8 run artifacts exist.
- No "8K+ judged answers" — 960 persisted judge scores.
- No "8K+ candidate answers" — 960 completed.
- Mock-provider runs exist under `runs/` and must never count toward provider diversity.
  Only the 8 `cgen__*` runs are real API generations.

### Interview answer

> "Cost control. The matrix is designed and validated for 8,168 answers across 72 runs; I
> ran a balanced 8-config slice that exercises every axis and proves the pipeline resumes
> without re-spending. Scaling it is a budget decision, not an engineering one."

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

**Status: Partial.** Deployment and bulk judging are real; the throughput figure is not.

### Claim

> Moved bulk judging off paid APIs onto an AWQ-quantized Mistral-7B served by vLLM on a
> single on-demand AWS g4dn.xlarge (T4, 16 GB), sustaining 23 judgments/min at p50 2.6s /
> p95 3.4s across a 960-answer run that completed in 41 minutes without a failure or
> restart. A dedicated benchmark measured 506 tok/s total throughput (56 output tok/s) at
> concurrency 16.

### Evidence

Bulk run, derived from per-row `judged_at` timestamps:

| Measure | Value |
|---|---:|
| Answers judged | 960 |
| Wall clock | 41.5 min |
| Sustained throughput | 23.2 judgments/min |
| Per-answer latency | p50 2.62s, p95 3.37s, max 3.78s |
| Failures | 0 |

Dedicated vLLM benchmark (`runs/vllm_benchmark/mistral_7b_awq_t4_c16_n64.json`):

| Measure | Value |
|---|---:|
| Max concurrency | 16 |
| Requests completed / failed | 64 / 0 |
| Sustained output throughput | 56.18 tok/s |
| Peak output throughput | 144.00 tok/s |
| Total token throughput | 506.48 tok/s |
| Input / output tokens | 131,320 / 16,384 |

Hardware: AWS `g4dn.xlarge`, Tesla T4 15,360 MiB, vLLM 0.27.0, `max_model_len=4096`,
`gpu_memory_utilization=0.90`, model `solidrust/Mistral-7B-Instruct-v0.3-AWQ`.

### Scope

The two measurements are **separate workloads** and must not be combined. The 960-answer
bulk run executed at **concurrency 1** — confirmed arithmetically, since 1/2.62s equals
the observed 0.386/s throughput. The concurrency-16 figure comes from a 64-request
benchmark with 2,052-token prompts, which is why output tok/s reads low while total token
throughput is high: the workload is prefill-dominated.

### Must not say

- No "145 tok/s" — measured sustained is 56.18; 144.00 was peak only.
- No "145 tok/s across 8K+ bulk-judged answers" — conflates two workloads, at two
  concurrency levels, over two different volumes.
- Do not attribute the concurrency-16 benchmark to the bulk run.

### Interview answer

> "Two separate measurements. The dedicated benchmark hit 56 output tok/s sustained at
> concurrency 16 — 506 total, since the workload is prefill-heavy at 2,052 input versus
> 256 output tokens. The bulk run is the one I'd actually quote: 960 judgments in 41
> minutes, p50 2.6s, zero failures — but it ran at concurrency 1, so raising concurrency
> is the obvious next optimisation."

---

## 5. Tracing, dashboard, and the CI regression gate

**Status: Partial.** All three are built; two lack the volume or execution to claim.

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
| Trace volume | **123 span documents, 121 traces** (120 from one instrumented judging run) |
| Dashboard | Builds; provenance union makes an unmeasured metric a compile error |
| CI gate logic | 8 tests pass; exit 0 on committed fixtures, exit 1 on a fake regression |
| CI execution | **Never run** — `git remote` is empty, nothing pushed |

The trace count read 0 for a long time because of three stacked faults, none visible to
the application: the OTLP gRPC exporter was declared but never installed; the Collector's
Elasticsearch exporter writes bulk `create` actions requiring a **data stream**, not a
plain index; and the count script aggregated on a `text`-mapped field. All three are
fixed, and `scripts/setup_trace_index.py` makes the data stream reproducible.

### Must not say

- No "10K+ traces in Elasticsearch" — measured 123 span documents over 121 traces.
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
- Do not state "gated CI" as operating — the workflow has never executed. It becomes true
  after a push; CI was verified to pass with no data services running (116 tests).

### Interview answer

> "The gate blocks on >5% eval-score regression and >15% latency or cost, and I verified
> it fails a deliberate regression with exit code 1. Tracing covers six layers and the
> export path is proven into Elasticsearch, but I've only generated a smoke test's worth
> of spans — so I'd claim the instrumentation, not a trace count."

---

## Cross-cutting

Two claims that hold across every bullet and are worth making explicitly:

- **Provenance.** Every number in the README names the artifact it came from, and
  unmeasured metrics render as "not measured" rather than zero — enforced by the type
  system, not by convention.
- **Negative results are recorded.** The degenerate kappa, the corpus duplication defect,
  the discarded label set, and the NFCorpus non-replication are all in
  `docs/build-log.md` rather than removed.
