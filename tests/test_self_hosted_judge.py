import requests
from fastapi.testclient import TestClient

from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, JudgeType, RunStatus
from backend.app.mock_self_hosted_judge_server import create_mock_self_hosted_judge_app
from backend.app.self_hosted_judge import (
    SelfHostedJudge,
    SelfHostedJudgeConfig,
)


class FakeHTTPResponse:
    def __init__(self, status_code: int, data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self) -> dict:
        if self._data is None:
            raise ValueError("No JSON")
        return self._data


class FakeSession:
    def __init__(self, responses: list[FakeHTTPResponse | Exception]) -> None:
        self.responses = responses
        self.call_count = 0
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        response = self.responses[self.call_count]
        self.call_count += 1

        if isinstance(response, Exception):
            raise response

        return response


def make_case() -> EvalCase:
    return EvalCase(
        id="MA-001",
        question="What is 2 + 2?",
        expected_answer="4",
        task_type=TaskType.DIRECT_QA,
    )


def make_candidate() -> CandidateAnswer:
    return CandidateAnswer(
        run_id="run_001",
        case_id="MA-001",
        generated_answer="4",
        trace_id="trace_001",
    )


def make_config(**overrides) -> SelfHostedJudgeConfig:
    values = {
        "endpoint_url": "http://mock-judge/v1/chat/completions",
        "model_name": "mock-mistral-7b",
        "timeout_seconds": 1.0,
        "max_retries": 0,
        "retry_backoff_seconds": 0.0,
    }
    values.update(overrides)
    return SelfHostedJudgeConfig(**values)


def test_mock_self_hosted_judge_endpoint_returns_openai_compatible_json():
    client = TestClient(create_mock_self_hosted_judge_app())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-mistral-7b",
            "messages": [
                {
                    "role": "user",
                    "content": "Expected answer:\n4\n\nCandidate answer:\n4",
                }
            ],
            "temperature": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    content = body["choices"][0]["message"]["content"]

    assert body["model"] == "mock-mistral-7b"
    assert '"correctness": 1.0' in content
    assert '"passed": true' in content


def test_self_hosted_judge_returns_score_from_mock_endpoint_shape():
    mock_server_client = TestClient(create_mock_self_hosted_judge_app())
    mock_response = mock_server_client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-mistral-7b",
            "messages": [
                {
                    "role": "user",
                    "content": "Expected answer:\n4\n\nCandidate answer:\n4",
                }
            ],
            "temperature": 0,
        },
    )
    fake_session = FakeSession(
        responses=[FakeHTTPResponse(status_code=200, data=mock_response.json())]
    )
    judge = SelfHostedJudge(
        config=make_config(),
        session=fake_session,
    )

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.run_id == "run_001"
    assert score.case_id == "MA-001"
    assert score.judge_name == "self-hosted-7b-bulk-v0"
    assert score.judge_type == JudgeType.SELF_HOSTED_7B
    assert score.correctness == 1.0
    assert score.faithfulness == 1.0
    assert score.citation_quality == 0.0
    assert score.passed is True
    assert score.trace_id == "trace_001"
    assert score.status == RunStatus.COMPLETED


def test_self_hosted_judge_retries_retryable_http_error():
    success_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"correctness": 1.0, "faithfulness": 1.0, '
                        '"citation_quality": 0.0, "passed": true, '
                        '"explanation": "Recovered after retry."}'
                    )
                }
            }
        ]
    }
    fake_session = FakeSession(
        responses=[
            FakeHTTPResponse(status_code=503, text="loading"),
            FakeHTTPResponse(status_code=200, data=success_response),
        ]
    )
    judge = SelfHostedJudge(
        config=make_config(max_retries=1),
        session=fake_session,
        sleep=lambda seconds: None,
    )

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.status == RunStatus.COMPLETED
    assert score.passed is True
    assert fake_session.call_count == 2


def test_self_hosted_judge_returns_failed_score_after_timeout():
    fake_session = FakeSession(
        responses=[requests.Timeout("simulated timeout")]
    )
    judge = SelfHostedJudge(
        config=make_config(timeout_seconds=0.01),
        session=fake_session,
        sleep=lambda seconds: None,
    )

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.correctness == 0.0
    assert score.faithfulness == 0.0
    assert score.citation_quality == 0.0
    assert score.passed is False
    assert score.status == RunStatus.FAILED
    assert "timed out" in score.explanation


def test_self_hosted_judge_returns_failed_score_after_malformed_judge_json():
    bad_response = {
        "choices": [
            {
                "message": {
                    "content": "This response is not JSON."
                }
            }
        ]
    }
    fake_session = FakeSession(
        responses=[
            FakeHTTPResponse(status_code=200, data=bad_response),
            FakeHTTPResponse(status_code=200, data=bad_response),
        ]
    )
    judge = SelfHostedJudge(
        config=make_config(),
        max_parse_attempts=2,
        session=fake_session,
    )

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.status == RunStatus.FAILED
    assert score.passed is False
    assert "failed to return valid JSON" in score.explanation
    assert fake_session.call_count == 2
