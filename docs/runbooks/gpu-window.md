# GPU Window Runbook

Purpose: consolidate the real self-hosted 7B work into one cost-controlled GPU
window after the local mock rehearsal passes.

## Scope

Required GPU work:

- Replace mock 7B with the real vLLM endpoint in the validation harness.
- Judge the 120-answer validation slice with the real self-hosted 7B judge.
- Bulk judge persisted candidate answers.
- Run a dedicated vLLM throughput benchmark at concurrency `16`.

Optional GPU work:

- Generate self-hosted candidate answers only if self-hosted candidate-provider
  coverage is intentionally added later.
- This is not required for the current resume bullets.

## Target Configuration

- Model: `Mistral-7B-Instruct-v0.3-AWQ`
- Quantization: `AWQ`
- Serving: `vLLM`
- Instance: `AWS g4dn.xlarge`
- GPU: `T4`, `16 GB`
- `max_model_len`: `4096`
- `gpu_memory_utilization`: `0.90`
- Benchmark concurrency: `16`
- Self-hosted judge endpoint:
  - `http://127.0.0.1:8001/v1/chat/completions`

## Cost Guardrails

- Use on-demand only for the planned window.
- Start the instance only after local mock rehearsal passes.
- Keep commands copied into a notes file before launch.
- Confirm the current EC2 regional price before launch.
- Stop or terminate the instance immediately after result files are copied off
  the box.
- Do not leave vLLM running overnight.

## Launch Checklist

- Local mock rehearsal passed:
  - `python scripts\rehearse_gpu_window.py --validation-limit 12 --bulk-limit 24`
- Candidate answers exist:
  - `docs/results/candidate-generation.md`
- The candidate-answer count is measured from JSONL files.
- AWS quota allows `g4dn.xlarge`.
- Disk has enough room for model weights, Python environment, repo, and outputs.
- Security group allows SSH from your IP only.
- You have a clear stop/terminate time.

## Instance Setup

Example commands on the GPU instance:

```bash
nvidia-smi
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install vllm
pip install -r requirements.txt
```

## Model Serving Command

```bash
vllm serve casperhansen/mistral-7b-instruct-v0.3-awq \
  --served-model-name mistral-7b-instruct-v0.3-awq \
  --quantization awq \
  --dtype half \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.90 \
  --host 0.0.0.0 \
  --port 8001
```

If the T4 runs out of memory, lower one thing at a time:

- `--max-model-len 3072`
- `--gpu-memory-utilization 0.85`
- benchmark concurrency below `16` only for debugging, not for the final target
  benchmark

## Health Check

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/v1/models
```

The judge adapter expects an OpenAI-compatible chat-completions endpoint at:

```text
http://127.0.0.1:8001/v1/chat/completions
```

## Validation-Slice Judging

Run this only when GPT-4o-mini API use is intentionally approved:

```bash
python scripts/dual_judge_validate.py \
  runs/candidate_generation/cgen__candidate_answer_run_matrix_v0_1__openai__gpt_4o_mini__golden_rag_v0_1__bm25_top50_context4__rag_prompt_v1__repeat_01_candidate_answers.jsonl \
  --limit 120 \
  --self-hosted-url http://127.0.0.1:8001/v1/chat/completions \
  --self-hosted-model mistral-7b-instruct-v0.3-awq \
  --report-output runs/gpu_window/real_7b_validation_report.json \
  --review-output runs/gpu_window/real_7b_manual_review_queue.jsonl
```

This replaces the mock 7B path for judge agreement. The validation agreement
numbers become usable only after GPT-4o-mini and the real self-hosted 7B judge
score the same validation answers.

## Bulk Judging

```bash
python scripts/bulk_self_hosted_judge_answers.py \
  --candidate-glob "runs/candidate_generation/cgen__candidate_answer_run_matrix_v0_1__*_candidate_answers.jsonl" \
  --self-hosted-url http://127.0.0.1:8001/v1/chat/completions \
  --self-hosted-model mistral-7b-instruct-v0.3-awq \
  --output-dir runs/self_hosted_bulk_judging \
  --scale-report-path docs/results/scale-runs.md \
  --progress-every 100
```

Resume behavior:

- The script reads the existing judge-score JSONL output.
- Completed `(run_id, case_id, judge_name)` scores are skipped.
- Failed rows can be retried because only completed scores are treated as done.
- Status is checkpointed after every scored answer.

## Benchmark Command

```bash
mkdir -p runs/vllm_benchmark
vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:8001 \
  --endpoint /v1/chat/completions \
  --model mistral-7b-instruct-v0.3-awq \
  --dataset-name random \
  --num-prompts 256 \
  --input-len 2048 \
  --output-len 256 \
  --max-concurrency 16 \
  --save-result \
  --result-dir runs/vllm_benchmark \
  --result-filename mistral_7b_awq_t4_c16.json
```

Record the benchmark result in:

- `docs/results/vllm-benchmark.md`

## Required Result Files

- `docs/results/scale-runs.md`
  - judged-answer count
  - candidate files scanned
  - completed and failed judge-score counts
  - model, endpoint, and run metadata
- `docs/results/vllm-benchmark.md`
  - output tok/s at concurrency `16`
  - benchmark command
  - benchmark JSON path

## Measurement Boundary

The GPU window runs both the bulk judging scale run and the vLLM benchmark, but
those are separate measurements.

Use this wording unless the bulk judging script is explicitly instrumented to
measure sustained output tokens/sec over the whole bulk run:

```text
sustaining X tok/s at concurrency 16; bulk-judged Y answers on the same vLLM setup
```

Do not use:

```text
X tok/s across Y bulk-judged answers
```

unless the bulk run itself logs sustained output tok/s across all Y answers.

## Teardown Checklist

- Copy `runs/gpu_window/`, `runs/self_hosted_bulk_judging/`, and
  `runs/vllm_benchmark/` off the instance.
- Confirm `docs/results/scale-runs.md` exists.
- Confirm `docs/results/vllm-benchmark.md` exists.
- Stop vLLM.
- Stop or terminate the EC2 instance.
- Confirm the instance is no longer running in the AWS console.
- Rotate or remove any temporary API keys from shell history if used.

## Why This Matters

- Mock 7B gives meaningless final judge-quality numbers, but it proves command
  shape, schema parsing, checkpointing, report writing, and recovery behavior.
- GPU work is consolidated because the instance costs money while it is running.
- Bulk judging thousands of answers can take hours because every candidate
  answer requires prompt construction, HTTP serving, generation, parsing, and
  disk checkpointing.
- Checkpoint/resume is required because network hiccups, GPU OOM, rate limits,
  SSH disconnects, or process crashes should not erase already-paid work.
- T4 memory can fail if model weights, KV cache, context length, and concurrency
  exceed the 16 GB budget.
- Teardown matters because an idle GPU instance still costs money.

## Sources

- vLLM `serve` CLI documentation:
  - https://docs.vllm.ai/en/latest/cli/serve/
- vLLM `bench serve` CLI documentation:
  - https://docs.vllm.ai/en/latest/cli/bench/serve/
- AWS EC2 On-Demand behavior:
  - https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html
- AWS accelerated instance specs:
  - https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html
