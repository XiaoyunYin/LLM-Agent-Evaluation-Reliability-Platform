import json
from pathlib import Path

import pytest

from backend.app.dual_judge_validation import (
    MOCK_7B_WARNING,
    calculate_cohens_kappa,
    run_dual_judge_validation,
    save_validation_artifacts,
)
from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer, JudgeScore, JudgeType


class FakeJudge:
    def __init__(self, judge_name: str, judge_type: JudgeType, scores_by_case_id: dict):
        self.judge_name = judge_name
        self.judge_type = judge_type
        self.scores_by_case_id = scores_by_case_id
        self.calls: list[dict] = []

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        self.calls.append(
            {
                "case_id": case.id,
                "candidate_case_id": candidate.case_id,
                "retrieved_context": retrieved_context or [],
            }
        )
        score_data = self.scores_by_case_id[case.id]

        return JudgeScore(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            judge_name=self.judge_name,
            judge_type=self.judge_type,
            correctness=score_data["correctness"],
            faithfulness=score_data.get("faithfulness", score_data["correctness"]),
            citation_quality=score_data.get("citation_quality", 0.0),
            passed=score_data["passed"],
            explanation=score_data.get("explanation", "Fake judge score."),
            trace_id=candidate.trace_id,
        )


def make_cases() -> list[EvalCase]:
    return [
        EvalCase(
            id="case_001",
            question="Question 1?",
            expected_answer="Answer 1",
            task_type=TaskType.DIRECT_QA,
        ),
        EvalCase(
            id="case_002",
            question="Question 2?",
            expected_answer="Answer 2",
            task_type=TaskType.DIRECT_QA,
        ),
        EvalCase(
            id="case_003",
            question="Question 3?",
            expected_answer="Answer 3",
            task_type=TaskType.DIRECT_QA,
        ),
    ]


def make_candidates() -> list[CandidateAnswer]:
    return [
        CandidateAnswer(
            run_id="run_001",
            case_id="case_001",
            generated_answer="Candidate answer 1",
        ),
        CandidateAnswer(
            run_id="run_001",
            case_id="case_002",
            generated_answer="Candidate answer 2",
        ),
        CandidateAnswer(
            run_id="run_001",
            case_id="case_003",
            generated_answer="Candidate answer 3",
        ),
    ]


def test_dual_judge_validation_runs_both_judges_on_same_slice():
    judge_a = FakeJudge(
        judge_name="gpt-4o-mini-validation-v0",
        judge_type=JudgeType.GPT4O_MINI,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 0.2, "passed": False},
            "case_003": {"correctness": 0.8, "passed": True},
        },
    )
    judge_b = FakeJudge(
        judge_name="mock-self-hosted-7b",
        judge_type=JudgeType.SELF_HOSTED_7B,
        scores_by_case_id={
            "case_001": {"correctness": 0.9, "passed": True},
            "case_002": {"correctness": 0.3, "passed": False},
            "case_003": {"correctness": 0.1, "passed": False},
        },
    )

    result = run_dual_judge_validation(
        cases=make_cases(),
        candidates=make_candidates(),
        judge_a=judge_a,
        judge_b=judge_b,
        retrieved_context_by_case_id={"case_001": ["[chunk_001] context"]},
    )

    assert [call["case_id"] for call in judge_a.calls] == [
        "case_001",
        "case_002",
        "case_003",
    ]
    assert [call["case_id"] for call in judge_b.calls] == [
        "case_001",
        "case_002",
        "case_003",
    ]
    assert judge_a.calls[0]["retrieved_context"] == ["[chunk_001] context"]
    assert result.report.total_cases == 3
    assert result.report.pass_fail_agreements == 2
    assert result.report.pass_fail_disagreements == 1
    assert result.report.pass_fail_agreement_percentage == pytest.approx(
        66.666,
        abs=0.001,
    )
    assert result.report.mock_7b_warning == MOCK_7B_WARNING


