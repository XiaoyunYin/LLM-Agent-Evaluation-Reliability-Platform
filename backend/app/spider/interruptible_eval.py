"""Execution driver for the official Spider comparison, with a working timeout.

**Why this exists.** The vendored `eval_exec_match` runs each query as:

    await asyncio.wait_for(exec_on_db_(path, query), timeout)

but `exec_on_db_` calls a blocking `cursor.execute(...)`. A coroutine that never
awaits cannot be cancelled, so `wait_for` only fires *after* the query finishes.
The timeout is therefore inert for exactly the queries it exists to bound.

On the single-database substrate that is survivable. On the test-suite substrate,
where ~35 instances run both gold and prediction, one slow query stalls everything:
a full gold-pass sat on a single task for over 13 minutes, twice, before being
interrupted — and lowering the documented timeout changed nothing, because the
timeout was never the thing in control.

**What this changes, and what it does not.** Execution is driven here, using
SQLite's `set_progress_handler` to interrupt inside the C loop, which actually
works. Result comparison is still upstream's:

- `result_eq`        — row order, bag semantics, column permutation
- `remove_distinct`  — applied when `keep_distinct=False`
- `postprocess`      — the `> =` / `< =` / `! =` normalisation

Those are the subtle parts, and they are imported from the vendored source rather
than reimplemented, so the pinned hashes still describe the semantics in force.

The budget applies symmetrically to gold and prediction, so it cannot favour
either. A gold query that exceeds it makes the task a substrate exclusion; a
prediction that exceeds it fails.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from backend.app.spider.official_eval import result_eq

# Imported from the vendored modules loaded by `official_eval`.
import exec_eval  # noqa: E402  (registered in sys.modules by official_eval)
import parse  # noqa: E402


class GoldQueryFailed(Exception):
    """The gold query errored or timed out on an instance of this substrate."""


class QueryTimeout(Exception):
    """A query exceeded the per-query budget."""


def _execute(database: Path, query: str, timeout_seconds: float) -> list[tuple]:
    """Run one query with a genuinely enforceable time budget.

    The progress handler is called every N VM instructions and can abort the
    statement from inside SQLite, which is what makes the budget real.
    """
    connection = sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro", uri=True, timeout=timeout_seconds
    )
    connection.text_factory = lambda value: value.decode(errors="ignore")

    deadline = time.monotonic() + timeout_seconds
    connection.set_progress_handler(
        lambda: 1 if time.monotonic() > deadline else 0, 2_000
    )
    try:
        return connection.execute(query).fetchall()
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error).lower():
            raise QueryTimeout(f"exceeded {timeout_seconds}s") from error
        raise
    finally:
        connection.set_progress_handler(None, 0)
        connection.close()


def eval_exec_match_interruptible(
    db: str | Path,
    p_str: str,
    g_str: str,
    keep_distinct: bool = False,
    timeout_seconds: float = 15.0,
) -> int:
    """Upstream's comparison, with execution we can actually bound.

    Returns 1 when the prediction matches gold on every instance, else 0.
    Raises `GoldQueryFailed` when gold cannot be evaluated, which the caller turns
    into a substrate exclusion rather than an agent failure.
    """
    predicted, gold = exec_eval.postprocess(p_str), exec_eval.postprocess(g_str)
    if not keep_distinct:
        predicted = parse.remove_distinct(predicted)
        gold = parse.remove_distinct(gold)

    # Upstream's rule: row order matters only when gold sorts.
    order_matters = "order by" in gold.lower()

    directory = Path(db).parent
    instances = sorted(directory.glob("*.sqlite"))
    if not instances:
        raise GoldQueryFailed(f"no database instances under {directory}")

    for instance in instances:
        try:
            gold_rows = _execute(instance, gold, timeout_seconds)
        except QueryTimeout as error:
            raise GoldQueryFailed(
                f"gold query exceeded {timeout_seconds}s on {instance.name}"
            ) from error
        except sqlite3.Error as error:
            raise GoldQueryFailed(
                f"gold query failed on {instance.name}: {error}"
            ) from error

        try:
            predicted_rows = _execute(instance, predicted, timeout_seconds)
        except (QueryTimeout, sqlite3.Error):
            # A prediction that errors or runs too long is simply wrong here.
            return 0

        if not result_eq(gold_rows, predicted_rows, order_matters=order_matters):
            return 0

    return 1
