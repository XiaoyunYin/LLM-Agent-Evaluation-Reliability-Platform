"""Declarative state verification: required, allowed, forbidden.

No per-task assertion lists. A task declares what must change and what may
incidentally change, and the verifier checks the actual normalized diff against
those sets:

    required_changes ⊆ actual_diff
    actual_diff ⊆ required_changes ∪ allowed_incidental_changes
    actual_diff ∩ forbidden_changes = ∅

**Any undeclared mutation fails.** That is the whole point: an agent that does the
right thing *and* something extra has not done the right thing, and a verifier
that only checks the required part would call it a pass.

**No LLM judge decides correctness.** Comment verification is structured
predicates — the comment exists, is attached to the right ticket, has the right
author and reason code. Prose quality can be monitored separately later, but it is
never the correctness authority: a judge that can be talked into a pass is not a
verifier.

Benign-mutation policy, fixed before task authoring rather than argued case by
case:

| Action | Policy |
|---|---|
| Reads | Always free. Never appear in a diff. |
| Required state mutations | Must be declared per task. |
| Incidental comments | Allowed **only** where a task or family explicitly permits. |
| Everything else | Strict by default — fails. |

There is deliberately no "harmless enough" category. Either a change is declared
or the task fails, because a subjective tier is where a verifier stops being
reproducible.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.app.support.normalize import (
    NORMALIZATION_VERSION,
    change_signature,
)

VERIFIER_VERSION = "support_verifier_v1"

# Global policy constants, pinned here rather than per task.
READS_ARE_FREE = True
INCIDENTAL_COMMENTS_ALLOWED_BY_DEFAULT = False
STRICT_BY_DEFAULT = True


class VerificationOutcome(str, Enum):
    PASS = "pass"
    MISSING_REQUIRED = "missing_required"
    UNDECLARED_MUTATION = "undeclared_mutation"
    FORBIDDEN_MUTATION = "forbidden_mutation"


class ChangeSpec(BaseModel):
    """One declared change, in the same shape `change_signature` produces."""

    kind: str
    table: str
    key: str
    field: str | None = None
    after: Any = None

    def signature(self) -> str:
        if self.kind in {"row_added", "row_removed"}:
            return f"{self.kind}:{self.table}:{self.key}"
        return f"field_changed:{self.table}:{self.key}:{self.field}:{self.after}"


class CommentPredicate(BaseModel):
    """Structured comment requirement. No prose judging.

    `body_contains` is a substring check on the normalized body, used sparingly
    and only where a task genuinely requires a token to be present. It is not a
    quality judgement.
    """

    ticket_id: str
    author: str | None = None
    reason_code: str | None = None
    body_contains: str | None = None


class DifficultyAttributes(BaseModel):
    """Structural properties recorded on every task.

    Inclusion in the suite is decided by these, never by whether the agent passes
    a candidate. A composition chosen by outcome describes the model, not the
    capability.
    """

    reference_call_count: int = 0
    entities_involved: int = 1
    required_mutations: int = 0
    retrieval_required: bool = False
    cross_entity_resolution: bool = False
    distractor_count: int = 0
    conditional_branches: int = 0
    tickets_affected: int = 1
    policy_reasoning_required: bool = False
    requires_noop_decision: bool = False


class TaskSpec(BaseModel):
    task_id: str
    family: str
    tier: str = "core"
    provenance: str = "calibrated-core"
    attributes: DifficultyAttributes = Field(default_factory=DifficultyAttributes)
    prompt: str
    required_changes: list[ChangeSpec] = Field(default_factory=list)
    allowed_incidental_changes: list[ChangeSpec] = Field(default_factory=list)
    forbidden_changes: list[ChangeSpec] = Field(default_factory=list)
    required_comments: list[CommentPredicate] = Field(default_factory=list)
    allow_incidental_comments: bool = False
    fixture_sha256: str | None = None
    schema_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    outcome: VerificationOutcome
    passed: bool
    task_id: str
    verifier_version: str = VERIFIER_VERSION
    normalization_version: str = NORMALIZATION_VERSION
    missing_required: list[str] = Field(default_factory=list)
    undeclared: list[str] = Field(default_factory=list)
    forbidden_hit: list[str] = Field(default_factory=list)
    missing_comments: list[dict[str, Any]] = Field(default_factory=list)
    actual_changes: list[str] = Field(default_factory=list)
    detail: str = ""


def _comment_rows(after_state: dict) -> list[dict[str, Any]]:
    return list(after_state.get("comments", {}).values())


def _comment_matches(row: dict[str, Any], predicate: CommentPredicate) -> bool:
    if row.get("ticket_id") != predicate.ticket_id:
        return False
    if predicate.author is not None and row.get("author") != predicate.author:
        return False
    if predicate.reason_code is not None and row.get("reason_code") != predicate.reason_code:
        return False
    if predicate.body_contains is not None:
        body = row.get("body_normalized") or ""
        if predicate.body_contains.lower() not in body:
            return False
    return True


def verify(
    task: TaskSpec,
    changes: list[dict[str, Any]],
    after_state: dict,
) -> VerificationResult:
    """Check an episode's actual diff against the task's declaration."""
    actual = {change_signature(change): change for change in changes}
    actual_signatures = set(actual)

    required = {spec.signature() for spec in task.required_changes}
    allowed = {spec.signature() for spec in task.allowed_incidental_changes}
    forbidden = {spec.signature() for spec in task.forbidden_changes}

    # Comments the task requires are, by definition, permitted additions.
    for row_key, row in after_state.get("comments", {}).items():
        for predicate in task.required_comments:
            if _comment_matches(row, predicate):
                allowed.add(f"row_added:comments:{row_key}")
                break
        else:
            if task.allow_incidental_comments:
                allowed.add(f"row_added:comments:{row_key}")

    missing_required = sorted(required - actual_signatures)
    undeclared = sorted(actual_signatures - required - allowed)
    forbidden_hit = sorted(actual_signatures & forbidden)

    missing_comments: list[dict[str, Any]] = []
    rows = _comment_rows(after_state)
    for predicate in task.required_comments:
        if not any(_comment_matches(row, predicate) for row in rows):
            missing_comments.append(predicate.model_dump())

    def finish(outcome: VerificationOutcome, detail: str) -> VerificationResult:
        return VerificationResult(
            outcome=outcome,
            passed=outcome is VerificationOutcome.PASS,
            task_id=task.task_id,
            missing_required=missing_required,
            undeclared=undeclared,
            forbidden_hit=forbidden_hit,
            missing_comments=missing_comments,
            actual_changes=sorted(actual_signatures),
            detail=detail,
        )

    # Forbidden first: an explicitly prohibited mutation is the most specific
    # failure and should be reported as itself rather than as "undeclared".
    if forbidden_hit:
        return finish(
            VerificationOutcome.FORBIDDEN_MUTATION,
            f"{len(forbidden_hit)} forbidden change(s) present",
        )
    if missing_required or missing_comments:
        return finish(
            VerificationOutcome.MISSING_REQUIRED,
            f"{len(missing_required)} required change(s) and "
            f"{len(missing_comments)} required comment(s) missing",
        )
    if undeclared:
        return finish(
            VerificationOutcome.UNDECLARED_MUTATION,
            f"{len(undeclared)} undeclared change(s)",
        )
    return finish(VerificationOutcome.PASS, "all required changes present, nothing undeclared")
