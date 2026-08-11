from backend.app.agentic_judge import (
    grade_final_answer,
    grade_tool_arguments,
    grade_tool_choice,
    judge_agentic_tool_call,
)
from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer


def test_grade_tool_choice_passes_when_tool_name_matches():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="126",
        tool_call={
            "name": "calculator",
            "arguments": {"expression": "18 * 7"},
        },
    )

    score, explanation = grade_tool_choice(case, candidate)

    assert score == 1.0
    assert "expected tool" in explanation


def test_grade_tool_choice_fails_when_candidate_makes_no_tool_call():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="126",
        tool_call=None,
    )

    score, explanation = grade_tool_choice(case, candidate)

    assert score == 0.0
    assert "did not make a tool call" in explanation


def test_grade_tool_choice_fails_when_tool_name_does_not_match():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="126",
        tool_call={
            "name": "mock_search",
            "arguments": {"query": "18 * 7"},
        },
    )

    score, explanation = grade_tool_choice(case, candidate)

    assert score == 0.0
    assert "Expected tool 'calculator'" in explanation

def test_grade_tool_arguments_passes_when_arguments_match():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="126",
        tool_call={
            "name": "calculator",
            "arguments": {"expression": "18 * 7"},
        },
    )

    score, explanation = grade_tool_arguments(case, candidate)

    assert score == 1.0
    assert "expected tool arguments" in explanation

def test_tool_choice_can_pass_while_tool_arguments_fail():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="25",
        tool_call={
            "name": "calculator",
            "arguments": {"expression": "18 + 7"},
        },
    )

    choice_score, _ = grade_tool_choice(case, candidate)
    argument_score, argument_explanation = grade_tool_arguments(case, candidate)

    assert choice_score == 1.0
    assert argument_score == 0.0
    assert "Expected arguments" in argument_explanation

def test_grade_final_answer_reuses_rule_based_answer_judge():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="The answer is 126.",
        tool_call={
            "name": "calculator",
            "arguments": {"expression": "18 * 7"},
        },
    )

    score, explanation = grade_final_answer(case, candidate)

    assert score == 0.8
    assert "contains" in explanation


def test_judge_agentic_tool_call_returns_all_scores():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="126",
        tool_call={
            "name": "calculator",
            "arguments": {"expression": "18 * 7"},
        },
    )

    result = judge_agentic_tool_call(case, candidate)

    assert result["run_id"] == "run_001"
    assert result["case_id"] == "AT-001"
    assert result["tool_choice_score"] == 1.0
    assert result["tool_arguments_score"] == 1.0
    assert result["final_answer_score"] == 1.0
    assert result["passed"] is True

def test_judge_agentic_tool_call_reports_independent_failures():
    case = EvalCase(
        id="AT-001",
        question="Use a calculator to multiply 18 by 7.",
        expected_answer="126",
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "expected_tool_call": {
                "name": "calculator",
                "arguments": {"expression": "18 * 7"},
            }
        },
    )
    candidate = CandidateAnswer(
        run_id="run_001",
        case_id="AT-001",
        generated_answer="25",
        tool_call={
            "name": "mock_search",
            "arguments": {"query": "18 + 7"},
        },
    )

    result = judge_agentic_tool_call(case, candidate)

    assert result["tool_choice_score"] == 0.0
    assert result["tool_arguments_score"] == 0.0
    assert result["final_answer_score"] == 0.0
    assert result["passed"] is False
    assert "tool_choice" in result["explanations"]
    assert "tool_arguments" in result["explanations"]
    assert "final_answer" in result["explanations"]