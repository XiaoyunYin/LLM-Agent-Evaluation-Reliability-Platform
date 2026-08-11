import os

import redis


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


def main() -> None:
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)

    client = redis.Redis.from_url(redis_url, socket_connect_timeout=5)
    if client.ping():
        print("Redis connection OK")


if __name__ == "__main__":
    main()