import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer, JudgeScore, ReviewCase


DEFAULT_SCORE_DISAGREEMENT_THRESHOLD = 0.25
MOCK_7B_WARNING = (
    "Mock 7B agreement is only a harness test. It is not final measured judge "
    "agreement and must not be reported as a measured result."
)


class Judge(Protocol):
    judge_name: str

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        ...


class DualJudgeCaseResult(BaseModel):
    run_id: str
    case_id: str
    candidate_answer: str
    judge_a_score: JudgeScore
    judge_b_score: JudgeScore
    pass_fail_agree: bool
    correctness_delta: float
    faithfulness_delta: float
    citation_quality_delta: float
    score_agree: bool
    disagreement_reason: str | None = None


class DualJudgeValidationReport(BaseModel):
    validation_run_id: str
    created_at: str
    judge_a_name: str
    judge_b_name: str
    total_cases: int
    pass_fail_agreements: int
    pass_fail_disagreements: int
    pass_fail_agreement_percentage: float
    score_disagreement_threshold: float
    score_agreements: int
    score_disagreements: int
    score_agreement_percentage: float
    mean_correctness_delta: float
    mean_faithfulness_delta: float
    mean_citation_quality_delta: float
    inter_judge_kappa: float | None = None
    judge_a_human_kappa: float | None = None
    judge_b_human_kappa: float | None = None
    # Pass rates make a degenerate validation slice visible. When either rate is
    # 0.0 or 1.0 the judge used a single category, so pass/fail agreement is
    # trivially high and inter_judge_kappa is None rather than a real score.
    judge_a_pass_rate: float = 0.0
    judge_b_pass_rate: float = 0.0
    agreement_is_degenerate: bool = False
    manual_review_case_count: int
    # Only populated when judge B was a mock. A real run must not carry a warning
    # saying its numbers are a harness test -- that is a provenance error in the
    # opposite direction, and it would discredit a measurement that is sound.
    mock_7b_warning: str | None = None
    metadata: dict = Field(default_factory=dict)
    results: list[DualJudgeCaseResult] = Field(default_factory=list)


class DualJudgeValidationResult(BaseModel):
    report: DualJudgeValidationReport
    manual_review_cases: list[ReviewCase]


def run_dual_judge_validation(
    cases: list[EvalCase],
    candidates: list[CandidateAnswer],
    judge_a: Judge,
    judge_b: Judge,
    retrieved_context_by_case_id: dict[str, list[str]] | None = None,
    human_labels_by_case_id: dict[str, bool] | None = None,
    compare_scores: bool = True,
    score_disagreement_threshold: float = DEFAULT_SCORE_DISAGREEMENT_THRESHOLD,
    validation_run_id: str | None = None,
    report_metadata: dict | None = None,
    judge_b_is_mock: bool = False,
) -> DualJudgeValidationResult:
    if not candidates:
        raise ValueError("At least one candidate answer is required.")

    if score_disagreement_threshold < 0:
        raise ValueError("score_disagreement_threshold must be >= 0.")

    cases_by_id = {case.id: case for case in cases}
    retrieved_context_by_case_id = retrieved_context_by_case_id or {}

    case_results: list[DualJudgeCaseResult] = []
    manual_review_cases: list[ReviewCase] = []

    for candidate in candidates:
        case = cases_by_id.get(candidate.case_id)
        if case is None:
            raise ValueError(f"Unknown case_id in candidate answers: {candidate.case_id}")

        retrieved_context = retrieved_context_by_case_id.get(candidate.case_id, [])
        judge_a_score = judge_a.judge_candidate_answer(
            case=case,
            candidate=candidate,
            retrieved_context=retrieved_context,
        )
        judge_b_score = judge_b.judge_candidate_answer(
            case=case,
            candidate=candidate,
            retrieved_context=retrieved_context,
        )

        correctness_delta = abs(judge_a_score.correctness - judge_b_score.correctness)
        faithfulness_delta = abs(judge_a_score.faithfulness - judge_b_score.faithfulness)
        citation_quality_delta = abs(
            judge_a_score.citation_quality - judge_b_score.citation_quality
        )
        pass_fail_agree = judge_a_score.passed == judge_b_score.passed
        score_agree = correctness_delta <= score_disagreement_threshold

        disagreement_reason = build_disagreement_reason(
            judge_a_score=judge_a_score,
            judge_b_score=judge_b_score,
            compare_scores=compare_scores,
            score_agree=score_agree,
            correctness_delta=correctness_delta,
            score_disagreement_threshold=score_disagreement_threshold,
        )

        case_result = DualJudgeCaseResult(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            candidate_answer=candidate.generated_answer,
            judge_a_score=judge_a_score,
            judge_b_score=judge_b_score,
            pass_fail_agree=pass_fail_agree,
            correctness_delta=correctness_delta,
            faithfulness_delta=faithfulness_delta,
            citation_quality_delta=citation_quality_delta,
            score_agree=score_agree,
            disagreement_reason=disagreement_reason,
        )
        case_results.append(case_result)

        if disagreement_reason is not None:
            manual_review_cases.append(
                ReviewCase(
                    run_id=candidate.run_id,
                    case_id=candidate.case_id,
                    answer=candidate.generated_answer,
                    judge_a_score=judge_a_score.correctness,
                    judge_b_score=judge_b_score.correctness,
                    disagreement_reason=disagreement_reason,
                )
            )

    report = build_validation_report(
        judge_a_name=judge_a.judge_name,
        judge_b_name=judge_b.judge_name,
        case_results=case_results,
        manual_review_cases=manual_review_cases,
        score_disagreement_threshold=score_disagreement_threshold,
        human_labels_by_case_id=human_labels_by_case_id,
        validation_run_id=validation_run_id,
        report_metadata=report_metadata,
        judge_b_is_mock=judge_b_is_mock,
    )

    return DualJudgeValidationResult(
        report=report,
        manual_review_cases=manual_review_cases,
    )


