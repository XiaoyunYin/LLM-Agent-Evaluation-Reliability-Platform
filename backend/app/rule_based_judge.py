from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer, JudgeScore, JudgeType


def normalize_answer(value: str) -> str:
    return value.strip().lower()


def judge_candidate_answer(
    case: EvalCase,
    candidate: CandidateAnswer,
) -> JudgeScore:
    expected = normalize_answer(case.expected_answer)
    generated = normalize_answer(candidate.generated_answer)

    if generated == expected:
        correctness = 1.0
        passed = True
        explanation = "Generated answer exactly matches expected answer."
    elif expected in generated:
        correctness = 0.8
        passed = True
        explanation = "Generated answer contains the expected answer."
    else:
        correctness = 0.0
        passed = False
        explanation = "Generated answer does not match expected answer."

    return JudgeScore(
        run_id=candidate.run_id,
        case_id=candidate.case_id,
        judge_name="rule-based-v0",
        judge_type=JudgeType.RULE_BASED,
        correctness=correctness,
        faithfulness=0.0,
        citation_quality=0.0,
        passed=passed,
        explanation=explanation,
        trace_id=candidate.trace_id,
    )