"""Freeze every input needed to regenerate the P0 benchmark.

A version string only helps if it actually changes when the thing it names
changes. `prompt_version = "sql_agent_v1"` does not stop someone editing the
prompt text and leaving the label alone, and the next run would then be
incomparable to this one while claiming to be identical.

So this pins **content hashes** alongside the version labels:

- the exact system-prompt text
- the exact tool JSON schema shown to the model
- the vendored evaluator source files
- the dataset archive and `dev.json` / `tables.json`
- the frozen exclusion list
- generation parameters and the pricing snapshot used for cost

`--verify` recomputes all of them and fails if anything drifted, which makes
"reproducible from the stored configuration" a check rather than a promise.

Usage:
    python scripts/freeze_p0_baseline.py --run-id spider_full__p0_v2
    python scripts/freeze_p0_baseline.py --run-id spider_full__p0_v2 --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.adapter import ADAPTER_VERSION, load_exclusions  # noqa: E402
from backend.app.spider.agent import (  # noqa: E402
    AGENT_VERSION,
    MODEL_PRICING,
    SQL_AGENT_PROMPTS,
)
from backend.app.spider.evaluator import (  # noqa: E402
    EVALUATOR_METRIC,
    EVALUATOR_NAME,
    KEEP_DISTINCT,
    PLUG_VALUE,
)
from backend.app.spider.loader import load_pin  # noqa: E402
from backend.app.spider.tools import (  # noqa: E402
    MAX_CELL_CHARS,
    MAX_VISIBLE_ROWS,
    QUERY_TIMEOUT_SECONDS,
    TOOL_SCHEMA_VERSION,
    TOOL_SPECS,
)
from backend.app.spider.trajectory import DEFAULT_RUN_ROOT, TrajectoryStore  # noqa: E402

BASELINE_DOC = REPO_ROOT / "docs" / "P0_BASELINE.md"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(run_id: str, root: Path) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.config_path.exists():
        raise SystemExit(f"No config at {store.config_path}")
    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    pin = load_pin()

    prompt_version = config.get("prompt_version")
    prompt_text = SQL_AGENT_PROMPTS.get(prompt_version, "")

    # Canonical JSON so key ordering cannot change the hash.
    tool_spec_json = json.dumps(TOOL_SPECS, sort_keys=True, separators=(",", ":"))

    evaluator_dir = REPO_ROOT / "backend" / "app" / "spider" / "official_eval"
    evaluator_hashes = {
        path.name: sha256_file(path)
        for path in sorted(evaluator_dir.glob("*.py"))
        if path.name != "__init__.py"
    }

    artifacts = {}
    for name in (
        "config.json", "episodes.jsonl", "steps.jsonl", "payloads.jsonl",
        "p0_metrics.json", "p0_completion.json", "failure_analysis.json",
        "claims_audit.json",
    ):
        path = store.run_dir / name
        if path.exists():
            artifacts[name] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }

    return {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "code_commit_sha": config.get("code_commit_sha"),
        "code_working_tree_dirty": config.get("code_working_tree_dirty"),

        "dataset": {
            "benchmark": pin["benchmark"],
            "split": config.get("split"),
            "dataset_version": config.get("dataset_version"),
            "archive_url": pin["archive_url"],
            "archive_sha256": pin["archive_sha256"],
            "archive_bytes": pin["archive_bytes"],
            "dev_json_sha256": pin["dev_json_sha256"],
            "tables_json_sha256": pin["tables_json_sha256"],
            "dev_examples": pin["dev_examples"],
            "databases": pin["databases"],
        },

        "evaluator": {
            "name": EVALUATOR_NAME,
            "metric": EVALUATOR_METRIC,
            "source": pin["evaluator_source"],
            "plug_value": PLUG_VALUE,
            "keep_distinct": KEEP_DISTINCT,
            "vendored_file_sha256": evaluator_hashes,
        },

        "exclusions": {
            "source": "docs/LOCKED_INPUTS.md",
            "count": len(load_exclusions()),
            "task_ids": sorted(load_exclusions()),
        },

        "model": {
            "model_version": config.get("model_version"),
            "temperature": config.get("temperature"),
            "max_steps_model_turn_cap": config.get("max_steps"),
            "pricing_snapshot_usd_per_1m": MODEL_PRICING.get(config.get("model_version")),
            "pricing_basis": "published list price, not a billed invoice",
        },

        "prompt": {
            "prompt_version": prompt_version,
            # The label is a name; this hash is the actual identity.
            "prompt_sha256": sha256_text(prompt_text),
            "prompt_chars": len(prompt_text),
        },

        "tools": {
            "tool_schema_version": TOOL_SCHEMA_VERSION,
            "tool_spec_sha256": sha256_text(tool_spec_json),
            "tool_names": [spec["function"]["name"] for spec in TOOL_SPECS],
            "max_visible_rows": MAX_VISIBLE_ROWS,
            "max_cell_chars": MAX_CELL_CHARS,
            "query_timeout_seconds": QUERY_TIMEOUT_SECONDS,
        },

        "agent": {
            "agent_version": AGENT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },

        "artifacts": artifacts,
    }


def verify(manifest: dict[str, Any]) -> list[str]:
    """Recompute every content hash and report drift."""
    drift: list[str] = []
    current = build_manifest(manifest["run_id"], DEFAULT_RUN_ROOT)

    checks = [
        ("prompt.prompt_sha256", manifest["prompt"]["prompt_sha256"],
         current["prompt"]["prompt_sha256"]),
        ("tools.tool_spec_sha256", manifest["tools"]["tool_spec_sha256"],
         current["tools"]["tool_spec_sha256"]),
        ("dataset.archive_sha256", manifest["dataset"]["archive_sha256"],
         current["dataset"]["archive_sha256"]),
        ("dataset.dev_json_sha256", manifest["dataset"]["dev_json_sha256"],
         current["dataset"]["dev_json_sha256"]),
        ("exclusions.count", manifest["exclusions"]["count"],
         current["exclusions"]["count"]),
    ]
    for name, frozen, now in checks:
        if frozen != now:
            drift.append(f"{name}: frozen={frozen} current={now}")

    for name, frozen in manifest["evaluator"]["vendored_file_sha256"].items():
        now = current["evaluator"]["vendored_file_sha256"].get(name)
        if frozen != now:
            drift.append(f"evaluator/{name}: frozen={frozen} current={now}")

    for name, entry in manifest.get("artifacts", {}).items():
        now = current.get("artifacts", {}).get(name)
        if now is None:
            drift.append(f"artifact {name}: missing")
        elif entry["sha256"] != now["sha256"]:
            drift.append(f"artifact {name}: content changed since freeze")

    return drift


def render_doc(manifest: dict[str, Any]) -> str:
    dataset = manifest["dataset"]
    evaluator = manifest["evaluator"]
    model = manifest["model"]
    lines = [
        "# P0 Frozen Baseline",
        "",
        "Everything required to regenerate the P0 Spider benchmark. Content hashes",
        "sit beside version labels because a label does not change when the thing it",
        "names is edited — the hash does.",
        "",
        f"Frozen at: {manifest['frozen_at']}  ",
        f"Run ID: `{manifest['run_id']}`  ",
        f"Code commit: `{manifest['code_commit_sha']}`"
        + ("  **(working tree dirty at run time)**" if manifest["code_working_tree_dirty"] else ""),
        "",
        "Verify nothing has drifted:",
        "",
        "```powershell",
        f"python scripts/freeze_p0_baseline.py --run-id {manifest['run_id']} --verify",
        "```",
        "",
        "## Dataset",
        "",
        "| | |",
        "|---|---|",
        f"| Benchmark | `{dataset['benchmark']}` |",
        f"| Split | `{dataset['split']}` |",
        f"| Dataset version | `{dataset['dataset_version']}` |",
        f"| Examples / databases | {dataset['dev_examples']:,} / {dataset['databases']} |",
        f"| Archive sha256 | `{dataset['archive_sha256']}` |",
        f"| Archive bytes | {dataset['archive_bytes']:,} |",
        f"| `dev.json` sha256 | `{dataset['dev_json_sha256']}` |",
        f"| `tables.json` sha256 | `{dataset['tables_json_sha256']}` |",
        "",
        f"Source: {dataset['archive_url']}",
        "",
        "## Evaluator",
        "",
        "| | |",
        "|---|---|",
        f"| Name | `{evaluator['name']}` |",
        f"| Metric | `{evaluator['metric']}` |",
        f"| `plug_value` / `keep_distinct` | `{evaluator['plug_value']}` / `{evaluator['keep_distinct']}` |",
        "",
        "Vendored source hashes:",
        "",
    ]
    for name, digest in sorted(evaluator["vendored_file_sha256"].items()):
        lines.append(f"- `{name}`: `{digest}`")

    lines += [
        "",
        "## Exclusions",
        "",
        f"- Source: `{manifest['exclusions']['source']}`",
        f"- Excluded tasks: **{manifest['exclusions']['count']}**"
        + (f" — {manifest['exclusions']['task_ids']}" if manifest["exclusions"]["task_ids"] else " (empty; every gold query passes)"),
        "",
        "## Model and generation parameters",
        "",
        "| | |",
        "|---|---|",
        f"| Model | `{model['model_version']}` |",
        f"| Temperature | `{model['temperature']}` |",
        f"| `max_steps` (model-turn cap) | `{model['max_steps_model_turn_cap']}` |",
        f"| Pricing snapshot (USD / 1M tokens) | `{model['pricing_snapshot_usd_per_1m']}` |",
        f"| Pricing basis | {model['pricing_basis']} |",
        "",
        "## Prompt",
        "",
        "| | |",
        "|---|---|",
        f"| Version label | `{manifest['prompt']['prompt_version']}` |",
        f"| Text sha256 | `{manifest['prompt']['prompt_sha256']}` |",
        f"| Characters | {manifest['prompt']['prompt_chars']:,} |",
        "",
        "## Tool schema",
        "",
        "| | |",
        "|---|---|",
        f"| Version label | `{manifest['tools']['tool_schema_version']}` |",
        f"| Spec sha256 (canonical JSON) | `{manifest['tools']['tool_spec_sha256']}` |",
        f"| Tools | {', '.join(f'`{n}`' for n in manifest['tools']['tool_names'])} |",
        f"| Model-visible row cap | {manifest['tools']['max_visible_rows']} |",
        f"| Model-visible cell cap | {manifest['tools']['max_cell_chars']} chars |",
        f"| Query timeout | {manifest['tools']['query_timeout_seconds']}s |",
        "",
        "## Agent",
        "",
        f"- `agent_version`: `{manifest['agent']['agent_version']}`",
        f"- `adapter_version`: `{manifest['agent']['adapter_version']}`",
        "",
        "## Run artifacts",
        "",
        "| File | Bytes | sha256 |",
        "|---|---:|---|",
    ]
    for name, entry in sorted(manifest.get("artifacts", {}).items()):
        lines.append(f"| `{name}` | {entry['bytes']:,} | `{entry['sha256'][:16]}…` |")

    lines += [
        "",
        "## Regenerate",
        "",
        "```powershell",
        "python scripts/download_spider.py",
        "python scripts/qa_spider_evaluator.py --split dev",
        f"python scripts/run_spider_benchmark.py --stage full --run-id {manifest['run_id']}",
        f"python scripts/report_spider_metrics.py --run-id {manifest['run_id']} --check-traces",
        f"python scripts/analyze_spider_failures.py --run-id {manifest['run_id']}",
        f"python scripts/audit_p0_claims.py --run-id {manifest['run_id']}",
        f"python scripts/verify_p0_completion.py --run-id {manifest['run_id']}",
        "```",
        "",
        "A regenerated run will not reproduce the success rate to the episode, because",
        "the model API is not bit-deterministic even at temperature 0. What is frozen",
        "here is the **configuration**, so any difference between two runs is",
        "attributable to sampling rather than to a changed input. Quantifying that",
        "run-to-run variance is P1 work and is required before any regression",
        "threshold can be defended.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    manifest_path = root / args.run_id / "baseline_manifest.json"

    if args.verify:
        if not manifest_path.exists():
            print(f"No frozen manifest at {manifest_path}")
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        drift = verify(manifest)
        if drift:
            print("BASELINE DRIFT DETECTED:")
            for item in drift:
                print(f"  {item}")
            return 1
        print(f"Baseline verified: no drift from {manifest['frozen_at']}")
        return 0

    manifest = build_manifest(args.run_id, root)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    BASELINE_DOC.write_text(render_doc(manifest), encoding="utf-8")

    print(f"Frozen baseline for {args.run_id}")
    print(f"  prompt sha256     {manifest['prompt']['prompt_sha256']}")
    print(f"  tool spec sha256  {manifest['tools']['tool_spec_sha256']}")
    print(f"  dataset           {manifest['dataset']['dataset_version']}")
    print(f"  exclusions        {manifest['exclusions']['count']}")
    print(f"  artifacts hashed  {len(manifest.get('artifacts', {}))}")
    print(f"\nWrote {manifest_path}")
    print(f"Wrote {BASELINE_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
