# P0 Frozen Baseline

**"The P0 baseline" means run `spider_full__p0_v2` and no other run.**
Any other full run in this repository is a repeat or comparison run.

Everything required to regenerate the P0 Spider benchmark. Content hashes
sit beside version labels because a label does not change when the thing it
names is edited — the hash does.

Frozen at: 2026-08-13T05:20:50.253461+00:00  
Run ID: `spider_full__p0_v2`  
Code commit: `ff9a4945be7cc1d8ac9bcdc5c9f19c7e97a1cea7`  **(working tree dirty at run time)**

Verify nothing has drifted:

```powershell
python scripts/freeze_p0_baseline.py --run-id spider_full__p0_v2 --verify
```

## Dataset

| | |
|---|---|
| Benchmark | `spider-1.0` |
| Split | `dev` |
| Dataset version | `spider-1.0:dev:30d64a3fccde` |
| Examples / databases | 1,034 / 166 |
| Archive sha256 | `5ddff97bb1d421282c593e8d30ce0ce107270f4dd4a21d60eba4bf287d5956b1` |
| Archive bytes | 99,736,136 |
| `dev.json` sha256 | `30d64a3fccde493226df79687aed9e4a1c0129525baf44f29c0573d914d758a4` |
| `tables.json` sha256 | `61bb20aa401f03164e2d7f3b16509b7b5f79cc9c943ca7bd159046df1159e2ed` |

Source: https://drive.usercontent.google.com/download?id=1TqleXec_OykOYFREKKtschzY29dUcVAQ&export=download&confirm=t

## Evaluator

| | |
|---|---|
| Name | `spider-test-suite-sql-eval` |
| Metric | `single_database_execution_accuracy` |
| `plug_value` / `keep_distinct` | `False` / `False` |

Vendored source hashes:

- `evaluation.py`: `7401e4014a8955376a7919c06903a7f0ab403c99e89f94204cd8f4c8e32ae779`
- `exec_eval.py`: `29d034db28904490c28037537a14fbb0150b6e86cef0049076c0511d6b6b77f7`
- `parse.py`: `ef04211a6e1c1e142571157f5c1999613e3451084c044083b2de1977f1f622c5`
- `process_sql.py`: `927fc564f7a8e34f09f009a2f5564a83fdf95226440dde84c87871fd65fe55a1`

## Exclusions

- Source: `docs/LOCKED_INPUTS.md`
- Excluded tasks: **0** (empty; every gold query passes)

## Model and generation parameters

| | |
|---|---|
| Model | `gpt-4o-mini` |
| Temperature | `0.0` |
| `top_p` | not sent; provider default applied |
| `seed` | **not sent** |
| Resolved model revision | not captured for this run; captured on runs after this freeze |
| `max_steps` (model-turn cap) | `10` |
| Pricing snapshot (USD / 1M tokens) | `{'input': 0.15, 'cached_input': 0.075, 'output': 0.6}` |
| Pricing basis | published list price, not a billed invoice |

Repeated executions of this configuration are 'repeated runs under an identical recorded configuration'. They are NOT seeded runs and are not bitwise reproducible.

## Prompt

| | |
|---|---|
| Version label | `sql_agent_v1` |
| Text sha256 | `8bb3c2b460bb130dcaf8b4bacf7ea3ddfcad10ac662adb5fd6749494fb040d55` |
| Characters | 773 |

## Tool schema

| | |
|---|---|
| Version label | `spider_tools_v2` |
| Spec sha256 (canonical JSON) | `a0ca63507c9d18913b8e3febfd1ba22fd698595ea796da8ac43603f1bc633a7a` |
| Tools | `inspect_schema`, `execute_sql`, `submit_answer` |
| Model-visible row cap | 20 |
| Model-visible cell cap | 200 chars |
| Query timeout | 30.0s |

## Agent

- `agent_version`: `spider_langgraph_agent_v1`
- `adapter_version`: `spider_adapter_v1`

## Run artifacts

| File | Bytes | sha256 |
|---|---:|---|
| `claims_audit.json` | 18,948 | `c621d07ff6f995a0…` |
| `config.json` | 51,229 | `c01c1b3b2a4ed602…` |
| `episodes.jsonl` | 1,409,724 | `1705b56e94ec7728…` |
| `failure_analysis.json` | 36,422 | `cece8099b8762849…` |
| `p0_completion.json` | 5,152 | `fe59f883296d9ba3…` |
| `p0_metrics.json` | 4,743 | `699dfc59445ec42a…` |
| `steps.jsonl` | 5,596,027 | `5112a98bd8a23242…` |

## Regenerate

```powershell
python scripts/download_spider.py
python scripts/qa_spider_evaluator.py --split dev
python scripts/run_spider_benchmark.py --stage full --run-id spider_full__p0_v2
python scripts/report_spider_metrics.py --run-id spider_full__p0_v2 --check-traces
python scripts/analyze_spider_failures.py --run-id spider_full__p0_v2
python scripts/audit_p0_claims.py --run-id spider_full__p0_v2
python scripts/verify_p0_completion.py --run-id spider_full__p0_v2
```

A regenerated run will not reproduce the success rate to the episode, because
the model API is not bit-deterministic even at temperature 0. What is frozen
here is the **configuration**, so any difference between two runs is
attributable to sampling rather than to a changed input. Quantifying that
run-to-run variance is P1 work and is required before any regression
threshold can be defended.
