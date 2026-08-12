import argparse
import json
import os
from datetime import datetime, timezone
import sys
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))


DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"
DEFAULT_TRACE_INDEX = "otel-traces"


def build_unique_trace_count_query(trace_id_field: str = "trace_id") -> dict:
    return {
        "size": 0,
        "query": {
            "exists": {
                "field": trace_id_field,
            }
        },
        "aggs": {
            "unique_trace_count": {
                "cardinality": {
                    "field": trace_id_field,
                }
            }
        },
    }


def count_trace_documents(
    elasticsearch_url: str,
    trace_index: str = DEFAULT_TRACE_INDEX,
    trace_id_field: str = "trace_id",
) -> dict:
    base_url = elasticsearch_url.rstrip("/")
    count_response = requests.get(
        f"{base_url}/{trace_index}/_count",
        timeout=10,
    )
    count_response.raise_for_status()

    # Dynamic mapping stores trace_id as text, which cannot be aggregated. The
    # aggregatable form is the .keyword subfield, so try that first and fall back
    # to the bare field for indices with an explicit keyword mapping.
    search_response = requests.post(
        f"{base_url}/{trace_index}/_search",
        json=build_unique_trace_count_query(
            trace_id_field=f"{trace_id_field}.keyword"
        ),
        timeout=10,
    )
    if search_response.status_code == 400:
        search_response = requests.post(
            f"{base_url}/{trace_index}/_search",
            json=build_unique_trace_count_query(trace_id_field=trace_id_field),
            timeout=10,
        )
    search_response.raise_for_status()

    count_body = count_response.json()
    search_body = search_response.json()

    return {
        "trace_index": trace_index,
        "span_document_count": count_body["count"],
        "unique_trace_count": search_body["aggregations"]["unique_trace_count"][
            "value"
        ],
        "trace_id_field": trace_id_field,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--elasticsearch-url",
        default=os.getenv("ELASTICSEARCH_URL", DEFAULT_ELASTICSEARCH_URL),
    )
    parser.add_argument("--index", default=DEFAULT_TRACE_INDEX)
    parser.add_argument("--trace-id-field", default="trace_id")
    parser.add_argument(
        "--save",
        type=Path,
        default=Path("runs/trace_counts/trace_count.json"),
        help="Persist the count so the dashboard can read a measured value "
             "instead of reporting not_measured while Elasticsearch is offline.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        counts = count_trace_documents(
            elasticsearch_url=args.elasticsearch_url,
            trace_index=args.index,
            trace_id_field=args.trace_id_field,
        )
    except requests.RequestException as error:
        print(
            "Could not query trace documents. "
            "Is Elasticsearch running and reachable?",
            file=sys.stderr,
        )
        print(error, file=sys.stderr)
        raise SystemExit(1) from error

    print(f"trace_index={counts['trace_index']}")
    print(f"span_document_count={counts['span_document_count']}")
    print(f"unique_trace_count={counts['unique_trace_count']}")
    print(f"trace_id_field={counts['trace_id_field']}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(counts)
        payload["measured_at"] = datetime.now(timezone.utc).isoformat()
        payload["exact_command"] = "python scripts/count_trace_documents.py"
        args.save.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"saved_artifact={args.save}")


if __name__ == "__main__":
    main()
