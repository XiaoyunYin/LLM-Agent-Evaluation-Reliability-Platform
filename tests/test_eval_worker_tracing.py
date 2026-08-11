from backend.app.eval_run import EvalRun
from backend.app.queue_jobs import build_run_key, save_eval_run
from backend.app.tracing import (
    SERVICE_LAYER_GATEWAY,
    SERVICE_LAYER_JUDGE,
    SERVICE_LAYER_PROVIDER,
    SERVICE_LAYER_RETRIEVAL,
    SERVICE_LAYER_STORAGE,
    SERVICE_LAYER_TOOL,
    format_trace_id,
)
import scripts.run_eval_worker as eval_worker
from scripts.run_eval_worker import handle_eval_run_job
from backend.app.queue_jobs import EvalRunJobPayload


class FakeRedis:
    def __init__(self):
        self.hashes = {}

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.hashes.get(key, {})


class FakeSpan:
    def __init__(self, name: str):
        self.name = name
        self.attributes = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, error):
        self.attributes["exception.type"] = type(error).__name__


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name: str):
        span = FakeSpan(name)
        self.spans.append(span)
        return span


def test_format_trace_id_uses_32_character_hex_string():
    assert format_trace_id(1) == "00000000000000000000000000000001"


def test_eval_worker_stores_trace_id_on_run_and_result():
    client = FakeRedis()
    run = EvalRun(
        run_id="run_trace_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )
    save_eval_run(client, run)
    payload = EvalRunJobPayload(
        run_id="run_trace_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )

    handle_eval_run_job(payload, client)

    stored_run = client.hgetall(build_run_key("run_trace_001"))
    result = client.hgetall("eval_run_result:run_trace_001")

    assert stored_run["status"] == "completed"
    assert len(stored_run["trace_id"]) == 32
    assert int(stored_run["trace_id"], 16) > 0
    assert result["run_id"] == "run_trace_001"
    assert result["trace_id"] == stored_run["trace_id"]


def test_eval_worker_emits_spans_for_all_six_service_layers(monkeypatch):
    fake_tracer = FakeTracer()
    monkeypatch.setattr(eval_worker, "get_tracer", lambda: fake_tracer)
    monkeypatch.setattr(
        eval_worker,
        "current_trace_id",
        lambda: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    client = FakeRedis()
    run = EvalRun(
        run_id="run_layers_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )
    save_eval_run(client, run)
    payload = EvalRunJobPayload(
        run_id="run_layers_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )

    handle_eval_run_job(payload, client)

    layers = {
        span.attributes.get("service.layer")
        for span in fake_tracer.spans
        if "service.layer" in span.attributes
    }
    span_names = {span.name for span in fake_tracer.spans}

    assert {
        SERVICE_LAYER_GATEWAY,
        SERVICE_LAYER_RETRIEVAL,
        SERVICE_LAYER_PROVIDER,
        SERVICE_LAYER_JUDGE,
        SERVICE_LAYER_TOOL,
        SERVICE_LAYER_STORAGE,
    }.issubset(layers)
    assert "gateway.accept_eval_run_job" in span_names
    assert "retrieval.fetch_context" in span_names
    assert "provider.generate_candidate_answer" in span_names
    assert "judge.score_candidate_answer" in span_names
    assert "tool.execute_agent_tool" in span_names
    assert "eval_runner.store_eval_run_result" in span_names

    for span in fake_tracer.spans:
        if "service.layer" in span.attributes:
            assert span.attributes["eval.run_id"] == "run_layers_001"

    stored_run = client.hgetall(build_run_key("run_layers_001"))
    result = client.hgetall("eval_run_result:run_layers_001")

    assert stored_run["trace_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert result["trace_id"] == stored_run["trace_id"]
