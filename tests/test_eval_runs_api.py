from fastapi.testclient import TestClient

from backend.main import app


def test_eval_run_list_exposes_dashboard_columns():
    client = TestClient(app)

    response = client.get("/eval-runs")

    assert response.status_code == 200
    runs = response.json()

    assert len(runs) >= 1
    run = runs[0]
    assert "run_id" in run
    assert "dataset_version" in run
    assert "provider_name" in run
    assert "score" in run
    assert "latency_ms" in run
    assert "created_at" in run
    assert "status" in run
    assert run["score"] is None
    assert run["latency_ms"] is None
