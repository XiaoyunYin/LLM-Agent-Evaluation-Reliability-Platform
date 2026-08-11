# vLLM Benchmark

Generated at: 2026-08-11T07:08:11+00:00

## Status

- Benchmark status: measured
- Model target: `Mistral-7B-Instruct-v0.3-AWQ`
- Model source: `solidrust/Mistral-7B-Instruct-v0.3-AWQ`
- Served model name: `mistral-7b-instruct-v0.3-awq`
- Quantization: `AWQ`
- Hardware: `AWS g4dn.xlarge`
- Instance ID: `i-040abe6cb917a6042`
- GPU: `Tesla T4, 15360 MiB`
- Serving: `vLLM 0.27.0` via `vllm/vllm-openai:latest`
- vLLM settings: `max_model_len=4096`, `gpu_memory_utilization=0.90`
- Benchmark concurrency: `16`

## Result

- Benchmark prompts: 64
- Input tokens: 131,320
- Generated tokens: 16,384
- Duration: 291.63 seconds
- Successful requests: 64
- Failed requests: 0
- Request throughput: 0.22 req/s
- Output tokens/sec at concurrency 16: 56.18
- Peak output tokens/sec: 144.00
- Total tokens/sec: 506.48
- Mean TTFT: 13,816.94 ms
- Median TTFT: 10,789.71 ms
- P99 TTFT: 42,290.67 ms
- Mean TPOT: 231.30 ms
- Median TPOT: 243.91 ms
- P99 TPOT: 264.50 ms
- Benchmark JSON artifact: `runs\vllm_benchmark\mistral_7b_awq_t4_c16_n64.json`

## Command

```bash
vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:8001 \
  --endpoint /v1/chat/completions \
  --model mistral-7b-instruct-v0.3-awq \
  --tokenizer solidrust/Mistral-7B-Instruct-v0.3-AWQ \
  --dataset-name random \
  --num-prompts 64 \
  --input-len 2048 \
  --output-len 256 \
  --max-concurrency 16 \
  --save-result \
  --result-dir /tmp/vllm_benchmark \
  --result-filename mistral_7b_awq_t4_c16_n64.json
```

## Measurement Boundary

- This is a dedicated vLLM throughput benchmark, not the bulk-judging throughput.
- Use wording like: `sustaining 56.18 output tok/s at concurrency 16; bulk-judged 960 answers on the same vLLM setup.`
- Do not claim 145 tok/s. The measured sustained output throughput was 56.18 tok/s; 144.00 tok/s was only peak output throughput in this benchmark.
