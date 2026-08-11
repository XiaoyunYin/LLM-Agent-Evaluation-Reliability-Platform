from scripts.benchmark_hybrid_retrieval import relevant_chunks_by_id


def test_relevant_chunks_by_id_maps_chunk_ids_to_relevance_grades():
    row = {
        "relevant_chunks": [
            {"chunk_id": "chunk_a", "relevance": 2},
            {"chunk_id": "chunk_b", "relevance": 1},
        ]
    }

    result = relevant_chunks_by_id(row)

    assert result == {
        "chunk_a": 2,
        "chunk_b": 1,
    }