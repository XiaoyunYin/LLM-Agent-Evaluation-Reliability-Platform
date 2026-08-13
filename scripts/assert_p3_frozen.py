"""Assert the live benchmark still matches the frozen manifest.

Run before every paid P3 run. The failure this prevents is the expensive one: a
run that completes, produces plausible numbers, and silently measured a different
benchmark than the one it is compared against. P0 lost a full run to exactly that
(episodes from a pre-tag commit landed in a post-tag run directory), and the only
reason it was caught was a row count that did not add up.

Content hashes, not version strings: a version string is a promise, a hash is a
measurement. The suite hash covers every task spec, so an edit to a single
required change breaks it even if nobody bumped a version.

    python -m scripts.assert_p3_frozen          # exit 0 if identical
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.support.agent import (  # noqa: E402
    AGENT_VERSION,
    PROMPT_VERSION,
    SupportAgentConfig,
)
from backend.app.support.normalize import NORMALIZATION_VERSION  # noqa: E402
from backend.app.support.schema import (  # noqa: E402
    DEFAULT_TICKET_COUNT,
    FIXTURE_VERSION,
    SCHEMA_VERSION,
    build_fixture,
)
from backend.app.support.tasks import TASK_FAMILY_VERSION, build_tasks  # noqa: E402
from backend.app.support.tools import TOOL_SCHEMA_VERSION  # noqa: E402
from backend.app.support.verifier import VERIFIER_VERSION  # noqa: E402

MANIFEST = REPO_ROOT / "config" / "p3_frozen_manifest.json"
FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"


def observed() -> dict:
    fixture_sha = build_fixture(FIXTURE_PATH, DEFAULT_TICKET_COUNT)
    tasks = build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)
    payload = json.dumps(
        [entry["spec"].model_dump() for entry in tasks], sort_keys=True, default=str
    )
    config = SupportAgentConfig()
    return {
        "fixture_version": FIXTURE_VERSION,
        "fixture_sha256": fixture_sha,
        "ticket_count": DEFAULT_TICKET_COUNT,
        "schema_version": SCHEMA_VERSION,
        "task_family_version": TASK_FAMILY_VERSION,
        "suite_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "agent_version": AGENT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "max_steps": config.max_steps,
        "empty_result_policy": config.empty_result_policy,
        "task_count": len(tasks),
    }


def main() -> int:
    if not MANIFEST.exists():
        print(f"no frozen manifest at {MANIFEST}")
        return 1
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    live = observed()

    # schema_repair_enabled is deliberately excluded: it is the treatment flag, so
    # a treatment run MUST differ from the frozen default. Everything the flag does
    # not control has to be identical, which is what makes the comparison paired.
    drift = {
        key: (frozen.get(key), value)
        for key, value in live.items()
        if frozen.get(key) != value
    }
    if drift:
        print("BENCHMARK DRIFT - do not run:")
        for key, (was, now) in sorted(drift.items()):
            print(f"  {key}\n      frozen {was}\n      live   {now}")
        return 1

    print(f"frozen benchmark intact: {live['task_count']} tasks, "
          f"suite {live['suite_sha256'][:12]}, budget {live['max_steps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
