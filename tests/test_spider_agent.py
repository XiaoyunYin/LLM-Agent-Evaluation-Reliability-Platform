"""Tests for the Spider SQL-agent evaluation path (P0).

Split into two groups:

- Tests that build their own tiny SQLite database run everywhere, including CI,
  where the 1 GB Spider download is not present.
- Tests that need the real benchmark are marked `spider_data` and skip cleanly
  when `datasets/spider` has not been fetched.

The failure-path tests matter most. A benchmark that only proves the happy path
will happily report an infrastructure outage as a model quality drop.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.app.spider.agent import (
    AgentConfig,
    SpiderSQLAgent,
    build_graph,
    estimate_cost,
)
from backend.app.spider.environment import (
    EpisodeDatabase,
    ReadOnlyViolation,
    assert_read_only,
)
from backend.app.spider.evaluator import VerificationOutcome, verify_sql
from backend.app.spider.loader import SQLTask
from backend.app.spider.mock_client import MockOpenAIClient
from backend.app.spider.tools import (
    MAX_VISIBLE_ROWS,
    execute_sql,
    inspect_schema,
    validate_tool_arguments,
)
from backend.app.spider.trajectory import (
    AgentEpisode,
    TerminationReason,
    TrajectoryStore,
)

SPIDER_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "spider"
requires_spider = pytest.mark.skipif(
    not (SPIDER_ROOT / "dev.json").exists(),
    reason="Spider not downloaded; run scripts/download_spider.py",
)


@pytest.fixture
def tiny_database(tmp_path: Path) -> Path:
    """A two-table database with a foreign key and enough rows to test capping."""
    path = tmp_path / "source" / "tiny.sqlite"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE artist (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INT);
        CREATE TABLE album (
            id INTEGER PRIMARY KEY,
            title TEXT,
            artist_id INT REFERENCES artist(id)
        );
        """
    )
    connection.executemany(
        "INSERT INTO artist (id, name, age) VALUES (?, ?, ?)",
        [(i, f"artist_{i}", 20 + i) for i in range(1, 51)],
    )
    connection.executemany(
        "INSERT INTO album (id, title, artist_id) VALUES (?, ?, ?)",
        [(i, f"album_{i}", i) for i in range(1, 51)],
    )
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def episode(tiny_database: Path, tmp_path: Path):
    database = EpisodeDatabase(tiny_database, "test_episode", tmp_path / "work")
    database.setup()
    yield database
    database.cleanup()


@pytest.fixture
def task(tiny_database: Path) -> SQLTask:
    return SQLTask(
        task_id="tiny_0001",
        question="How many artists are there?",
        database_id="tiny",
        database_path=str(tiny_database),
        gold_query="SELECT count(*) FROM artist",
        split="test",
    )


# --------------------------------------------------------------------------
# Read-only enforcement
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO artist VALUES (99, 'x', 1)",
        "UPDATE artist SET name = 'x'",
        "DELETE FROM artist",
        "DROP TABLE artist",
        "ALTER TABLE artist ADD COLUMN c INT",
        "CREATE TABLE evil (a INT)",
        "ATTACH DATABASE 'other.db' AS other",
        "PRAGMA writable_schema = 1",
        "SELECT 1; DROP TABLE artist",
        "",
    ],
)
def test_guard_rejects_non_read_queries(query):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM artist",
        "select name from artist where age > 30",
        "WITH a AS (SELECT * FROM artist) SELECT count(*) FROM a",
        "SELECT * FROM artist;",
    ],
)
def test_guard_allows_read_queries(query):
    assert_read_only(query)


def test_sqlite_rejects_writes_even_when_the_guard_is_bypassed(episode):
    """The guard is defence in depth, not the only defence.

    String-matching SQL is defeatable. If the guard were the only layer, one
    parser gap would put the pinned dataset at risk.
    """
    connection = episode.connect()
    with pytest.raises(sqlite3.Error):
        connection.execute("DELETE FROM artist")


