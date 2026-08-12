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
    # Assert the provenance invariant rather than a particular run state. Which
    # metrics are measured depends on which benchmarks have been run, so pinning
    # a status here makes the test fail the moment a benchmark succeeds, which is
    # the opposite of what it should be guarding.
    for metric in metrics.values():
        if metric["status"] == "measured":
            assert metric["value"] is not None, metric["key"]
            assert metric["source"], metric["key"]
        elif metric["status"] == "not_measured":
            assert metric["value"] is None, metric["key"]

    # Agreement was non_final while only a mock rehearsal report existed. Once a real
    # dual-judge slice is measured it must read as measured -- pinning "non_final"
    # here would keep asserting that the dashboard shows a mock number.
    agreement = metrics["judge_agreement_percentage"]
    assert agreement["status"] in {"measured", "non_final", "not_measured"}
    if agreement["status"] == "measured":
        assert agreement["value"] is not None
        assert agreement["source"]
    elif agreement["status"] == "non_final":
        assert "Mock rehearsal" in agreement["note"]


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
