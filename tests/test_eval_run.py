import pytest
from pydantic import ValidationError
from backend.app.eval_run import EvalRun, RunStatus, CandidateAnswer, JudgeScore, JudgeType, ReviewCase, ReviewStatus


def test_eval_run_accepts_valid_data():
    run = EvalRun(
        run_id="run_001",
        dataset_version="golden_rag_v0.1",
        provider_name="openai",
    )

    assert run.run_id == "run_001"
    assert run.dataset_version == "golden_rag_v0.1"
    assert run.provider_name == "openai"
    assert run.status == RunStatus.QUEUED

def test_eval_run_rejects_blank_run_id():
    with pytest.raises(ValidationError):
        EvalRun(
            run_id=" ",
            dataset_version="golden_rag_v0.1",
            provider_name="openai",
        )


def test_candidate_answer_accepts_valid_data():
    answer = CandidateAnswer(
        run_id="run_001",
        case_id="case_001",
        generated_answer="Test answer.",
    )

    assert answer.run_id=="run_001"
    assert answer.case_id=="case_001"
    assert answer.generated_answer=="Test answer."
    assert answer.trace_id is None
    assert answer.status == RunStatus.COMPLETED

def test_judge_score_accepts_structured_scores():
    score = JudgeScore(
        run_id="run_001",
        case_id="case_001",
        judge_name="gpt-4o-mini-rag-judge-v1",
        judge_type=JudgeType.GPT4O_MINI,
        correctness=0.9,
        faithfulness=0.8,
        citation_quality=0.7,
        passed=True,
        explanation="The answer is correct and mostly supported by the retrieved context.",
    )

    assert score.run_id == "run_001"
    assert score.case_id == "case_001"
    assert score.judge_name == "gpt-4o-mini-rag-judge-v1"
    assert score.judge_type == JudgeType.GPT4O_MINI
    assert score.correctness == 0.9
    assert score.faithfulness == 0.8
    assert score.citation_quality == 0.7
    assert score.passed is True
    assert score.explanation.startswith("The answer is correct")
    assert score.trace_id is None
    assert score.status == RunStatus.COMPLETED


def test_judge_score_rejects_score_above_one():
    with pytest.raises(ValidationError):
        JudgeScore(
            run_id="run_001",
            case_id="case_001",
            judge_name="gpt-4o-mini-rag-judge-v1",
            judge_type=JudgeType.GPT4O_MINI,
            correctness=1.2,
            faithfulness=0.8,
            citation_quality=0.7,
            passed=False,
            explanation="Correctness is invalid because it is above the allowed range.",
        )

def test_review_case_accepts_pending_disagreement_case():
    review_case = ReviewCase(
        run_id="run_001",
        case_id="case_001",
        answer="The candidate answer under review.",
        judge_a_score=0.9,
        judge_b_score=0.2,
        disagreement_reason="Judges disagree on correctness by more than threshold.",
    )

    assert review_case.run_id == "run_001"
    assert review_case.case_id == "case_001"
    assert review_case.answer == "The candidate answer under review."
    assert review_case.judge_a_score == 0.9
    assert review_case.judge_b_score == 0.2
    assert review_case.disagreement_reason.startswith("Judges disagree")
    assert review_case.human_label is None
    assert review_case.final_decision is None
    assert review_case.status == ReviewStatus.PENDING

def test_review_case_rejects_score_above_one():
    with pytest.raises(ValidationError):
        ReviewCase(
            run_id="run_001",
            case_id="case_001",
            answer="The candidate answer under review.",
            judge_a_score=1.1,
            judge_b_score=0.2,
            disagreement_reason="Judge A score is outside the allowed range.",
        )