def test_episode_uses_a_copy_and_cleans_it_up(tiny_database: Path, tmp_path: Path):
    original_bytes = tiny_database.read_bytes()

    database = EpisodeDatabase(tiny_database, "cleanup_probe", tmp_path / "work")
    database.setup()
    assert database.episode_path.exists()
    assert database.episode_path != tiny_database
    database.cleanup()

    assert not database.episode_dir.exists()
    assert tiny_database.read_bytes() == original_bytes


def test_two_episodes_get_separate_directories(tiny_database: Path, tmp_path: Path):
    """The evaluator globs every *.sqlite beside the database, so sharing a
    directory would make one episode's copy visible to another's verification."""
    with EpisodeDatabase(tiny_database, "a", tmp_path) as first:
        with EpisodeDatabase(tiny_database, "b", tmp_path) as second:
            assert first.episode_dir != second.episode_dir
            assert list(first.episode_dir.glob("*.sqlite")) == [first.episode_path]


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def test_inspect_schema_lists_tables(episode):
    result = inspect_schema(episode)
    assert result.success
    tables = {row["table"] for row in result.model_visible["tables"]}
    assert tables == {"artist", "album"}


def test_inspect_schema_describes_one_table(episode):
    result = inspect_schema(episode, "album")
    assert result.success
    visible = result.model_visible
    assert [column["name"] for column in visible["columns"]] == ["id", "title", "artist_id"]
    assert visible["primary_key"] == ["id"]
    assert visible["foreign_keys"] == [
        {"column": "artist_id", "references_table": "artist", "references_column": "id"}
    ]


def test_inspect_schema_unknown_table_is_recoverable(episode):
    result = inspect_schema(episode, "nope")
    assert not result.success
    # The model gets a usable list back rather than an exception ending the run.
    assert "artist" in result.model_visible["available_tables"]


def test_execute_sql_caps_visible_rows_but_keeps_the_full_result(episode):
    result = execute_sql(episode, "SELECT * FROM artist")
    assert result.success
    assert result.model_visible["row_count"] == 50
    assert len(result.model_visible["rows"]) == MAX_VISIBLE_ROWS
    assert result.model_visible["truncated"] is True
    # The whole result is persisted, just never sent to the model.
    assert len(result.full_result["rows"]) == 50


def test_execute_sql_returns_errors_instead_of_raising(episode):
    result = execute_sql(episode, "SELECT nope FROM artist")
    assert not result.success
    assert "no such column" in result.model_visible["error"]
    assert result.model_visible["rows"] == []


def test_execute_sql_rejects_writes(episode):
    result = execute_sql(episode, "DELETE FROM artist")
    assert not result.success
    assert "read-only" in result.model_visible["error"].lower()


# --------------------------------------------------------------------------
# Tool-argument validation
#
# Regression tests for a defect measured in the Step 13 smoke run: the model
# calls `inspect_schema({"table": ...})`, the tool read only `table_name`, and the
# unknown key was silently ignored - so the agent got the table *list* back,
# looking like success, and looped until it ran out of steps. 3 of 10 episodes
# were lost to it.
# --------------------------------------------------------------------------


def test_unknown_argument_is_rejected_with_the_accepted_name(episode):
    error = validate_tool_arguments("inspect_schema", {"table": "artist"})
    assert error is not None
    # The message has to be actionable, or the model cannot recover from it.
    assert "table_name" in error
    assert "table" in error


def test_missing_required_argument_is_rejected():
    error = validate_tool_arguments("execute_sql", {})
    assert error is not None and "query" in error


def test_valid_arguments_pass_validation():
    assert validate_tool_arguments("inspect_schema", {}) is None
    assert validate_tool_arguments("inspect_schema", {"table_name": "artist"}) is None
    assert validate_tool_arguments("execute_sql", {"query": "SELECT 1"}) is None


