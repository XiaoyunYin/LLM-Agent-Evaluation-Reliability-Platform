from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, JudgeType
from backend.app.rule_based_judge import judge_candidate_answer


def make_case(expected_answer: str = "210") -> EvalCase:
    return EvalCase(
        id="case_001",
        question="What is the answer?",
        expected_answer=expected_answer,
        task_type=TaskType.DIRECT_QA,
    )


def make_candidate(generated_answer: str) -> CandidateAnswer:
    return CandidateAnswer(
        run_id="run_001",
        case_id="case_001",
        generated_answer=generated_answer,
    )


def test_rule_based_judge_passes_exact_match():
    score = judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate("210"),
    )

    assert score.run_id == "run_001"
    assert score.case_id == "case_001"
    assert score.judge_name == "rule-based-v0"
    assert score.judge_type == JudgeType.RULE_BASED
    assert score.correctness == 1.0
    assert score.passed is True


def test_rule_based_judge_passes_when_expected_answer_is_contained():
    score = judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate("The answer is 210."),
    )

    assert score.correctness == 0.8
    assert score.passed is True
    assert "contains" in score.explanation


def test_rule_based_judge_fails_wrong_answer():
    score = judge_candidate_answer(
        case=make_case(),
        candidate=make_candidate("The answer is 180."),
    )

    assert score.correctness == 0.0
    assert score.passed is False
    assert "does not match" in score.explanation