def build_disagreement_reason(
    judge_a_score: JudgeScore,
    judge_b_score: JudgeScore,
    compare_scores: bool,
    score_agree: bool,
    correctness_delta: float,
    score_disagreement_threshold: float,
) -> str | None:
    reasons: list[str] = []

    if judge_a_score.status != judge_b_score.status:
        reasons.append(
            f"judge_status_differs: {judge_a_score.status.value} vs {judge_b_score.status.value}"
        )
    elif judge_a_score.status.value == "failed":
        reasons.append("both_judges_failed")

    if judge_a_score.passed != judge_b_score.passed:
        reasons.append(
            f"pass_fail_differs: {judge_a_score.passed} vs {judge_b_score.passed}"
        )

    if compare_scores and not score_agree:
        reasons.append(
            "correctness_delta_exceeds_threshold: "
            f"{correctness_delta:.3f} > {score_disagreement_threshold:.3f}"
        )

    if not reasons:
        return None

    return "; ".join(reasons)


def build_validation_report(
    judge_a_name: str,
    judge_b_name: str,
    case_results: list[DualJudgeCaseResult],
    manual_review_cases: list[ReviewCase],
    score_disagreement_threshold: float,
    human_labels_by_case_id: dict[str, bool] | None = None,
    validation_run_id: str | None = None,
    report_metadata: dict | None = None,
    judge_b_is_mock: bool = False,
) -> DualJudgeValidationReport:
    total_cases = len(case_results)
    pass_fail_agreements = sum(result.pass_fail_agree for result in case_results)
    score_agreements = sum(result.score_agree for result in case_results)

    judge_a_labels = [result.judge_a_score.passed for result in case_results]
    judge_b_labels = [result.judge_b_score.passed for result in case_results]

    judge_a_human_kappa = None
    judge_b_human_kappa = None

    if human_labels_by_case_id:
        judge_a_human_pairs = [
            (result.judge_a_score.passed, human_labels_by_case_id[result.case_id])
            for result in case_results
            if result.case_id in human_labels_by_case_id
        ]
        judge_b_human_pairs = [
            (result.judge_b_score.passed, human_labels_by_case_id[result.case_id])
            for result in case_results
            if result.case_id in human_labels_by_case_id
        ]
        judge_a_human_kappa = calculate_cohens_kappa_from_pairs(judge_a_human_pairs)
        judge_b_human_kappa = calculate_cohens_kappa_from_pairs(judge_b_human_pairs)

    judge_a_pass_rate = percentage(sum(judge_a_labels), total_cases) / 100.0
    judge_b_pass_rate = percentage(sum(judge_b_labels), total_cases) / 100.0
    # A judge that used only one category makes pass/fail agreement meaningless.
    agreement_is_degenerate = judge_a_pass_rate in (0.0, 1.0) or judge_b_pass_rate in (
        0.0,
        1.0,
    )

    return DualJudgeValidationReport(
        validation_run_id=validation_run_id or create_validation_run_id(),
        created_at=datetime.now(timezone.utc).isoformat(),
        judge_a_name=judge_a_name,
        judge_b_name=judge_b_name,
        total_cases=total_cases,
        pass_fail_agreements=pass_fail_agreements,
        pass_fail_disagreements=total_cases - pass_fail_agreements,
        pass_fail_agreement_percentage=percentage(pass_fail_agreements, total_cases),
        score_disagreement_threshold=score_disagreement_threshold,
        score_agreements=score_agreements,
        score_disagreements=total_cases - score_agreements,
        score_agreement_percentage=percentage(score_agreements, total_cases),
        mean_correctness_delta=mean(
            [result.correctness_delta for result in case_results]
        ),
        mean_faithfulness_delta=mean(
            [result.faithfulness_delta for result in case_results]
        ),
        mean_citation_quality_delta=mean(
            [result.citation_quality_delta for result in case_results]
        ),
        inter_judge_kappa=calculate_cohens_kappa(judge_a_labels, judge_b_labels),
        judge_a_human_kappa=judge_a_human_kappa,
        judge_b_human_kappa=judge_b_human_kappa,
        judge_a_pass_rate=judge_a_pass_rate,
        judge_b_pass_rate=judge_b_pass_rate,
        agreement_is_degenerate=agreement_is_degenerate,
        manual_review_case_count=len(manual_review_cases),
        mock_7b_warning=MOCK_7B_WARNING if judge_b_is_mock else None,
        metadata=report_metadata or {},
        results=case_results,
    )


