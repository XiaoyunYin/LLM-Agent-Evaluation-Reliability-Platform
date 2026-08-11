from pathlib import Path

from scripts.count_trace_documents import (
    build_unique_trace_count_query,
    count_trace_documents,
)


class FakeResponse:
    def __init__(self, body: dict, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


class FakeRequests:
    def __init__(self) -> None:
        self.get_calls = []
        self.post_calls = []

    def get(self, url: str, timeout: int):
        self.get_calls.append({"url": url, "timeout": timeout})
        return FakeResponse({"count": 12})

    def post(self, url: str, json: dict, timeout: int):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "aggregations": {
                    "unique_trace_count": {
                        "value": 3,
                    }
                }
            }
        )


def test_build_unique_trace_count_query_counts_distinct_trace_ids():
    query = build_unique_trace_count_query()

    assert query["size"] == 0
    assert query["query"]["exists"]["field"] == "trace_id"
    assert (
        query["aggs"]["unique_trace_count"]["cardinality"]["field"]
        == "trace_id"
    )


def test_count_trace_documents_reports_span_docs_and_unique_traces(monkeypatch):
    fake_requests = FakeRequests()
    monkeypatch.setattr("scripts.count_trace_documents.requests", fake_requests)

    counts = count_trace_documents(
        elasticsearch_url="http://elasticsearch.test:9200/",
        trace_index="otel-traces",
    )

    assert counts["trace_index"] == "otel-traces"
    assert counts["span_document_count"] == 12
    assert counts["unique_trace_count"] == 3
    assert fake_requests.get_calls[0]["url"] == (
        "http://elasticsearch.test:9200/otel-traces/_count"
    )
    assert fake_requests.post_calls[0]["url"] == (
        "http://elasticsearch.test:9200/otel-traces/_search"
    )


def test_collector_config_exports_traces_to_elasticsearch_index():
    config_text = Path("infra/otel-collector-config.yml").read_text(
        encoding="utf-8"
    )

    assert "otlp:" in config_text
    assert "elasticsearch:" in config_text
    assert "traces_index: otel-traces" in config_text
    assert "receivers:" in config_text
    assert "exporters:" in config_text


def test_docker_compose_includes_otel_collector_service_and_backend_endpoint():
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "otel-collector:" in compose_text
    assert "otel/opentelemetry-collector-contrib" in compose_text
    assert "4317:4317" in compose_text
    assert "OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317" in compose_text


class KeywordRejectingRequests(FakeRequests):
    """Elasticsearch rejects a cardinality aggregation on a text field with 400.

    Dynamic mapping stores trace_id as text, so the count script tries
    trace_id.keyword first and falls back to the bare field.
    """

    def post(self, url: str, json: dict, timeout: int):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        field = json["aggs"]["unique_trace_count"]["cardinality"]["field"]
        if field.endswith(".keyword"):
            return FakeResponse({"error": "illegal_argument_exception"}, status_code=400)
        return FakeResponse(
            {"aggregations": {"unique_trace_count": {"value": 7}}}
        )


def test_count_trace_documents_falls_back_when_keyword_subfield_is_absent(monkeypatch):
    fake_requests = KeywordRejectingRequests()
    monkeypatch.setattr("scripts.count_trace_documents.requests", fake_requests)

    counts = count_trace_documents(
        elasticsearch_url="http://elasticsearch.test:9200",
        trace_index="otel-traces",
    )

    assert counts["unique_trace_count"] == 7
    tried = [
        call["json"]["aggs"]["unique_trace_count"]["cardinality"]["field"]
        for call in fake_requests.post_calls
    ]
    assert tried == ["trace_id.keyword", "trace_id"]
