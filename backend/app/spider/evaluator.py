"""Execution-based verification of agent SQL against Spider gold SQL.

This wraps the vendored official evaluator rather than comparing result sets here.
Result equivalence for SQL is not "did the two lists match": the official
implementation handles row order (significant only when the gold query has an
`ORDER BY`), duplicate rows under bag semantics, and column permutation. Every one
of those is a place a hand-rolled comparison silently over- or under-counts.

**Which metric this is.** `eval_exec_match` compares denotations across every
`*.sqlite` in the database's directory. Pointed at the pinned
`datasets/spider/database/<db_id>/` folder, that is one database, so this measures
Spider **execution accuracy (EX)** on the original database. It is *not*
test-suite execution accuracy, which requires the separately distributed
distilled test-suite databases. EX can credit a wrong query that happens to agree
with gold on the one instance; documented, not silently conflated.

**Which database.** Verification runs against the pinned source database, not the
episode copy. The agent's connection is read-only and its copy is discarded, so
the source is provably pristine, and verifying against it keeps the verifier
independent of anything that happened during the episode.
"""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.app.spider.official_eval import eval_exec_match

# Per-query execution budget, in seconds.
#
# The vendored evaluator defaults to 60s **per query per database**. On the
# single-database substrate that caps a task at ~2 minutes. On the test-suite
# substrate, with ~35 instances and both gold and prediction run on each, the same
# default caps ONE task at ~70 minutes - and a full gold-pass stalled on exactly
# that, sitting on one task for over 13 minutes before it was interrupted.
#
# The budget is lowered for the test-suite substrate rather than left to hang. It
# applies symmetrically to gold and prediction, so it cannot favour either: a gold
# query that exceeds it makes the task a substrate exclusion (recorded with a
# reason), and a prediction that exceeds it fails. Set on the vendored module at
# runtime, so the pinned source hashes are untouched.
DEFAULT_QUERY_TIMEOUT_SECONDS = 60
TEST_SUITE_QUERY_TIMEOUT_SECONDS = 15


def set_query_timeout(seconds: int) -> int:
    """Set the vendored evaluator's per-query timeout. Returns the previous value."""
    import sys

    module = sys.modules.get("exec_eval")
    if module is None:  # pragma: no cover - import side effect guarantees it
        raise RuntimeError("vendored exec_eval not loaded")
    previous = module.TIMEOUT
    module.TIMEOUT = seconds
    return previous


def current_query_timeout() -> int:
    import sys

    return sys.modules["exec_eval"].TIMEOUT

# Official execution-accuracy defaults, matching `evaluation.py --etype exec`
# with no extra flags. Recorded as constants so a run artifact can state them.
PLUG_VALUE = False
KEEP_DISTINCT = False
EVALUATOR_NAME = "spider-test-suite-sql-eval"

# The metric's name in prose is **single-database execution accuracy**, used
# verbatim in every document. It is never called "test-suite accuracy": that name
# belongs to the protocol using the distilled multi-database test suite, which
# this does not use.
EVALUATOR_METRIC = "single_database_execution_accuracy"

# The identifier this metric carried before the rename. Runs frozen earlier
# persisted it, and their artifacts are immutable, so readers of old runs need to
# resolve it. Same metric, same flags, same semantics - only the label changed.
LEGACY_EVALUATOR_METRIC_IDS = frozenset({"execution_accuracy_original_db"})
KNOWN_EVALUATOR_METRIC_IDS = frozenset({EVALUATOR_METRIC}) | LEGACY_EVALUATOR_METRIC_IDS

EVALUATOR_METRIC_DISPLAY_NAME = "single-database execution accuracy"

# --------------------------------------------------------------------------
# Substrates
#
# The evaluator compares denotations across every *.sqlite in the database's
# directory. Which directory it is pointed at therefore *is* the metric:
#
#   single_db  -> datasets/spider/database/<db_id>/       (1 instance)
#   test_suite -> datasets/spider/test_suite_database/<db_id>/  (~35 instances)
#
# The test-suite substrate is strictly tighter: a query must agree with gold on
# every distilled instance, which catches queries that coincide with gold on the
# one shipped database. It is reported BESIDE the single-database metric and never
# replaces it, so the frozen P0 number stays comparable to itself.
# --------------------------------------------------------------------------

SUBSTRATE_SINGLE_DB = "single_db"
SUBSTRATE_TEST_SUITE = "test_suite"

SUBSTRATE_METRIC_IDS = {
    SUBSTRATE_SINGLE_DB: "single_database_execution_accuracy",
    SUBSTRATE_TEST_SUITE: "test_suite_execution_accuracy",
}
SUBSTRATE_DISPLAY_NAMES = {
    SUBSTRATE_SINGLE_DB: "single-database execution accuracy",
    SUBSTRATE_TEST_SUITE: "test-suite execution accuracy",
}
SUBSTRATE_DIRECTORIES = {
    SUBSTRATE_SINGLE_DB: "database",
    SUBSTRATE_TEST_SUITE: "test_suite_database",
}