def test_dual_judge_validation_routes_disagreements_to_manual_review_queue():
    judge_a = FakeJudge(
        judge_name="gpt-4o-mini-validation-v0",
        judge_type=JudgeType.GPT4O_MINI,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 0.9, "passed": True},
            "case_003": {"correctness": 0.5, "passed": False},
        },
    )
    judge_b = FakeJudge(
        judge_name="mock-self-hosted-7b",
        judge_type=JudgeType.SELF_HOSTED_7B,
        scores_by_case_id={
            "case_001": {"correctness": 0.9, "passed": True},
            "case_002": {"correctness": 0.2, "passed": False},
            "case_003": {"correctness": 0.1, "passed": False},
        },
    )

    result = run_dual_judge_validation(
        cases=make_cases(),
        candidates=make_candidates(),
        judge_a=judge_a,
        judge_b=judge_b,
        score_disagreement_threshold=0.25,
    )

    assert result.report.manual_review_case_count == 2
    assert [case.case_id for case in result.manual_review_cases] == [
        "case_002",
        "case_003",
    ]
    assert "pass_fail_differs" in result.manual_review_cases[0].disagreement_reason
    assert (
        "correctness_delta_exceeds_threshold"
        in result.manual_review_cases[1].disagreement_reason
    )


def test_cohens_kappa_returns_chance_adjusted_agreement():
    kappa = calculate_cohens_kappa(
        labels_a=[True, True, False, False],
        labels_b=[True, False, False, False],
    )

    assert kappa == pytest.approx(0.5)


def test_cohens_kappa_is_undefined_when_both_judges_use_one_category():
    """Regression guard for the Session 44 degenerate validation slice.

    Both judges failed all 120 cases, which made observed agreement 100% while
    chance agreement was also 100%. Kappa has no defined value there, and the
    old implementation returned a hardcoded 1.0 that read as perfect agreement.
    """
    kappa = calculate_cohens_kappa(
        labels_a=[False, False, False, False],
        labels_b=[False, False, False, False],
    )

    assert kappa is None

    kappa_all_pass = calculate_cohens_kappa(
        labels_a=[True, True, True],
        labels_b=[True, True, True],
    )

    assert kappa_all_pass is None


def test_dual_judge_validation_calculates_human_label_kappas():
    judge_a = FakeJudge(
        judge_name="gpt-4o-mini-validation-v0",
        judge_type=JudgeType.GPT4O_MINI,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 0.2, "passed": False},
            "case_003": {"correctness": 0.2, "passed": False},
        },
    )
    judge_b = FakeJudge(
        judge_name="mock-self-hosted-7b",
        judge_type=JudgeType.SELF_HOSTED_7B,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 1.0, "passed": True},
            "case_003": {"correctness": 0.2, "passed": False},
        },
    )

    result = run_dual_judge_validation(
        cases=make_cases(),
        candidates=make_candidates(),
        judge_a=judge_a,
        judge_b=judge_b,
        human_labels_by_case_id={
            "case_001": True,
            "case_002": False,
            "case_003": False,
        },
    )

    assert result.report.judge_a_human_kappa == pytest.approx(1.0)
    assert result.report.judge_b_human_kappa == pytest.approx(0.4)


def test_save_validation_artifacts_writes_report_and_review_queue():
    judge_a = FakeJudge(
        judge_name="gpt-4o-mini-validation-v0",
        judge_type=JudgeType.GPT4O_MINI,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 0.9, "passed": True},
            "case_003": {"correctness": 0.2, "passed": False},
        },
    )
    judge_b = FakeJudge(
        judge_name="mock-self-hosted-7b",
        judge_type=JudgeType.SELF_HOSTED_7B,
        scores_by_case_id={
            "case_001": {"correctness": 1.0, "passed": True},
            "case_002": {"correctness": 0.2, "passed": False},
            "case_003": {"correctness": 0.2, "passed": False},
        },
    )
    result = run_dual_judge_validation(
        cases=make_cases(),
        candidates=make_candidates(),
        judge_a=judge_a,
        judge_b=judge_b,
    )
    artifact_dir = Path("runs/test_dual_judge_validation_artifacts")
    report_path = artifact_dir / "validation_report.json"
    review_queue_path = artifact_dir / "manual_review_queue.jsonl"

    save_validation_artifacts(
        result=result,
        report_path=report_path,
        manual_review_queue_path=review_queue_path,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    review_rows = [
        json.loads(line)
        for line in review_queue_path.read_text(encoding="utf-8").splitlines()
        if line
    ]

    assert report["total_cases"] == 3
    assert report["manual_review_case_count"] == 1
    assert review_rows[0]["case_id"] == "case_002"


def test_dual_judge_validation_rejects_empty_candidate_slice():
    with pytest.raises(ValueError):
        run_dual_judge_validation(
            cases=make_cases(),
            candidates=[],
            judge_a=FakeJudge("judge-a", JudgeType.GPT4O_MINI, {}),
            judge_b=FakeJudge("judge-b", JudgeType.SELF_HOSTED_7B, {}),
        )
