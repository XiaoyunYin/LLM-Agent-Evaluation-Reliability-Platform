import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever


def main() -> None:
    retriever = ElasticsearchBm25Retriever()
    candidates = retriever.retrieve_candidates("administrator owner access workspace")
    results = retriever.retrieve("administrator owner access workspace")

    print(f"Retrieved candidates: {len(candidates)}")
    print(f"Retrieved metric results: {len(results)}")
    # results = retriever.retrieve("administrator owner access workspace")

    # print(f"Retrieved results: {len(results)}")

    # for result in results[:3]:
    #     print(result.chunk_id)
    #     print(f"score: {result.score:.4f}")
    #     print(result.text[:120].replace("\n", " "))
    #     print()


if __name__ == "__main__":
    main()