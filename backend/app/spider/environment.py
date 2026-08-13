"""Per-episode isolated SQLite environments with read-only agent access.

Two independent guarantees, because either one alone has a hole:

1. **Isolation by copy.** Every episode gets its own copy of the Spider database.
   If a write ever did land, it lands on a throwaway file and cannot leak into a
   later episode or corrupt the pinned dataset. Without this, one escaped `UPDATE`
   would silently change the ground truth every subsequent run is scored against.

2. **Read-only by connection.** The agent connection is opened with SQLite's URI
   `mode=ro`, so writes are rejected by SQLite itself rather than by a pattern
   match this project maintains. A statement guard runs *in front* of that, but
   only to turn the rejection into a clean, model-readable tool error and to block
   multi-statement payloads and `ATTACH`, which `mode=ro` does not stop.

The guard is deliberately the outer layer and not the only layer: string-matching
SQL is defeatable, so it must never be the thing standing between an agent and the
dataset.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import TracebackType

import sqlparse

# Statement types SQLite's `mode=ro` would allow but the benchmark should not.
# ATTACH can reach a second, writable database file; PRAGMA can change connection
# semantics under the evaluator's feet.
BLOCKED_KEYWORDS = frozenset({"ATTACH", "DETACH", "PRAGMA", "VACUUM"})

# The only statement forms an evaluated SQL answer may take.
ALLOWED_STATEMENT_TYPES = frozenset({"SELECT"})


class ReadOnlyViolation(Exception):
    """Raised when a query is rejected before it reaches SQLite."""


def _first_keyword(statement: sqlparse.sql.Statement) -> str:
    for token in statement.tokens:
        if token.is_whitespace or token.ttype in sqlparse.tokens.Comment:
            continue
        return token.value.upper()
    return ""


def assert_read_only(query: str) -> None:
    """Reject anything that is not a single read-only statement.

    Raises `ReadOnlyViolation` with a message the agent can act on. Blocking
    multi-statement input matters most: `SELECT 1; DROP TABLE t` is one string to
    a naive prefix check and two statements to a database.
    """
    if not query or not query.strip():
        raise ReadOnlyViolation("Empty query.")

    statements = [s for s in sqlparse.parse(query) if str(s).strip().rstrip(";").strip()]

    if not statements:
        raise ReadOnlyViolation("Empty query.")
    if len(statements) > 1:
        raise ReadOnlyViolation(
            f"Only one statement per call is allowed; got {len(statements)}."
        )

    statement = statements[0]
    statement_type = statement.get_type().upper()
    keyword = _first_keyword(statement)

    if keyword in BLOCKED_KEYWORDS:
        raise ReadOnlyViolation(f"{keyword} is not permitted in this environment.")

    # sqlparse reports a leading CTE as UNKNOWN, so WITH is accepted explicitly.
    if statement_type not in ALLOWED_STATEMENT_TYPES and keyword != "WITH":
        reported = statement_type if statement_type != "UNKNOWN" else keyword or "?"
        raise ReadOnlyViolation(
            f"Only read-only SELECT queries are permitted; got {reported}."
        )


class EpisodeDatabase:
    """An episode-scoped copy of a Spider database, opened read-only.

    Use as a context manager so the copy is removed even when the episode raises:

        with EpisodeDatabase(task.database_path, episode_id) as db:
            rows = db.execute("SELECT 1")
    """

    def __init__(
        self,
        source_path: str | Path,
        episode_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self.source_path = Path(source_path)
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source database not found: {self.source_path}")

        self.episode_id = episode_id or uuid.uuid4().hex
        self._workspace = Path(workspace) if workspace else Path(tempfile.gettempdir())
        self._workspace.mkdir(parents=True, exist_ok=True)

        # The evaluator enumerates every *.sqlite in the copy's directory, so each
        # episode needs its own directory, not just its own filename.
        self.episode_dir = self._workspace / f"episode_{self.episode_id}"
        self.episode_path = self.episode_dir / self.source_path.name

        self._connection: sqlite3.Connection | None = None
        self._closed = False

    def setup(self) -> "EpisodeDatabase":
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.source_path, self.episode_path)
        return self

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if not self.episode_path.exists():
                raise RuntimeError("Episode database not set up; call setup() first.")
            uri = f"file:{self.episode_path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30)
            # Spider databases contain rows that are not valid UTF-8. The official
            # evaluator applies the same decoding fallback, so results compared
            # against it must decode identically.
            connection.text_factory = lambda value: value.decode(errors="ignore")
            self._connection = connection
        return self._connection

    def execute(
        self,
        query: str,
        timeout_seconds: float | None = None,
    ) -> tuple[list[str], list[tuple]]:
        """Run a read-only query and return `(column_names, rows)`.

        `timeout_seconds` uses SQLite's progress handler rather than a thread, so a
        runaway query is interrupted inside the C loop instead of being abandoned
        while it keeps burning CPU.
        """
        assert_read_only(query)
        connection = self.connect()

        if timeout_seconds is not None:
            import time

            deadline = time.monotonic() + timeout_seconds

            def _interrupt_if_expired() -> int:
                return 1 if time.monotonic() > deadline else 0

            connection.set_progress_handler(_interrupt_if_expired, 10_000)

        try:
            cursor = connection.execute(query)
            columns = [description[0] for description in (cursor.description or [])]
            rows = cursor.fetchall()
            cursor.close()
            return columns, rows
        finally:
            if timeout_seconds is not None:
                connection.set_progress_handler(None, 0)

    def cleanup(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None
        shutil.rmtree(self.episode_dir, ignore_errors=True)
        self._closed = True

    def __enter__(self) -> "EpisodeDatabase":
        return self.setup()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()
