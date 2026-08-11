from typing import Any
import os

import requests
from pydantic import BaseModel, Field


BM25_CANDIDATE_DEPTH = 50
BM25_METRIC_DEPTH = 10
DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"
DEFAULT_INDEX_NAME = "llm_eval_chunks"

class Bm25RetrievalResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)

class ElasticsearchBm25Retriever:
    def __init__(
        self,
        elasticsearch_url: str | None = None,
        index_name: str | None = None,
        candidate_depth: int = BM25_CANDIDATE_DEPTH,
        metric_depth: int = BM25_METRIC_DEPTH,
    ) -> None:
        self.elasticsearch_url = elasticsearch_url or os.getenv(
            "ELASTICSEARCH_URL",
            DEFAULT_ELASTICSEARCH_URL,
        )
        self.index_name = index_name or os.getenv(
            "ELASTICSEARCH_INDEX",
            DEFAULT_INDEX_NAME,
        )
        self.candidate_depth = candidate_depth
        self.metric_depth = metric_depth

    def retrieve_candidates(self, query: str) -> list[Bm25RetrievalResult]:
        response = requests.get(
            f"{self.elasticsearch_url}/{self.index_name}/_search",
            json={
                "size": self.candidate_depth,
                "query": {
                    "match": {
                        "text": query,
                    }
                },
            },
            timeout=10,
        )
        response.raise_for_status()

        hits = response.json()["hits"]["hits"]

        return [
            Bm25RetrievalResult(
                chunk_id=hit["_source"]["chunk_id"],
                text=hit["_source"]["text"],
                score=float(hit["_score"]),
                metadata=hit["_source"].get("metadata", {}),
            )
            for hit in hits
        ]

    def retrieve(self, query: str) -> list[Bm25RetrievalResult]:
        candidates = self.retrieve_candidates(query)

        return candidates[: self.metric_depth]