_DATASET_ROOT = Path(__file__).resolve().parents[3] / "datasets" / "spider"


class SubstrateUnavailable(Exception):
    """Raised when a substrate's databases are not installed."""


def substrate_database_path(database_id: str, substrate: str) -> Path:
    """Resolve the anchor database for `database_id` under `substrate`.

    The anchor is the file handed to the evaluator; the evaluator then globs its
    directory, which is what turns one substrate into ~35 instances.
    """
    if substrate not in SUBSTRATE_DIRECTORIES:
        raise ValueError(f"Unknown substrate {substrate!r}")

    directory = _DATASET_ROOT / SUBSTRATE_DIRECTORIES[substrate] / database_id
    anchor = directory / f"{database_id}.sqlite"
    if not anchor.exists():
        raise SubstrateUnavailable(
            f"No {substrate} database for {database_id!r} at {anchor}. "
            "Run: python scripts/download_spider_test_suite.py"
        )
    return anchor


def substrate_instance_count(database_id: str, substrate: str) -> int:
    return len(list(substrate_database_path(database_id, substrate).parent.glob("*.sqlite")))


class VerificationOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    # The gold query itself failed to execute. This is a benchmark/annotation
    # defect, never an agent failure, and must be separated from FAIL so it
    # cannot quietly depress the measured accuracy.
    GOLD_ERROR = "gold_error"
    # The evaluator itself raised. Infrastructure failure, counted separately.
    EVALUATOR_ERROR = "evaluator_error"


class VerificationResult(BaseModel):
    outcome: VerificationOutcome
    passed: bool
    task_id: str
    database_id: str
    predicted_sql: str | None
    gold_sql: str
    latency_ms: float
    evaluator: str = EVALUATOR_NAME
    metric: str = EVALUATOR_METRIC
    substrate: str = SUBSTRATE_SINGLE_DB
    substrate_instances: int = 1
    query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS
    plug_value: bool = PLUG_VALUE
    keep_distinct: bool = KEEP_DISTINCT
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def verify_sql(
    predicted_sql: str | None,
    gold_sql: str,
    database_path: str | Path,
    task_id: str = "",
    database_id: str = "",
    substrate: str = SUBSTRATE_SINGLE_DB,
    instance_count: int | None = None,
) -> VerificationResult:
    """Verify one predicted query by execution.

    A `None` or blank prediction is a FAIL, not an error: an agent that produced
    no SQL did not solve the task.

    `substrate` selects which set of databases the comparison runs against. It
    only labels the result here - the actual breadth comes from `database_path`
    pointing into that substrate's directory, because the evaluator globs it.
    """
    started = time.perf_counter()
    instances = (
        instance_count
        if instance_count is not None
        else len(list(Path(database_path).parent.glob("*.sqlite")))
    )

    def finish(
        outcome: VerificationOutcome,
        error: str | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            outcome=outcome,
            passed=outcome is VerificationOutcome.PASS,
            task_id=task_id,
            database_id=database_id,
            predicted_sql=predicted_sql,
            gold_sql=gold_sql,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            metric=SUBSTRATE_METRIC_IDS[substrate],
            substrate=substrate,
            substrate_instances=instances,
            query_timeout_seconds=current_query_timeout(),
            error=error,
        )

    if predicted_sql is None or not predicted_sql.strip():
        return finish(VerificationOutcome.FAIL, "No SQL produced.")

    try:
        if substrate == SUBSTRATE_TEST_SUITE:
            # The vendored driver's timeout cannot interrupt a blocking query, and
            # ~35 instances per task makes that fatal rather than merely untidy.
            # Comparison semantics are still upstream's; only execution differs.
            from backend.app.spider.interruptible_eval import (
                GoldQueryFailed,
                eval_exec_match_interruptible,
            )

            try:
                score = eval_exec_match_interruptible(
                    db=database_path,
                    p_str=predicted_sql,
                    g_str=gold_sql,
                    keep_distinct=KEEP_DISTINCT,
                    timeout_seconds=current_query_timeout(),
                )
            except GoldQueryFailed as error:
                return finish(VerificationOutcome.GOLD_ERROR, str(error))
        else:
            score = eval_exec_match(
                db=str(database_path),
                p_str=predicted_sql,
                g_str=gold_sql,
                plug_value=PLUG_VALUE,
                keep_distinct=KEEP_DISTINCT,
                progress_bar_for_each_datapoint=False,
            )
    except AssertionError as error:
        # eval_exec_match asserts the gold query executes. That assertion firing
        # means the benchmark row is bad, not that the agent was wrong.
        return finish(VerificationOutcome.GOLD_ERROR, str(error))
    except Exception as error:  # noqa: BLE001 - surfaced as infrastructure failure
        return finish(
            VerificationOutcome.EVALUATOR_ERROR,
            f"{type(error).__name__}: {error}",
        )

    return finish(
        VerificationOutcome.PASS if score == 1 else VerificationOutcome.FAIL
    )