def test_wrong_argument_name_does_not_silently_return_the_table_list(task, tmp_path: Path):
    """The end-to-end version of the same defect.

    An agent that keeps calling `inspect_schema({"table": ...})` must be told it
    is wrong, not handed a successful-looking response forever.
    """
    client = MockOpenAIClient(script=[("inspect_schema", {"table": "artist"})] * 20)
    agent = SpiderSQLAgent(client, AgentConfig(max_steps=3))
    store = TrajectoryStore("bad_arg_run", tmp_path / "runs")
    agent.run_episode(
        task=task,
        run_id="bad_arg_run",
        store=store,
        dataset_version="test:v1",
        workspace=str(tmp_path / "work"),
    )

    tool_steps = [s for s in store.iter_steps() if s["step_type"] == "tool"]
    assert tool_steps, "expected tool steps"
    assert all(step["tool_success"] is False for step in tool_steps)

    # The rejection reason must reach the persisted payload, not only the
    # conversation. An empty tool_result payload leaves the audit trail unable to
    # say *why* a call failed.
    payloads = {
        json.loads(line)["ref"]: json.loads(line)["data"]
        for line in store.payloads_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for step in tool_steps:
        payload = payloads.get(step["tool_result_ref"])
        assert payload, f"empty tool_result payload on step {step['step_index']}"
        assert "table_name" in payload["error"]


def test_submit_answer_with_a_wrong_argument_name_is_not_scored_as_no_final_sql(
    task, tmp_path: Path
):
    """A naming slip on submit must not be recorded as "never produced an answer"."""
    client = MockOpenAIClient(
        script=[("submit_answer", {"sql": task.gold_query})] * 3
        + [("submit_answer", {"query": task.gold_query})]
    )
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    assert episode.termination_reason is TerminationReason.SUCCESS
    assert episode.final_sql == task.gold_query


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


def test_gold_query_passes_verification(task):
    result = verify_sql(
        task.gold_query, task.gold_query, task.database_path, task.task_id, task.database_id
    )
    assert result.outcome is VerificationOutcome.PASS
    assert result.passed


def test_wrong_query_fails_verification(task):
    result = verify_sql(
        "SELECT count(*) FROM album WHERE id < 10",
        task.gold_query,
        task.database_path,
        task.task_id,
        task.database_id,
    )
    assert result.outcome is VerificationOutcome.FAIL
    assert not result.passed


def test_missing_sql_fails_rather_than_erroring(task):
    result = verify_sql(None, task.gold_query, task.database_path)
    assert result.outcome is VerificationOutcome.FAIL


# --------------------------------------------------------------------------
# Trajectory store
# --------------------------------------------------------------------------


def _episode_record(task_id: str, run_id: str = "r1") -> AgentEpisode:
    return AgentEpisode(
        episode_id=f"ep_{task_id}",
        run_id=run_id,
        task_id=task_id,
        dataset_version="v1",
        model_version="m1",
        prompt_version="p1",
        tool_schema_version="t1",
        status="completed",
        termination_reason=TerminationReason.SUCCESS,
    )


def test_store_resumes_from_persisted_episodes(tmp_path: Path):
    store = TrajectoryStore("run_a", tmp_path)
    store.record_episode(_episode_record("t1"))
    store.record_episode(_episode_record("t2"))

    assert TrajectoryStore("run_a", tmp_path).completed_task_ids() == {"t1", "t2"}


def test_store_reset_clears_records_so_reruns_do_not_double_count(tmp_path: Path):
    store = TrajectoryStore("run_b", tmp_path)
    store.record_episode(_episode_record("t1"))
    store.reset()
    store.record_episode(_episode_record("t1"))

    assert store.duplicate_task_ids() == {}
    assert len(list(store.iter_episodes())) == 1


def test_store_detects_duplicate_task_ids(tmp_path: Path):
    store = TrajectoryStore("run_c", tmp_path)
    store.record_episode(_episode_record("t1"))
    store.record_episode(_episode_record("t1"))
    assert store.duplicate_task_ids() == {"t1": 2}


def test_store_survives_a_truncated_final_line(tmp_path: Path):
    store = TrajectoryStore("run_d", tmp_path)
    store.record_episode(_episode_record("t1"))
    with store.episodes_path.open("a", encoding="utf-8") as handle:
        handle.write('{"task_id": "t2", "sta')

    # A crash mid-write costs one task, which is re-run, not the whole file.
    assert store.completed_task_ids() == {"t1"}


# --------------------------------------------------------------------------
# Cost accounting
# --------------------------------------------------------------------------


def test_cost_uses_cached_input_pricing_when_reported():
    full = estimate_cost("gpt-4o-mini", 1_000_000, 0, 0)
    cached = estimate_cost("gpt-4o-mini", 1_000_000, 0, 1_000_000)
    assert full == pytest.approx(0.15)
    assert cached == pytest.approx(0.075)


def test_unknown_model_costs_zero_rather_than_guessing():
    assert estimate_cost("some-unreleased-model", 1_000_000, 1_000_000) == 0.0


# --------------------------------------------------------------------------
# Agent loop and termination taxonomy
# --------------------------------------------------------------------------


def _run(agent: SpiderSQLAgent, task: SQLTask, tmp_path: Path) -> AgentEpisode:
    store = TrajectoryStore("agent_run", tmp_path / "runs")
    return agent.run_episode(
        task=task,
        run_id="agent_run",
        store=store,
        dataset_version="test:v1",
        workspace=str(tmp_path / "work"),
    )


def test_graph_compiles():
    assert build_graph() is not None


def test_successful_episode_records_a_full_trajectory(task, tmp_path: Path):
    client = MockOpenAIClient(answers={task.question: task.gold_query})
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    assert episode.termination_reason is TerminationReason.SUCCESS
    assert episode.final_sql == task.gold_query
    assert episode.verification_result["passed"] is True
    assert episode.model_steps == 4
    assert episode.schema_inspections == 2
    assert episode.sql_executions == 1
    assert episode.input_tokens > 0
    assert episode.estimated_cost > 0
    assert episode.trace_id


def test_wrong_answer_terminates_as_verification_failed(task, tmp_path: Path):
    client = MockOpenAIClient(answers={task.question: "SELECT count(*) FROM album WHERE id < 5"})
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    assert episode.termination_reason is TerminationReason.VERIFICATION_FAILED
    assert episode.verification_result["passed"] is False


def test_non_executing_answer_terminates_as_sql_error(task, tmp_path: Path):
    """SQL_ERROR and VERIFICATION_FAILED must not collapse into each other.

    "The query does not run" and "the query runs and returns the wrong rows" call
    for different fixes, so the taxonomy has to keep them apart.
    """
    client = MockOpenAIClient(answers={task.question: "SELECT nonexistent FROM artist"})
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    assert episode.termination_reason is TerminationReason.SQL_ERROR


def test_no_submission_terminates_as_no_final_sql(task, tmp_path: Path):
    client = MockOpenAIClient(answers={})
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    assert episode.termination_reason is TerminationReason.NO_FINAL_SQL
    assert episode.final_sql is None


def test_step_cap_terminates_as_max_steps(task, tmp_path: Path):
    # A client that only ever inspects the schema can never finish.
    client = MockOpenAIClient(script=[("inspect_schema", {})] * 50)
    agent = SpiderSQLAgent(client, AgentConfig(max_steps=3))
    episode = _run(agent, task, tmp_path)

    assert episode.termination_reason is TerminationReason.MAX_STEPS
    assert episode.model_steps == 3


def test_model_failure_is_reported_as_infrastructure_not_a_wrong_answer(task, tmp_path: Path):
    client = MockOpenAIClient(fail_after=0)
    agent = SpiderSQLAgent(client, AgentConfig(max_model_retries=1, retry_backoff_seconds=0))
    episode = _run(agent, task, tmp_path)

    assert episode.termination_reason is TerminationReason.MODEL_ERROR
    assert episode.verification_result is None


def test_malformed_tool_arguments_are_recoverable_not_infrastructure_failures(
    task, tmp_path: Path
):
    class BadArgsClient(MockOpenAIClient):
        def _default_script(self, turn, messages):
            if turn == 0:
                from backend.app.spider.mock_client import _Function, _ToolCall

                return [
                    _ToolCall(
                        id="call_bad",
                        function=_Function(name="inspect_schema", arguments="{not json"),
                    )
                ]
            return super()._default_script(turn, messages)

    client = BadArgsClient(answers={task.question: task.gold_query})
    episode = _run(SpiderSQLAgent(client), task, tmp_path)

    # The model's own mistake, so the episode continues rather than aborting.
    assert episode.termination_reason is not TerminationReason.TOOL_ERROR


def test_episode_database_is_removed_after_the_run(task, tmp_path: Path):
    client = MockOpenAIClient(answers={task.question: task.gold_query})
    _run(SpiderSQLAgent(client), task, tmp_path)

    workspace = tmp_path / "work"
    assert not list(workspace.glob("episode_*")) if workspace.exists() else True


def test_steps_and_payload_refs_are_consistent(task, tmp_path: Path):
    client = MockOpenAIClient(answers={task.question: task.gold_query})
    store = TrajectoryStore("ref_run", tmp_path / "runs")
    episode = SpiderSQLAgent(client).run_episode(
        task=task,
        run_id="ref_run",
        store=store,
        dataset_version="test:v1",
        workspace=str(tmp_path / "work"),
    )

    steps = list(store.iter_steps())
    assert len(steps) == episode.total_steps

    refs = {
        json.loads(line)["ref"]
        for line in store.payloads_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for step in steps:
        for key in ("model_input_ref", "model_output_ref", "tool_result_ref"):
            if step.get(key):
                assert step[key] in refs, f"dangling {key} on step {step['step_index']}"


# --------------------------------------------------------------------------
# Real Spider data
# --------------------------------------------------------------------------


def test_every_tool_step_emits_a_span(task, tmp_path: Path, monkeypatch):
    """Regression test for a measured trace gap.

    On run `spider_full__p0_v1`, 23 `inspect_schema` steps had no span (argument
    validation returned before the span opened) and all 986 `submit_answer` steps
    had none. The reconciliation check missed both because it only compared four
    hand-listed span types. Every tool step must produce exactly one span.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "backend.app.spider.agent.get_tracer", lambda: provider.get_tracer("test")
    )

    client = MockOpenAIClient(
        script=[
            ("inspect_schema", {}),
            ("inspect_schema", {"table": "artist"}),   # rejected arguments
            ("execute_sql", {"query": "SELECT 1"}),
            ("submit_answer", {"query": task.gold_query}),
        ]
    )
    store = TrajectoryStore("span_run", tmp_path / "runs")
    SpiderSQLAgent(client).run_episode(
        task=task,
        run_id="span_run",
        store=store,
        dataset_version="test:v1",
        workspace=str(tmp_path / "work"),
    )

    span_names = [span.name for span in exporter.get_finished_spans()]
    tool_steps = [s for s in store.iter_steps() if s["step_type"] == "tool"]

    for step in tool_steps:
        expected = f"tool.{step['tool_name']}"
        assert expected in span_names, f"no span for tool step {step['tool_name']}"

    counts = {name: span_names.count(name) for name in set(span_names)}
    assert counts.get("tool.inspect_schema") == 2, (
        "the rejected-argument call must still emit a span"
    )
    assert counts.get("tool.submit_answer") == 1
    assert counts.get("tool.execute_sql") == 1
    assert counts.get("sqlite.query") == 1
    # One span per tool step, no more and no less.
    tool_span_total = sum(
        count for name, count in counts.items()
        if name.startswith("tool.")
    )
    assert tool_span_total == len(tool_steps)


@requires_spider
def test_spider_dev_split_matches_its_gold_file():
    from backend.app.spider.loader import verify_split_integrity

    result = verify_split_integrity("dev")
    assert result["ok"], result["mismatches"][:5]
    assert result["tasks"] == 1034


@requires_spider
def test_exclusion_list_is_frozen_and_parseable():
    from backend.app.spider.adapter import build_task_set

    task_set = build_task_set("dev")
    assert len(task_set) + len(task_set.excluded) == 1034
    # dataset_version must change if the underlying data changes.
    assert task_set.dataset_version.startswith("spider-1.0:dev:")


# --------------------------------------------------------------------------
# Rate limiting as a first-class state
#
# Regression tests for a measured incident: the provider's daily request quota
# was exhausted, the SDK retried the 429s silently, and the result was 90
# MODEL_ERROR episodes out of 92 plus what looked like provider latency
# degradation. A quota refusal is not a model defect and must not be recorded
# as one.
# --------------------------------------------------------------------------


class _RateLimitError(Exception):
    """Shaped like the provider's error, without importing the SDK."""


def test_rate_limit_is_recognised_structurally():
    from backend.app.spider.agent import is_rate_limit_error

    assert is_rate_limit_error(_RateLimitError("Error code: 429 - rate limit reached"))
    assert is_rate_limit_error(RuntimeError("Error code: 429 - RPD exceeded"))
    assert not is_rate_limit_error(RuntimeError("connection reset by peer"))
    assert not is_rate_limit_error(None)


def test_rate_limit_terminates_as_rate_limited_not_model_error(task, tmp_path: Path):
    class RateLimitedClient(MockOpenAIClient):
        def _create(self, **kwargs):
            raise _RateLimitError("Error code: 429 - rate limit reached, RPD")

    agent = SpiderSQLAgent(
        RateLimitedClient(),
        AgentConfig(max_model_retries=3, retry_backoff_seconds=0),
    )
    episode = _run(agent, task, tmp_path)

    assert episode.termination_reason is TerminationReason.RATE_LIMITED
    assert episode.termination_reason is not TerminationReason.MODEL_ERROR
    assert "429" in (episode.error or "")


def test_rate_limits_are_not_retried(task, tmp_path: Path):
    """Retrying into an exhausted quota burns wall time and hides the cause."""

    class CountingClient(MockOpenAIClient):
        calls = 0

        def _create(self, **kwargs):
            type(self).calls += 1
            raise _RateLimitError("Error code: 429 - rate limit reached")

    CountingClient.calls = 0
    agent = SpiderSQLAgent(
        CountingClient(),
        AgentConfig(max_model_retries=3, retry_backoff_seconds=0),
    )
    _run(agent, task, tmp_path)

    assert CountingClient.calls == 1, "a 429 must not be retried in benchmark mode"


def test_transient_errors_are_still_retried(task, tmp_path: Path):
    class FlakyClient(MockOpenAIClient):
        calls = 0

        def _create(self, **kwargs):
            type(self).calls += 1
            raise RuntimeError("connection reset by peer")

    FlakyClient.calls = 0
    agent = SpiderSQLAgent(
        FlakyClient(),
        AgentConfig(max_model_retries=3, retry_backoff_seconds=0),
    )
    episode = _run(agent, task, tmp_path)

    assert FlakyClient.calls == 3, "transient failures must still be retried"
    assert episode.termination_reason is TerminationReason.MODEL_ERROR


def test_rate_limit_is_a_halting_termination():
    from backend.app.spider.trajectory import (
        HALTING_TERMINATIONS,
        INFRASTRUCTURE_TERMINATIONS,
    )

    assert TerminationReason.RATE_LIMITED in HALTING_TERMINATIONS
    assert TerminationReason.RATE_LIMITED in INFRASTRUCTURE_TERMINATIONS
    # A quota refusal says nothing about the agent, so it must never be mistaken
    # for a wrong answer.
    assert TerminationReason.VERIFICATION_FAILED not in HALTING_TERMINATIONS


def test_retry_wait_is_excluded_from_api_latency(task, tmp_path: Path):
    """Latency metrics must measure the provider, not our own backoff."""

    class SlowThenOkClient(MockOpenAIClient):
        attempts = 0

        def _create(self, **kwargs):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise RuntimeError("connection reset by peer")
            return super()._create(**kwargs)

    SlowThenOkClient.attempts = 0
    agent = SpiderSQLAgent(
        SlowThenOkClient(answers={task.question: task.gold_query}),
        AgentConfig(max_model_retries=3, retry_backoff_seconds=0.25),
    )
    store = TrajectoryStore("latency_run", tmp_path / "runs")
    agent.run_episode(
        task=task,
        run_id="latency_run",
        store=store,
        dataset_version="test:v1",
        workspace=str(tmp_path / "work"),
    )

    first = [s for s in store.iter_steps() if s["step_type"] == "model"][0]
    assert first["retry_wait_ms"] >= 200, "backoff should be recorded"
    assert first["api_latency_ms"] < first["latency_ms"], (
        "api_latency_ms must exclude the backoff that latency_ms includes"
    )
