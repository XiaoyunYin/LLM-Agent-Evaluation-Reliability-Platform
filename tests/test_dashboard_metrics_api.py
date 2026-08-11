from fastapi.testclient import TestClient

from backend.main import app


def test_metrics_summary_exposes_required_dashboard_keys():
    client = TestClient(app)

    response = client.get("/metrics-summary")

    assert response.status_code == 200
    body = response.json()
    metrics = {metric["key"]: metric for metric in body["metrics"]}

    assert set(metrics) == {
        "recall_at_10",
        "ndcg_at_10",
        "judge_agreement_percentage",
        "disagreement_percentage",
        "judged_answer_count",
        "eval_run_count",
        "trace_count",
    }
    assert metrics["recall_at_10"]["status"] == "not_measured"
    assert metrics["trace_count"]["status"] == "not_measured"
    assert metrics["judge_agreement_percentage"]["status"] == "non_final"
    assert "Mock rehearsal" in metrics["judge_agreement_percentage"]["note"]


def test_review_cases_include_saved_manual_review_queue_artifacts():
    client = TestClient(app)

    response = client.get("/review-cases")

    assert response.status_code == 200
    cases = response.json()
    ids = {case["case_id"] for case in cases}

    assert "review_case_001" not in ids
    assert "RH-001" in ids
    assert all("id" in case for case in cases)
    assert all("disagreement_reason" in case for case in cases)
