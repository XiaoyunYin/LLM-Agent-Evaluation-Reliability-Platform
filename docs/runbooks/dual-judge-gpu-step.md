# GPU step: measure real dual-judge agreement

One task, one artifact. Everything upstream is committed; this window only swaps the
mock judge endpoint for real vLLM and records the number.

**Expected GPU time: 15-25 minutes**, most of it model download and load. The judging
itself is ~120 answers at roughly 2.6s each on a T4, so about 5 minutes.

---

## Before you start the instance

Verify locally that the slice is present and the port is free. Judging against a
leftover mock server is the one mistake that produces a plausible-looking number that
means nothing.

```powershell
# 120 answers should be present
(Get-Content runs/candidate_generation/cgen__dual_judge_slice_v1__openai__gpt_4o_mini__golden_squad_v2_sampled__hybrid_rrf_k60_top10_context4__rag_prompt_v1__repeat_01_candidate_answers.jsonl | Measure-Object -Line).Lines

# nothing must be listening on 8001
Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
```

---

## 1. Launch and serve

`g4dn.xlarge`, Deep Learning AMI, ~30 GB disk. The AWQ weights are about 4 GB.

```bash
docker run --gpus all -p 8001:8000 --ipc=host \
  vllm/vllm-openai:latest \
  --model solidrust/Mistral-7B-Instruct-v0.3-AWQ \
  --quantization awq \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.90 \
  --served-model-name mistral-7b-instruct-v0.3-awq
```

Wait for readiness before anything else:

```bash
curl -s localhost:8001/health
curl -s localhost:8001/v1/models | head -c 300
```

The served name must read `mistral-7b-instruct-v0.3-awq`. If it does not, the judge
name recorded in the report will not match the model that produced the scores.

---

## 2. Confirm it is the real model, not a stub

A single request, checked by eye. This costs seconds and prevents recording mock
output as a measurement.

```bash
curl -s localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mistral-7b-instruct-v0.3-awq",
       "messages":[{"role":"user","content":"Reply with exactly: READY"}],
       "max_tokens":10}'
```

A real model replies `READY`. The mock server returns a fixed judge-shaped JSON blob
regardless of the prompt — if you see JSON with `correctness` in it, you are talking
to the stub.

---

## 3. Run the validation

```powershell
python scripts/dual_judge_validate.py `
  runs/candidate_generation/cgen__dual_judge_slice_v1__openai__gpt_4o_mini__golden_squad_v2_sampled__hybrid_rrf_k60_top10_context4__rag_prompt_v1__repeat_01_candidate_answers.jsonl `
  --dataset datasets/squad_v2/golden.jsonl `
  --chunks datasets/squad_v2/chunks.jsonl `
  --limit 120 `
  --self-hosted-url http://127.0.0.1:8001/v1/chat/completions `
  --self-hosted-model mistral-7b-instruct-v0.3-awq `
  --report-output runs/dual_judge_squad/real_7b_report.json `
  --review-output runs/dual_judge_squad/real_7b_review.jsonl
```

Requires `OPENAI_API_KEY` for judge A. Cost is roughly `$0.04` for 120 GPT-4o-mini
judgments.

---

## 4. Read the result honestly

```powershell
python scripts/recompute_validation_report.py runs/dual_judge_squad/real_7b_report.json
```

Check these three fields before believing any agreement figure:

| Field | What it must show |
|---|---|
| `judge_a_pass_rate` | strictly between 0 and 1 |
| `judge_b_pass_rate` | strictly between 0 and 1 |
| `agreement_is_degenerate` | `false` |

If either pass rate is `0.0` or `1.0`, that judge used a single category, agreement is
trivially high, and `inter_judge_kappa` will be `None`. **That is not a result.** In the
rehearsal, judge A measured `0.608` with a 0.0/0.5/1.0 spread, so judge A is known
good; a degenerate outcome here would point at the 7B judge or its prompt.

Whatever the number is, it is the number. A low agreement between a 7B judge and
GPT-4o-mini is a real finding about small-model judging, not a failure to be re-rolled
until it looks better.

---

## 5. Optional, same window

Only if the instance is already up and you want more from it.

**Trace volume** — set the exporter before running anything and spans land in
Elasticsearch as a byproduct:

```powershell
python scripts/setup_trace_index.py   # once, before the collector
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4317"
$env:OTEL_EXPORTER_OTLP_INSECURE = "true"
```

**Self-hosted candidate generation**, if you want scale without paid APIs:

```powershell
$env:SELF_HOSTED_MODEL_ENDPOINT = "http://127.0.0.1:8001/v1/chat/completions"
python scripts/generate_candidates_for_dataset.py `
  --dataset golden_squad_v2_sampled `
  --provider self-hosted --model mistral-7b-instruct-v0.3-awq `
  --index squad_v2_chunks --prompt-version rag_prompt_v2
```

Both are resumable, so an interrupted run costs at most the work in flight.

---

## 6. Teardown

Bill accrues while the instance exists, not while it is busy.

```bash
aws ec2 terminate-instances --instance-ids <id>
aws ec2 describe-instances --query \
  'Reservations[].Instances[?State.Name!=`terminated`].[InstanceId,State.Name]'
```

Then delete the temporary security group and key pair, and remove the local `.pem`.
The final check should list nothing pending, running, stopping, or stopped.

---

## After the window

1. Copy `runs/dual_judge_squad/real_7b_report.json` back to the repo and commit it.
2. Update claim 3 in `docs/claims.md` with the measured agreement, kappa, and both
   pass rates.
3. Update the README metrics table.
4. If the slice is non-degenerate, claim 3 moves from **Unsupported** to **Verified**.

## Known account blocker

Anthropic generation on this fixture currently fails with
`400 - Your credit balance is too low`. Provider diversity therefore still rests on the
older synthetic-fixture runs. Topping up and re-running
`generate_candidates_for_dataset.py --provider anthropic` on `golden_squad_v2_sampled`
costs about `$0.05` and attaches that claim to the current fixture.
