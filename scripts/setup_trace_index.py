"""Create the Elasticsearch data stream the OpenTelemetry Collector writes into.

The collector's Elasticsearch exporter sends bulk `create` actions, which only
work against a data stream. Without one it fails every span with a 404 -
first `index_not_found_exception`, then `resource_not_found_exception` if a plain
index is created by hand. Neither error surfaces in the application; spans simply
never appear, and a trace count reads 0 as though nothing was ever instrumented.

This script is idempotent, so it is safe to run before every collector start.

Usage:
    python scripts/setup_trace_index.py
    python scripts/setup_trace_index.py --elasticsearch-url http://127.0.0.1:9200
"""

from __future__ import annotations

import argparse
import os
import sys

import requests

DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"
DEFAULT_TRACE_INDEX = "otel-traces"
TEMPLATE_NAME = "otel-traces-template"


def ensure_template(base_url: str, trace_index: str) -> None:
    body = {
        "index_patterns": [f"{trace_index}*"],
        "data_stream": {},
        "priority": 500,
        "template": {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"dynamic": True},
        },
    }
    response = requests.put(
        f"{base_url}/_index_template/{TEMPLATE_NAME}", json=body, timeout=10
    )
    response.raise_for_status()
    print(f"index template {TEMPLATE_NAME}: ok")


def ensure_data_stream(base_url: str, trace_index: str) -> None:
    existing = requests.get(f"{base_url}/_data_stream/{trace_index}", timeout=10)
    if existing.status_code == 200:
        print(f"data stream {trace_index}: already exists")
        return

    # A plain index of the same name blocks data stream creation; remove it. It
    # can only have come from a failed manual attempt, and it holds no spans
    # because the collector could never write to it.
    plain = requests.head(f"{base_url}/{trace_index}", timeout=10)
    if plain.status_code == 200:
        requests.delete(f"{base_url}/{trace_index}", timeout=10)
        print(f"removed plain index {trace_index} so a data stream can take its place")

    response = requests.put(f"{base_url}/_data_stream/{trace_index}", timeout=10)
    response.raise_for_status()
    print(f"data stream {trace_index}: created")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--elasticsearch-url",
        default=os.getenv("ELASTICSEARCH_URL", DEFAULT_ELASTICSEARCH_URL),
    )
    parser.add_argument("--index", default=DEFAULT_TRACE_INDEX)
    args = parser.parse_args()

    base_url = args.elasticsearch_url.rstrip("/")
    try:
        ensure_template(base_url, args.index)
        ensure_data_stream(base_url, args.index)
    except requests.RequestException as error:
        print(
            "Could not reach Elasticsearch. Is it running? "
            "docker compose up -d elasticsearch",
            file=sys.stderr,
        )
        print(error, file=sys.stderr)
        return 1

    print("\nSpans exported through the collector will now be indexed.")
    print("Verify with: python scripts/count_trace_documents.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
