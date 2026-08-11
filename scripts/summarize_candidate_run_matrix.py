import argparse
import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MATRIX_PATH = Path("config/candidate_answer_run_matrix.json")


class MatrixValidationError(Exception):
    pass


@dataclass(frozen=True)
class RunRow:
    block_id: str
    dataset_version: str
    task_family: str
    case_count: int
    provider: str
    model: str
    retrieval_mode: str
    prompt_version: str
    repeat_id: str


def load_matrix(path: Path = DEFAULT_MATRIX_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise MatrixValidationError(f"Matrix config not found: {path}") from error
    except json.JSONDecodeError as error:
        raise MatrixValidationError(f"Matrix config is not valid JSON: {path}") from error


def provider_key(provider_model: dict) -> str:
    return f"{provider_model['provider']}:{provider_model['model']}"


def expand_run_matrix(matrix: dict) -> list[RunRow]:
    datasets = {dataset["dataset_version"]: dataset for dataset in matrix["datasets"]}
    provider_models = {
        provider_key(provider_model): provider_model
        for provider_model in matrix["provider_models"]
    }

    rows: list[RunRow] = []
    for block in matrix["run_blocks"]:
        dataset = datasets[block["dataset_version"]]
        for provider_model_key in block["provider_models"]:
            provider_model = provider_models[provider_model_key]
            for retrieval_mode in block["retrieval_modes"]:
                for prompt_version in block["prompt_versions"]:
                    for repeat_id in block["repeat_ids"]:
                        rows.append(
                            RunRow(
                                block_id=block["block_id"],
                                dataset_version=dataset["dataset_version"],
                                task_family=dataset["task_family"],
                                case_count=int(dataset["case_count"]),
                                provider=provider_model["provider"],
                                model=provider_model["model"],
                                retrieval_mode=retrieval_mode,
                                prompt_version=prompt_version,
                                repeat_id=repeat_id,
                            )
                        )

    return rows


def summarize_matrix(matrix: dict) -> dict:
    rows = expand_run_matrix(matrix)
    datasets = {dataset["dataset_version"]: dataset for dataset in matrix["datasets"]}
    provider_models = {
        provider_key(provider_model): provider_model
        for provider_model in matrix["provider_models"]
    }
    token_assumptions = matrix["token_estimate_assumptions"]

    candidate_answers_by_provider: dict[str, int] = {}
    run_count_by_task_family: dict[str, int] = {}
    candidate_answers_by_task_family: dict[str, int] = {}
    estimated_cost_by_provider: dict[str, float] = {}

    for row in rows:
        candidate_answers_by_provider[row.provider] = (
            candidate_answers_by_provider.get(row.provider, 0) + row.case_count
        )
        run_count_by_task_family[row.task_family] = (
            run_count_by_task_family.get(row.task_family, 0) + 1
        )
        candidate_answers_by_task_family[row.task_family] = (
            candidate_answers_by_task_family.get(row.task_family, 0) + row.case_count
        )

        model_key = f"{row.provider}:{row.model}"
        provider_model = provider_models[model_key]
        assumption = token_assumptions[row.task_family]
        input_mtok = (
            row.case_count * assumption["average_input_tokens_per_answer"] / 1_000_000
        )
        output_mtok = (
            row.case_count * assumption["average_output_tokens_per_answer"] / 1_000_000
        )
        estimated_cost_by_provider[row.provider] = estimated_cost_by_provider.get(
            row.provider,
            0.0,
        ) + (
            input_mtok * provider_model["input_usd_per_million_tokens"]
            + output_mtok * provider_model["output_usd_per_million_tokens"]
        )

    primary_rag_run_count = sum(
        1
        for row in rows
        if row.task_family == "rag"
        and datasets[row.dataset_version]["counts_toward_8k_scale_math"]
    )
    primary_rag_candidate_answer_count = sum(
        row.case_count
        for row in rows
        if row.task_family == "rag"
        and datasets[row.dataset_version]["counts_toward_8k_scale_math"]
    )

    estimated_total_cost = sum(estimated_cost_by_provider.values())

    return {
        "primary_rag_run_count": primary_rag_run_count,
        "agentic_tool_run_count": run_count_by_task_family.get(
            "agentic_tool_calling",
            0,
        ),
        "total_run_count": len(rows),
        "primary_rag_candidate_answer_count": primary_rag_candidate_answer_count,
        "agentic_tool_candidate_answer_count": candidate_answers_by_task_family.get(
            "agentic_tool_calling",
            0,
        ),
        "total_candidate_answer_count": sum(candidate_answers_by_provider.values()),
        "candidate_answer_count_by_provider": candidate_answers_by_provider,
        "estimated_generation_cost_usd_by_provider": {
            provider: round(cost, 4)
            for provider, cost in sorted(estimated_cost_by_provider.items())
        },
        "estimated_total_generation_cost_usd": round(estimated_total_cost, 2),
        "estimated_total_generation_cost_with_20_percent_buffer_usd": round(
            estimated_total_cost * 1.2,
            2,
        ),
    }


def validate_expected_summary(matrix: dict, summary: dict) -> None:
    expected = matrix.get("expected_summary", {})
    keys_to_validate = [
        "primary_rag_run_count",
        "agentic_tool_run_count",
        "total_run_count",
        "primary_rag_candidate_answer_count",
        "agentic_tool_candidate_answer_count",
        "total_candidate_answer_count",
        "candidate_answer_count_by_provider",
        "estimated_total_generation_cost_usd",
        "estimated_total_generation_cost_with_20_percent_buffer_usd",
    ]

    for key in keys_to_validate:
        if expected.get(key) != summary.get(key):
            raise MatrixValidationError(
                f"expected_summary.{key}={expected.get(key)!r} "
                f"does not match computed {summary.get(key)!r}"
            )


def render_summary(summary: dict) -> str:
    lines = ["candidate_answer_run_matrix_summary"]
    lines.append(f"primary_rag_run_count={summary['primary_rag_run_count']}")
    lines.append(f"agentic_tool_run_count={summary['agentic_tool_run_count']}")
    lines.append(f"total_run_count={summary['total_run_count']}")
    lines.append(
        "primary_rag_candidate_answer_count="
        f"{summary['primary_rag_candidate_answer_count']}"
    )
    lines.append(
        "agentic_tool_candidate_answer_count="
        f"{summary['agentic_tool_candidate_answer_count']}"
    )
    lines.append(
        f"total_candidate_answer_count={summary['total_candidate_answer_count']}"
    )
    for provider, count in sorted(summary["candidate_answer_count_by_provider"].items()):
        lines.append(f"candidate_answer_count[{provider}]={count}")
    for provider, cost in sorted(
        summary["estimated_generation_cost_usd_by_provider"].items()
    ):
        lines.append(f"estimated_generation_cost_usd[{provider}]={cost:.4f}")
    lines.append(
        "estimated_total_generation_cost_usd="
        f"{summary['estimated_total_generation_cost_usd']:.2f}"
    )
    lines.append(
        "estimated_total_generation_cost_with_20_percent_buffer_usd="
        f"{summary['estimated_total_generation_cost_with_20_percent_buffer_usd']:.2f}"
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matrix = load_matrix(args.matrix)
    summary = summarize_matrix(matrix)
    if args.validate:
        validate_expected_summary(matrix, summary)
    print(render_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
