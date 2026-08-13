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
) -> VerificationResult:
    """Verify one predicted query by execution.

    A `None` or blank prediction is a FAIL, not an error: an agent that produced
    no SQL did not solve the task.
    """
    started = time.perf_counter()

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
            error=error,
        )

    if predicted_sql is None or not predicted_sql.strip():
        return finish(VerificationOutcome.FAIL, "No SQL produced.")

    try:
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
