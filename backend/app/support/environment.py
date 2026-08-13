"""Per-episode isolated support database with before/after snapshots.

Same isolation guarantee as P0's Spider environment, with one deliberate
difference: **this connection is writable**. P3 is about effects, so the agent
must be able to mutate — which makes isolation the only thing standing between one
episode and the next.

Every episode gets its own copy in its own directory, snapshotted before the agent
starts and after it finishes, and destroyed at the end. The fixture is never
opened for writing.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any

from backend.app.support.normalize import diff, snapshot


class SupportEnvironment:
    """An episode-scoped writable copy of the support database."""

    def __init__(
        self,
        fixture_path: str | Path,
        episode_id: str | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self.fixture_path = Path(fixture_path)
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"No fixture at {self.fixture_path}")

        self.episode_id = episode_id or uuid.uuid4().hex
        base = Path(workspace) if workspace else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        self.episode_dir = base / f"support_episode_{self.episode_id}"
        self.episode_path = self.episode_dir / "support.sqlite"

        self._connection: sqlite3.Connection | None = None
        self.before_state: dict[str, Any] | None = None
        self.after_state: dict[str, Any] | None = None

    def setup(self) -> "SupportEnvironment":
        self.episode_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.fixture_path, self.episode_path)
        self.before_state = snapshot(self.connect())
        return self

    def connect(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(self.episode_path, timeout=30)
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection = connection
        return self._connection

    def capture_after(self) -> dict[str, Any]:
        self.after_state = snapshot(self.connect())
        return self.after_state

    def state_diff(self) -> list[dict[str, Any]]:
        if self.before_state is None:
            raise RuntimeError("setup() was not called")
        if self.after_state is None:
            self.capture_after()
        return diff(self.before_state, self.after_state)

    def cleanup(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None
        shutil.rmtree(self.episode_dir, ignore_errors=True)

    def __enter__(self) -> "SupportEnvironment":
        return self.setup()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # The after-state is captured before teardown so a raising episode still
        # produces a diff. An episode that crashed mid-mutation is exactly the
        # case where the resulting state matters most.
        if self.after_state is None and self._connection is not None:
            try:
                self.capture_after()
            except Exception:  # noqa: BLE001
                pass
        self.cleanup()
