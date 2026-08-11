import json
import sys
from pathlib import Path
from collections import Counter

REQUIRED_FIELDS = {
    "id",
    "query",
    "split",
    "labeling_protocol_version",
    "labels_created_blind_to_judge_outputs",
    "categories",
    "relevant_chunks",
    "labeling_limitations",
}

VALID_DIFFICULTIES = {"easy", "hard"}
VALID_HOP_TYPES = {"single-hop", "multi-hop"}
VALID_MATCH_TYPES = {"exact-term", "semantic/paraphrase"}
VALID_RELEVANCE = {0, 1, 2}

TARGET_TOTAL_RECORDS = 120
TARGET_PER_CATEGORY_CELL = 15
RESULT_NOTE_PATH = Path("docs/docs/retrieval-label-validation-results.md")
DEFAULT_LABEL_PATH = Path("datasets/labels/retrieval_heldout_120_v0.2.jsonl")


def load_chunk_ids(chunk_path: Path) -> set[str]:
    chunk_ids = set()

    with chunk_path.open("r", encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            chunk_ids.add(chunk["id"])

    return chunk_ids


def validate_strict_distribution(count: int, category_counts: Counter) -> None:
    if count != TARGET_TOTAL_RECORDS:
        raise ValueError(f"expected {TARGET_TOTAL_RECORDS} records, found {count}")

    for difficulty in VALID_DIFFICULTIES:
        for hop_type in VALID_HOP_TYPES:
            for match_type in VALID_MATCH_TYPES:
                category_key = (difficulty, hop_type, match_type)
                actual_count = category_counts[category_key]

                if actual_count != TARGET_PER_CATEGORY_CELL:
                    raise ValueError(
                        f"expected {TARGET_PER_CATEGORY_CELL} records for "
                        f"{category_key}, found {actual_count}"
                    )


def format_counter(counter: Counter) -> list[str]:
    return [f"- {key}: {counter[key]}" for key in sorted(counter)]


def write_results_note(
    count: int,
    relevant_chunk_reference_count: int,
    relevance_counts: Counter,
    category_counts: Counter,
    difficulty_counts: Counter,
    hop_type_counts: Counter,
    match_type_counts: Counter,
    domain_counts: Counter,
) -> None:
    completeness = "complete"
    completeness_note = f"The labeled query set meets the target of {TARGET_TOTAL_RECORDS} queries."

    if count < TARGET_TOTAL_RECORDS:
        completeness = "incomplete"
        completeness_note = (
            f"The labeled query set is incomplete: found {count} queries, "
            f"below the target of {TARGET_TOTAL_RECORDS}. Continue honestly using {count} "
            "as the measured size until more labels are added."
        )

    lines = [
        "# Retrieval Label Validation Results",
        "",
        "## Summary",
        "",
        f"- Labeled queries measured: {count}",
        f"- Dossier input target: {TARGET_TOTAL_RECORDS}",
        f"- Completion status: {completeness}",
        f"- Relevant chunk references checked: {relevant_chunk_reference_count}",
        "- Unknown relevant chunk IDs: 0",
        f"- Result: {completeness_note}",
        "",
        "## Label Distribution",
        "",
        *[
            f"- relevance {relevance}: {relevance_counts[relevance]}"
            for relevance in sorted(VALID_RELEVANCE)
        ],
        "",
        "## Query Category Distribution",
        "",
        "Difficulty:",
        *format_counter(difficulty_counts),
        "",
        "Hop type:",
        *format_counter(hop_type_counts),
        "",
        "Match type:",
        *format_counter(match_type_counts),
        "",
        "Domain:",
        *format_counter(domain_counts),
        "",
        "Combined category cells:",
        *format_counter(category_counts),
        "",
        "## Why This Validation Matters",
        "",
        (
            "Validation matters because retrieval scores only mean something when the "
            "gold labels point to real chunks and use consistent metadata."
        ),
        (
            "Broken labels include missing fields, duplicate queries, invalid relevance "
            "values, empty relevant chunk lists, or chunk IDs that do not exist in the corpus."
        ),
        (
            "Label distribution matters because the mix of relevance grades affects how "
            "strict or forgiving the retrieval benchmark is."
        ),
        (
            "Query category distribution matters because it shows whether the held-out set "
            "covers easy, hard, single-hop, multi-hop, exact-term, and semantic retrieval cases."
        ),
        "",
        "Metric integrity note: this validates label structure only. It does not measure retrieval quality.",
    ]

    RESULT_NOTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_NOTE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_label_path() -> Path:
    """Allow an explicit path so a candidate label set can be validated before
    it replaces the current one."""
    for index, argument in enumerate(sys.argv[1:], start=1):
        if argument == "--labels" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_LABEL_PATH


def main() -> None:
    label_path = resolve_label_path()
    chunk_path = Path("datasets/corpus/chunks.jsonl")
    valid_chunk_ids = load_chunk_ids(chunk_path)
    count = 0
    seen_ids = set()
    seen_queries = set()
    relevance_counts = Counter()
    category_counts = Counter()
    difficulty_counts = Counter()
    hop_type_counts = Counter()
    match_type_counts = Counter()
    domain_counts = Counter()
    relevant_chunk_reference_count = 0
    strict = "--strict" in sys.argv
    with label_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            record = json.loads(line)

            missing_fields = REQUIRED_FIELDS - set(record)
            if missing_fields:
                raise ValueError(
                    f"{label_path}:{line_number} missing fields: {sorted(missing_fields)}"
                )

            if not record["id"]:
                raise ValueError(f"{label_path}:{line_number} id must be non-empty")

            if not record["query"]:
                raise ValueError(f"{label_path}:{line_number} query must be non-empty")

            if record["split"] != "heldout":
                raise ValueError(f"{label_path}:{line_number} split must be heldout")

            if record["labels_created_blind_to_judge_outputs"] is not True:
                raise ValueError(f"{label_path}:{line_number} labels must be blind to judge outputs")
            categories = record["categories"]

            if categories.get("difficulty") not in VALID_DIFFICULTIES:
                raise ValueError(f"{label_path}:{line_number} invalid difficulty")

            if categories.get("hop_type") not in VALID_HOP_TYPES:
                raise ValueError(f"{label_path}:{line_number} invalid hop_type")

            if categories.get("match_type") not in VALID_MATCH_TYPES:
                raise ValueError(f"{label_path}:{line_number} invalid match_type")

            category_key = (
                categories["difficulty"],
                categories["hop_type"],
                categories["match_type"],
            )
            category_counts[category_key] += 1
            difficulty_counts[categories["difficulty"]] += 1
            hop_type_counts[categories["hop_type"]] += 1
            match_type_counts[categories["match_type"]] += 1
            domain_counts[categories.get("domain", "unknown")] += 1

            if not record["relevant_chunks"]:
                raise ValueError(f"{label_path}:{line_number} relevant_chunks must be non-empty")

            for chunk_label in record["relevant_chunks"]:
                chunk_id = chunk_label.get("chunk_id")
                if chunk_id not in valid_chunk_ids:
                    raise ValueError(f"{label_path}:{line_number} unknown chunk_id: {chunk_id}")
                relevance = chunk_label.get("relevance")
                if relevance not in VALID_RELEVANCE:
                    raise ValueError(f"{label_path}:{line_number} invalid relevance")
                relevance_counts[relevance] += 1
                relevant_chunk_reference_count += 1
            query_id = record["id"]
            query_text = record["query"]

            if query_id in seen_ids:
                raise ValueError(f"{label_path}:{line_number} duplicate query id: {query_id}")

            if query_text in seen_queries:
                raise ValueError(f"{label_path}:{line_number} duplicate query text: {query_text}")

            seen_ids.add(query_id)
            seen_queries.add(query_text)
            count += 1

    print(f"labeled_queries: {count}")
    print(f"dossier_target_labeled_queries: {TARGET_TOTAL_RECORDS}")
    if count < TARGET_TOTAL_RECORDS:
        print(f"status: incomplete - found {count}, target is {TARGET_TOTAL_RECORDS}")
    else:
        print("status: complete")
    print(f"relevant_chunk_references_checked: {relevant_chunk_reference_count}")
    print("unknown_relevant_chunk_ids: 0")
    print("label distribution:")
    for relevance in sorted(VALID_RELEVANCE):
        print(f"  relevance {relevance}: {relevance_counts[relevance]}")
    print("query category distribution:")
    print("  difficulty:")
    for difficulty, difficulty_count in sorted(difficulty_counts.items()):
        print(f"    {difficulty}: {difficulty_count}")
    print("  hop_type:")
    for hop_type, hop_type_count in sorted(hop_type_counts.items()):
        print(f"    {hop_type}: {hop_type_count}")
    print("  match_type:")
    for match_type, match_type_count in sorted(match_type_counts.items()):
        print(f"    {match_type}: {match_type_count}")
    print("  domain:")
    for domain, domain_count in sorted(domain_counts.items()):
        print(f"    {domain}: {domain_count}")
    print("combined category counts:")
    for category_key, category_count in sorted(category_counts.items()):
        print(f"  {category_key}: {category_count}")
    write_results_note(
        count=count,
        relevant_chunk_reference_count=relevant_chunk_reference_count,
        relevance_counts=relevance_counts,
        category_counts=category_counts,
        difficulty_counts=difficulty_counts,
        hop_type_counts=hop_type_counts,
        match_type_counts=match_type_counts,
        domain_counts=domain_counts,
    )
    print(f"results_note: {RESULT_NOTE_PATH}")
    if strict:
        validate_strict_distribution(count, category_counts)


if __name__ == "__main__":
    main()
