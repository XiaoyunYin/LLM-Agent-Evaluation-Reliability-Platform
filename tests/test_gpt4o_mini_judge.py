import pytest


from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, RunStatus
from backend.app.gpt4o_mini_judge import (
    JudgeOutputParseError,
    parse_judge_output,
    GPT4oMiniJudge,
)


def test_parse_judge_output_accepts_valid_json():
    output = parse_judge_output(
        """
        {
          "correctness": 1.0,
          "faithfulness": 0.8,
          "citation_quality": 0.5,
          "passed": true,
          "explanation": "Answer is correct and mostly supported."
        }
        """
    )

    assert output.correctness == 1.0
    assert output.faithfulness == 0.8
    assert output.citation_quality == 0.5
    assert output.passed is True


def test_parse_judge_output_rejects_non_json():
    with pytest.raises(JudgeOutputParseError):
        parse_judge_output("The answer looks good.")


def test_parse_judge_output_rejects_out_of_range_score():
    with pytest.raises(JudgeOutputParseError):
        parse_judge_output(
            """
            {
              "correctness": 1.2,
              "faithfulness": 1.0,
              "citation_quality": 1.0,
              "passed": true,
              "explanation": "Score is out of range."
            }
            """
        )

class FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponsesClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.call_count = 0

    def create(self, **kwargs):
        output = self.outputs[self.call_count]
        self.call_count += 1
        return FakeResponse(output)


class FakeOpenAIClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = FakeResponsesClient(outputs)


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
    )


def valid_judge_json() -> str:
    return """
    {
      "correctness": 1.0,
      "faithfulness": 1.0,
      "citation_quality": 0.0,
      "passed": true,
      "explanation": "The answer matches the expected answer."
    }
    """


def test_gpt4o_mini_judge_returns_score_from_valid_json():
    fake_client = FakeOpenAIClient(outputs=[valid_judge_json()])
    judge = GPT4oMiniJudge(client=fake_client)

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.run_id == "run_001"
    assert score.case_id == "MA-001"
    assert score.correctness == 1.0
    assert score.faithfulness == 1.0
    assert score.citation_quality == 0.0
    assert score.passed is True
    assert score.status == RunStatus.COMPLETED
    assert fake_client.responses.call_count == 1


def test_gpt4o_mini_judge_retries_once_after_malformed_json():
    fake_client = FakeOpenAIClient(
        outputs=[
            "This answer is correct.",
            valid_judge_json(),
        ]
    )
    judge = GPT4oMiniJudge(client=fake_client)

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.passed is True
    assert score.status == RunStatus.COMPLETED
    assert fake_client.responses.call_count == 2


def test_gpt4o_mini_judge_returns_failed_score_after_repeated_malformed_json():
    fake_client = FakeOpenAIClient(
        outputs=[
            "This answer is correct.",
            "Still not JSON.",
        ]
    )
    judge = GPT4oMiniJudge(client=fake_client)

    score = judge.judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate(),
    )

    assert score.correctness == 0.0
    assert score.faithfulness == 0.0
    assert score.citation_quality == 0.0
    assert score.passed is False
    assert score.status == RunStatus.FAILED
    assert "failed to return valid JSON" in score.explanation
    assert fake_client.responses.call_count == 2