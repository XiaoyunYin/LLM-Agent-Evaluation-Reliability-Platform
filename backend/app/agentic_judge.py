from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer
from backend.app.rule_based_judge import judge_candidate_answer


def grade_tool_choice(case: EvalCase, candidate: CandidateAnswer) -> tuple[float, str]:
    expected_tool_call = case.metadata.get("expected_tool_call")
    actual_tool_call = candidate.tool_call

    if not isinstance(expected_tool_call, dict):
        return 0.0, "Eval case does not define an expected tool call."

    expected_name = expected_tool_call.get("name")

    if actual_tool_call is None:
        return 0.0, "Candidate did not make a tool call."

    actual_name = actual_tool_call.get("name")

    if actual_name == expected_name:
        return 1.0, "Candidate chose the expected tool."

    return 0.0, f"Expected tool '{expected_name}', but candidate chose '{actual_name}'."

def grade_tool_arguments(case: EvalCase, candidate: CandidateAnswer) -> tuple[float, str]:
    expected_tool_call = case.metadata.get("expected_tool_call")
    actual_tool_call = candidate.tool_call

    if not isinstance(expected_tool_call, dict):
        return 0.0, "Eval case does not define an expected tool call."

    expected_arguments = expected_tool_call.get("arguments")

    if actual_tool_call is None:
        return 0.0, "Candidate did not make a tool call."

    actual_arguments = actual_tool_call.get("arguments")

    if actual_arguments == expected_arguments:
        return 1.0, "Candidate used the expected tool arguments."

    return 0.0, (
        f"Expected arguments {expected_arguments}, "
        f"but candidate used {actual_arguments}."
    )

def grade_final_answer(case: EvalCase, candidate: CandidateAnswer) -> tuple[float, str]:
    score = judge_candidate_answer(case, candidate)
    return score.correctness, score.explanation

def judge_agentic_tool_call(case: EvalCase, candidate: CandidateAnswer) -> dict:
    tool_choice_score, tool_choice_explanation = grade_tool_choice(case, candidate)
    tool_arguments_score, tool_arguments_explanation = grade_tool_arguments(case, candidate)
    final_answer_score, final_answer_explanation = grade_final_answer(case, candidate)

    passed = (
        tool_choice_score == 1.0
        and tool_arguments_score == 1.0
        and final_answer_score >= 0.8
    )

    return {
        "run_id": candidate.run_id,
        "case_id": candidate.case_id,
        "tool_choice_score": tool_choice_score,
        "tool_arguments_score": tool_arguments_score,
        "final_answer_score": final_answer_score,
        "passed": passed,
        "explanations": {
            "tool_choice": tool_choice_explanation,
            "tool_arguments": tool_arguments_explanation,
            "final_answer": final_answer_explanation,
        },
    }