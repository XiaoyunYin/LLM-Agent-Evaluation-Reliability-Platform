# Scale Runs

Generated at: 2026-08-11T07:00:12.429413+00:00

## Status

- Run type: REAL GPU RUN
- Bulk run ID: `self_hosted_7b_bulk_20260811_061841`
- Judge: `self-hosted-7b-bulk-v0`
- Judge model: `mistral-7b-instruct-v0.3-awq`
- Endpoint: `http://127.0.0.1:8001/v1/chat/completions`
- Instance type: `AWS g4dn.xlarge`
- Instance ID: `i-040abe6cb917a6042`
- GPU: `Tesla T4, 15360 MiB`
- Model source: `solidrust/Mistral-7B-Instruct-v0.3-AWQ`
- Quantization: `AWQ`
- Serving: `vLLM 0.27.0` via `vllm/vllm-openai:latest`
- vLLM settings: `max_model_len=4096`, `gpu_memory_utilization=0.90`
- Bulk judging started at: `2026-08-11T06:18:41.758408+00:00`
- Bulk judging finished at: `2026-08-11T07:00:12.419631+00:00`

## Judged-Answer Counts

- Candidate files scanned: 8
- Candidate rows seen during this invocation: 964
- Eligible completed candidate answers seen: 960
- Skipped already judged answers: 0
- Newly scored answers in this invocation: 960
- Latest completed judge-score count in output: 960
- Latest failed judge-score count in output: 0

## Output Files

- Judge scores: `runs\self_hosted_bulk_judging\self_hosted_7b_bulk_20260811_061841_judge_scores.jsonl`
- Status checkpoint: `runs\self_hosted_bulk_judging\self_hosted_7b_bulk_20260811_061841_status.json`
- Validation report: `runs\gpu_window\real_7b_validation_report.json`
- Manual review queue: `runs\gpu_window\real_7b_manual_review_queue.jsonl`

## Judge Validation

- Validation slice size: 120 candidate answers
- GPT-4o-mini use: validation slice only
- Pass/fail agreement: 100.00%
- Score agreement at threshold 0.25: 92.50%
- Manual-review routed cases: 9
- Inter-judge kappa: 1.00

## Measurement Boundary

- Bulk judged-answer count and vLLM throughput benchmark are separate measurements.
- Bulk sustained output tok/s: not measured by this bulk script
- Average output tokens per judged answer: not captured by the bulk judging script
- Use semicolon wording unless the bulk run is explicitly instrumented to report sustained output tok/s over the whole run.