def calculate_cohens_kappa(labels_a: list[bool], labels_b: list[bool]) -> float | None:
    if len(labels_a) != len(labels_b):
        raise ValueError("Kappa label lists must have the same length.")

    return calculate_cohens_kappa_from_pairs(list(zip(labels_a, labels_b)))


def calculate_cohens_kappa_from_pairs(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None

    total = len(pairs)
    observed_agreement = sum(left == right for left, right in pairs) / total

    left_true_rate = sum(left for left, _ in pairs) / total
    left_false_rate = 1.0 - left_true_rate
    right_true_rate = sum(right for _, right in pairs) / total
    right_false_rate = 1.0 - right_true_rate
    expected_agreement = (
        left_true_rate * right_true_rate + left_false_rate * right_false_rate
    )

    # When expected agreement is 1.0 both raters used a single category, so
    # chance agreement is total and kappa has no defined value. Returning 1.0
    # here would manufacture a perfect-agreement signal out of a degenerate
    # case; callers must see None and fall back to the pass rates instead.
    if expected_agreement == 1.0:
        return None

    return (observed_agreement - expected_agreement) / (1.0 - expected_agreement)


def save_validation_artifacts(
    result: DualJudgeValidationResult,
    report_path: Path,
    manual_review_queue_path: Path,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manual_review_queue_path.parent.mkdir(parents=True, exist_ok=True)

    with report_path.open("w", encoding="utf-8") as file:
        json.dump(result.report.model_dump(mode="json"), file, indent=2)

    with manual_review_queue_path.open("w", encoding="utf-8") as file:
        for review_case in result.manual_review_cases:
            file.write(json.dumps(review_case.model_dump(mode="json")) + "\n")


def create_validation_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"dual_judge_validation_{timestamp}"


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0

    return (numerator / denominator) * 100.0


def mean(values: list[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)
