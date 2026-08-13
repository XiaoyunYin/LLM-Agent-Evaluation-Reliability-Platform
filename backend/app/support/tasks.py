"""Parameterized task families and their reference action sequences.

Tasks are **generated from templates against pinned fixture state**, not authored
one by one. Fifty hand-written tasks drift: two authors express the same rule
differently, and a verifier bug in one is invisible in the others. A family is
written once, QA'd once, and instantiated many times.

Every task carries a **reference action sequence** — the tool calls a correct agent
would make. That is what makes verifier QA possible: replay the reference and the
task must PASS; mutate the reference and it must FAIL. A task whose own reference
does not pass is a broken task, not a hard one.

Families, in increasing difficulty:

| Family | Shape |
|---|---|
| `simple_update` | one field on a named ticket |
| `lookup_update` | find the ticket, then update it |
| `policy_update` | retrieve a policy, apply what it says |
| `multi_field` | several fields on one ticket, all required |
| `multi_ticket` | the same operation across several tickets |
| `conditional_escalation` | branch on customer tier / ticket content |
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backend.app.support.verifier import ChangeSpec, CommentPredicate, TaskSpec

TASK_FAMILY_VERSION = "support_tasks_v1"

FAMILIES = (
    "simple_update",
    "lookup_update",
    "policy_update",
    "multi_field",
    "multi_ticket",
    "conditional_escalation",
)


def _field_change(table: str, key: str, field: str, after: Any) -> ChangeSpec:
    return ChangeSpec(kind="field_changed", table=table, key=key, field=field, after=after)


def _needs_change(ticket: dict[str, Any], field: str, target: Any) -> bool:
    """True when setting `field` to `target` would actually change the row.

    A required change the fixture already satisfies produces no diff, so the
    verifier can never see it and the task is unpassable no matter what the agent
    does. Verifier QA caught exactly this: two account-lockout tickets were
    already at priority `high`, and their reference sequences failed.

    Filtering at generation is the fix; `qa_support_verifier.py` also asserts it
    independently, because a generator and its own check sharing an assumption is
    how this class of bug survives.
    """
    current = ticket.get(field)
    if field == "escalated":
        return int(current or 0) != int(target)
    return current != target


def _tickets(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(r) for r in connection.execute("SELECT * FROM tickets ORDER BY ticket_id")]


def build_tasks(fixture_path: Path, fixture_sha: str, schema_version: str) -> list[dict[str, Any]]:
    """Instantiate every family against the pinned fixture.

    Returns `{"spec": TaskSpec, "reference": [(tool, arguments), ...]}` so the
    QA harness can replay a known-good solution for each task.
    """
    connection = sqlite3.connect(fixture_path)
    tickets = _tickets(connection)
    by_id = {t["ticket_id"]: t for t in tickets}
    customers = {
        r["customer_id"]: dict(r)
        for r in connection.execute("SELECT * FROM customers")
    }
    connection.close()

    def spec(**kwargs) -> TaskSpec:
        return TaskSpec(
            fixture_sha256=fixture_sha, schema_version=schema_version, **kwargs
        )

    tasks: list[dict[str, Any]] = []

    # ---- simple_update: one field, ticket named in the prompt --------------
    targets = [t for t in tickets if _needs_change(t, "priority", "urgent")][:8]
    for index, ticket in enumerate(targets, start=1):
        ticket_id = ticket["ticket_id"]
        tasks.append({
            "spec": spec(
                task_id=f"SUP-simple-{index:03d}",
                family="simple_update",
                prompt=(
                    f"Ticket {ticket_id} has been re-triaged. Set its priority to "
                    f"urgent. Change nothing else."
                ),
                required_changes=[_field_change("tickets", ticket_id, "priority", "urgent")],
            ),
            "reference": [("update_ticket", {"ticket_id": ticket_id, "priority": "urgent"})],
        })

    # ---- lookup_update: the ticket must be found first ---------------------
    lookup_targets = [
        t for t in tickets if _needs_change(t, "status", "in_progress")
    ][:8]
    for index, ticket in enumerate(lookup_targets, start=1):
        ticket_id = ticket["ticket_id"]
        customer = customers[ticket["customer_id"]]
        tasks.append({
            "spec": spec(
                task_id=f"SUP-lookup-{index:03d}",
                family="lookup_update",
                prompt=(
                    f"Customer {customer['name']} reported an issue with the subject "
                    f"\"{ticket['subject']}\". Find that customer's ticket with that "
                    f"subject and move it to status in_progress. Change nothing else."
                ),
                required_changes=[_field_change("tickets", ticket_id, "status", "in_progress")],
            ),
            "reference": [
                ("search_tickets", {"customer_name": customer["name"]}),
                ("update_ticket", {"ticket_id": ticket_id, "status": "in_progress"}),
            ],
        })

    # ---- policy_update: the rule is only in the policy corpus --------------
    security = [
        t for t in tickets
        if "data exposure" in t["subject"].lower()
        and _needs_change(t, "priority", "urgent")
        and _needs_change(t, "escalated", 1)
        and _needs_change(t, "team_id", "TEAM-technical")
    ][:4]
    for index, ticket in enumerate(security, start=1):
        ticket_id = ticket["ticket_id"]
        tasks.append({
            "spec": spec(
                task_id=f"SUP-policy-{index:03d}",
                family="policy_update",
                prompt=(
                    f"Ticket {ticket_id} is a security report. Look up the security "
                    f"report handling policy and apply it exactly."
                ),
                required_changes=[
                    _field_change("tickets", ticket_id, "priority", "urgent"),
                    _field_change("tickets", ticket_id, "escalated", 1),
                    _field_change("tickets", ticket_id, "team_id", "TEAM-technical"),
                ],
                required_comments=[
                    CommentPredicate(ticket_id=ticket_id, reason_code="SECURITY_TRIAGE")
                ],
            ),
            "reference": [
                ("search_policy", {"query": "security report handling"}),
                ("update_ticket", {"ticket_id": ticket_id, "priority": "urgent", "escalated": True}),
                ("list_reference_data", {}),
                ("assign_ticket", {"ticket_id": ticket_id, "team_id": "TEAM-technical"}),
                ("add_comment", {"ticket_id": ticket_id, "body": "Security triage started.",
                                 "reason_code": "SECURITY_TRIAGE"}),
            ],
        })

    # ---- multi_field: several required changes on one ticket --------------
    lockouts = [
        t for t in tickets
        if "log in" in t["subject"].lower()
        and _needs_change(t, "priority", "high")
        and _needs_change(t, "team_id", "TEAM-accounts")
    ][:6]
    for index, ticket in enumerate(lockouts, start=1):
        ticket_id = ticket["ticket_id"]
        tasks.append({
            "spec": spec(
                task_id=f"SUP-multi-{index:03d}",
                family="multi_field",
                prompt=(
                    f"Ticket {ticket_id} is an account lockout. Set priority to high, "
                    f"assign it to the accounts team, and add a comment with reason "
                    f"code IDENTITY_CHECK."
                ),
                required_changes=[
                    _field_change("tickets", ticket_id, "priority", "high"),
                    _field_change("tickets", ticket_id, "team_id", "TEAM-accounts"),
                ],
                required_comments=[
                    CommentPredicate(ticket_id=ticket_id, reason_code="IDENTITY_CHECK")
                ],
            ),
            "reference": [
                ("update_ticket", {"ticket_id": ticket_id, "priority": "high"}),
                ("assign_ticket", {"ticket_id": ticket_id, "team_id": "TEAM-accounts"}),
                ("add_comment", {"ticket_id": ticket_id, "body": "Identity check required.",
                                 "reason_code": "IDENTITY_CHECK"}),
            ],
        })

    # ---- multi_ticket: same operation across several tickets --------------
    shipping = [
        t for t in tickets
        if "ship" in t["subject"].lower()
        and _needs_change(t, "team_id", "TEAM-shipping")
    ][:9]
    for index in range(0, min(len(shipping), 9) - 2, 3):
        group = shipping[index:index + 3]
        if len(group) < 3:
            break
        ids = [t["ticket_id"] for t in group]
        tasks.append({
            "spec": spec(
                task_id=f"SUP-multiticket-{index // 3 + 1:03d}",
                family="multi_ticket",
                prompt=(
                    "The shipping queue is being rebalanced. Assign tickets "
                    + ", ".join(ids)
                    + " to the shipping team. Change nothing else."
                ),
                required_changes=[
                    _field_change("tickets", tid, "team_id", "TEAM-shipping") for tid in ids
                ],
            ),
            "reference": [
                ("assign_ticket", {"ticket_id": tid, "team_id": "TEAM-shipping"}) for tid in ids
            ],
        })

    # ---- conditional_escalation: branch on customer tier ------------------
    outages = [
        t for t in tickets
        if "API returns 500" in t["subject"]
        and _needs_change(t, "team_id", "TEAM-technical")
    ][:6]
    for index, ticket in enumerate(outages, start=1):
        ticket_id = ticket["ticket_id"]
        tier = customers[ticket["customer_id"]]["tier"]
        if tier == "enterprise":
            required = [
                _field_change("tickets", ticket_id, "team_id", "TEAM-technical"),
            ]
            if _needs_change(ticket, "priority", "urgent"):
                required.append(_field_change("tickets", ticket_id, "priority", "urgent"))
            if _needs_change(ticket, "escalated", 1):
                required.append(_field_change("tickets", ticket_id, "escalated", 1))
            reference = [
                ("get_ticket", {"ticket_id": ticket_id}),
                ("search_policy", {"query": "enterprise escalation outage"}),
                ("update_ticket", {"ticket_id": ticket_id, "priority": "urgent", "escalated": True}),
                ("assign_ticket", {"ticket_id": ticket_id, "team_id": "TEAM-technical"}),
            ]
        else:
            # Non-enterprise: assign to technical, do NOT escalate. The forbidden
            # change is what makes the branch measurable - an agent that escalates
            # everything passes the enterprise cases and fails here.
            required = [_field_change("tickets", ticket_id, "team_id", "TEAM-technical")]
            reference = [
                ("get_ticket", {"ticket_id": ticket_id}),
                ("search_policy", {"query": "enterprise escalation outage"}),
                ("assign_ticket", {"ticket_id": ticket_id, "team_id": "TEAM-technical"}),
            ]

        tasks.append({
            "spec": spec(
                task_id=f"SUP-cond-{index:03d}",
                family="conditional_escalation",
                prompt=(
                    f"Ticket {ticket_id} reports an outage. Check the customer's tier "
                    f"and apply the enterprise escalation policy only if it applies. "
                    f"Assign the ticket to the technical team either way."
                ),
                required_changes=required,
                forbidden_changes=(
                    []
                    if tier == "enterprise"
                    else [_field_change("tickets", ticket_id, "escalated", 1)]
                ),
                metadata={"customer_tier": tier},
            ),
            "reference": reference,
        })

    return tasks
