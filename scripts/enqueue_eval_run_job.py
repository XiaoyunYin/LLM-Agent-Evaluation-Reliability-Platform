import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.queue_jobs import EvalRunJobPayload


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
QUEUE_NAME = "eval_run_jobs"


def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"queued_eval_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dataset-version", default="golden_rag_v0.1")
    parser.add_argument("--provider", default="mock")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    client = redis.Redis.from_url(redis_url, decode_responses=True)

    run_id = args.run_id or create_run_id()

    payload = EvalRunJobPayload(
        run_id=run_id,
        dataset_version=args.dataset_version,
        provider_name=args.provider,
    )
    job_json = payload.model_dump_json()

    client.rpush(QUEUE_NAME, job_json)

    print(f"enqueued run_id={payload.run_id}")
    print(f"queue={QUEUE_NAME}")
    print(f"provider={payload.provider_name}")
    print(f"dataset_version={payload.dataset_version}")


if __name__ == "__main__":
    main()