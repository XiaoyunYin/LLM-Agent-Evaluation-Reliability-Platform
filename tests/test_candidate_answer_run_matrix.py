from pathlib import Path

from scripts.summarize_candidate_run_matrix import (
    expand_run_matrix,
    load_matrix,
    summarize_matrix,
    validate_expected_summary,
)
from scripts.submit_candidate_run_matrix import build_mini_balanced_rows


MATRIX_PATH = Path("config/candidate_answer_run_matrix.json")


def test_candidate_answer_run_matrix_matches_expected_summary():
    matrix = load_matrix(MATRIX_PATH)
    summary = summarize_matrix(matrix)

    validate_expected_summary(matrix, summary)

    assert summary["primary_rag_run_count"] == 68
    assert summary["agentic_tool_run_count"] == 4
    assert summary["total_run_count"] == 72
    assert summary["primary_rag_candidate_answer_count"] == 8160
    assert summary["agentic_tool_candidate_answer_count"] == 8
    assert summary["total_candidate_answer_count"] == 8168


def test_candidate_answer_run_matrix_has_balanced_real_provider_coverage():
    matrix = load_matrix(MATRIX_PATH)
    summary = summarize_matrix(matrix)

    assert summary["candidate_answer_count_by_provider"] == {
        "openai": 4084,
        "anthropic": 4084,
    }
    assert all(
        provider_model["counts_as_real_provider_diversity"]
        for provider_model in matrix["provider_models"]
    )


def test_candidate_answer_run_matrix_keeps_mock_and_self_hosted_out_of_diversity_claim():
    matrix = load_matrix(MATRIX_PATH)
    providers = {provider_model["provider"] for provider_model in matrix["provider_models"]}

    assert "mock" not in providers
    assert "self_hosted" not in providers
    assert matrix["guardrails"]["mock_provider_runs_count_as_real_provider_diversity"] is False
    assert matrix["guardrails"]["self_hosted_candidate_generation_required"] is False
    assert matrix["guardrails"]["self_hosted_mistral_role"] == (
        "judge_only_for_current_resume_scope"
    )


def test_candidate_answer_run_matrix_is_generation_only_before_judging():
    matrix = load_matrix(MATRIX_PATH)

    assert matrix["phase"] == "candidate_answer_generation_before_judging"
    assert matrix["judging_included"] is False
    assert matrix["guardrails"]["candidate_answers_must_exist_before_bulk_judging"] is True


def test_candidate_answer_run_rows_include_rag_and_agentic_cases():
    matrix = load_matrix(MATRIX_PATH)
    rows = expand_run_matrix(matrix)
    task_families = {row.task_family for row in rows}
    retrieval_modes = {row.retrieval_mode for row in rows}
    prompt_versions = {row.prompt_version for row in rows}

    assert "rag" in task_families
    assert "agentic_tool_calling" in task_families
    assert "hybrid_rrf_k60_top10_context4" in retrieval_modes
    assert "tool_calling_no_retrieval" in retrieval_modes
    assert "rag_prompt_v1" in prompt_versions
    assert "agentic_prompt_v1" in prompt_versions


def test_candidate_answer_run_matrix_estimates_api_cost_before_running():
    matrix = load_matrix(MATRIX_PATH)
    summary = summarize_matrix(matrix)

    assert matrix["guardrails"]["cost_values_are_estimates_not_measured_spend"] is True
    assert summary["estimated_generation_cost_usd_by_provider"]["openai"] == 2.3277
    assert summary["estimated_generation_cost_usd_by_provider"]["anthropic"] == 16.948
    assert summary["estimated_total_generation_cost_usd"] == 19.28
    assert summary["estimated_total_generation_cost_with_20_percent_buffer_usd"] == 23.13


def test_mini_balanced_matrix_selects_four_runs_per_real_provider():
    matrix = load_matrix(MATRIX_PATH)
    rows = build_mini_balanced_rows(expand_run_matrix(matrix))

    provider_counts = {}
    retrieval_modes = {row.retrieval_mode for row in rows}
    prompt_versions = {row.prompt_version for row in rows}
    for row in rows:
        provider_counts[row.provider] = provider_counts.get(row.provider, 0) + 1

    assert len(rows) == 8
    assert provider_counts == {"openai": 4, "anthropic": 4}
    assert retrieval_modes == {
        "bm25_top50_context4",
        "hybrid_rrf_k60_top10_context4",
    }
    assert prompt_versions == {"rag_prompt_v1", "rag_prompt_v2"}
