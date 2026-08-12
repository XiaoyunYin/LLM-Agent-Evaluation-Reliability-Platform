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

The claim that **all three** corpora support is different and weaker:

> Fusion matches or exceeds the better of its two inputs without needing to know in
> advance which that is, and beats the weaker input substantially every time.

That is a robustness property, not a lift.

### Must not say

- ❌ *"Hybrid retrieval beats both dense and BM25"* — unscoped. NFCorpus refutes it.
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

**Status: Unsupported.** The harness is real; the measurement is degenerate.

### Claim that may be made

> Built a dual-judge cross-check (GPT-4o-mini + self-hosted 7B) computing Cohen's kappa
> and per-dimension score deltas, with configurable disagreement thresholds routing cases
> to a manual-review queue.

That describes **capability built**, which is accurate. No agreement *number* may be
reported.

### Evidence

| Measure | Value |
|---|---:|
| Validation slice | 120 answers |
| Pass/fail agreement | 100.00% — degenerate |
| Judge A pass rate | 0.0 |
| Judge B pass rate | 0.0 |
| Cohen's kappa | `None` (undefined) |
| Score agreement at threshold 0.25 | 92.50% |
| Manual review routed | 9 cases (7.5%) |

Artifact: `runs/gpu_window/real_7b_validation_report.json`

Both judges marked **all 120** cases failed, so agreement is trivially 100% and kappa is
undefined rather than 1.00 — chance agreement is also 100% when both raters use one
category. `calculate_cohens_kappa_from_pairs` previously returned a hardcoded `1.0` there;
it now returns `None`, and every report carries `judge_a_pass_rate`, `judge_b_pass_rate`,
and `agreement_is_degenerate`.

Root cause: `golden_rag_v0.1.jsonl` was written independently of the corpus — measured, **0
of 120** questions contained corpus vocabulary — so 115 of 120 answers were correctly
refusing "the context is insufficient". The judges were right; the fixture was wrong.

Both repairs are in place but the slice has not been re-run: `golden_rag_v0.2.jsonl` is
corpus-grounded (108 verified-answerable plus 12 abstention cases), and retrieval routing
is now decided per case via `case_requires_retrieval()`. Re-running needs a GPU window.

### Must not say

- No "84% inter-judge agreement" — never measured.
- No "16% sent to manual review" — measured 7.5%, and from a degenerate slice.
- No "100% agreement" or "kappa 1.00" — numerically true, statistically meaningless, and
  the fastest way to lose credibility in an interview.
- No "graded relevance labels created blind to judge outputs" for the synthetic set — its
  labels are programmatically derived from planted facts. The BEIR sets carry genuine
  human judgments; cite those instead.

### Interview answer

> "Both judges failed all 120, so agreement was degenerate and kappa undefined. I traced
> it to a dataset/corpus mismatch — the RAG golden set was arithmetic QA and the corpus was
> support runbooks, so 115 of 120 answers were correctly-refusing 'insufficient context'.
> The harness was right; the fixture was wrong. I also fixed a kappa implementation that
> returned a hardcoded 1.0 on single-category slices, which is what let it hide."

---

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
| Trace volume | **3 span documents, 1 unique trace** (smoke test) |
| Dashboard | Builds; provenance union makes an unmeasured metric a compile error |
| CI gate logic | 8 tests pass; exit 0 on committed fixtures, exit 1 on a fake regression |
| CI execution | **Never run** — `git remote` is empty, nothing pushed |

The trace count read 0 for a long time because of three stacked faults, none visible to
the application: the OTLP gRPC exporter was declared but never installed; the Collector's
Elasticsearch exporter writes bulk `create` actions requiring a **data stream**, not a
plain index; and the count script aggregated on a `text`-mapped field. All three are
fixed, and `scripts/setup_trace_index.py` makes the data stream reproducible.

### Must not say

- No "10K+ traces in Elasticsearch" — 3 span documents exist.
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
