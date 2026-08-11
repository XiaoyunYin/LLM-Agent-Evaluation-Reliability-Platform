import os

import requests

DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"


def main() -> None:
    elasticsearch_url = os.getenv(
        "ELASTICSEARCH_URL",
        DEFAULT_ELASTICSEARCH_URL,
    )

    response = requests.get(elasticsearch_url, timeout=5)
    response.raise_for_status()

    print("Elasticsearch connection OK")


if __name__ == "__main__":
    main()