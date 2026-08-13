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

from backend.app.support.schema import applicable_policies, signal_for_subject
from backend.app.support.verifier import (
    ChangeSpec,
    CommentPredicate,
    DifficultyAttributes,
    TaskSpec,
)

TASK_FAMILY_VERSION = "support_tasks_v5"

CORE_FAMILIES = (
    "simple_update",
    "lookup_update",
    "policy_update",
    "multi_field",
    "multi_ticket",
    "conditional_escalation",
)

# Structurally harder families, added by the one-time composition/difficulty
# expansion pass. Each must satisfy the structural attributes pre-committed in
# docs/P3_SUITE_COMPOSITION.md.
HARD_FAMILIES = (
    "chained_resolution",
    "policy_selection",
    "distractor_resolution",
    "multi_ticket_conditional",
    "noop_plus_mutation",
)

FAMILIES = CORE_FAMILIES + HARD_FAMILIES

# Policy actions, keyed by policy id. The verifier derives required changes from
# the SAME predicate the agent must apply, so a task cannot encode an expectation
# the policy does not actually state.
POLICY_ACTIONS: dict[str, dict[str, Any]] = {
    # The mandated end state for each policy, and the ONLY source of a
    # policy-driven task's required changes. Hand-listing them per family is how
    # SUP-noop-003/005 became unpassable: the policy says "assigned to the billing
    # team AT NORMAL PRIORITY", the task required only the team, and an agent that
    # followed the policy exactly was failed for an undeclared mutation.
    "POL-002": {"priority": "normal", "team_id": "TEAM-billing"},
    "POL-001": {"priority": "urgent", "escalated": 1, "team_id": "TEAM-technical"},
    "POL-011": {"priority": "high", "team_id": "TEAM-technical"},
    "POL-012": {"priority": "normal", "team_id": "TEAM-technical"},
    "POL-014": {"priority": "high", "team_id": "TEAM-technical"},
    "POL-013": {"priority": "normal", "team_id": "TEAM-technical"},
    "POL-006": {"priority": "low", "team_id": "TEAM-technical"},
}


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

    tasks.extend(_hard_families(tickets, customers, spec))
    return tasks


def _hard_families(tickets, customers, spec) -> list[dict[str, Any]]:
    """Generate the structurally harder families.

    Selection is by structural attribute only. No candidate is included or
    excluded because of how an agent performs on it.
    """
    hard: list[dict[str, Any]] = []
    by_customer: dict[str, list[dict[str, Any]]] = {}
    for ticket in tickets:
        by_customer.setdefault(ticket["customer_id"], []).append(ticket)

    def attrs(**kwargs) -> DifficultyAttributes:
        return DifficultyAttributes(**kwargs)

    # -- chained_resolution: customer name -> ticket -> team ------------------
    index = 0
    for customer_id, group in sorted(by_customer.items()):
        if len(hard) >= 10:
            break
        # Both required fields must be real changes. Filtering only one of them
        # is how SUP-chain-002 shipped a no-op priority requirement, caught by the
        # independent QA check rather than by this generator.
        candidates = [
            t for t in group
            if "log in" in t["subject"].lower()
            and _needs_change(t, "team_id", "TEAM-accounts")
            and _needs_change(t, "priority", "high")
        ]
        if not candidates:
            continue
        ticket = candidates[0]
        customer = customers[customer_id]
        index += 1
        hard.append({
            "spec": spec(
                task_id=f"SUP-chain-{index:03d}", family="chained_resolution",
                tier="hard", provenance="hard-calibration-derived",
                attributes=attrs(reference_call_count=4, entities_involved=3,
                                 required_mutations=2, cross_entity_resolution=True,
                                 tickets_affected=1),
                prompt=(
                    f"{customer['name']} cannot log in. Find their account-lockout "
                    f"ticket, assign it to the team that handles account lockouts, "
                    f"and set its priority to high. Look up the team identifier "
                    f"rather than guessing it."
                ),
                required_changes=[
                    _field_change("tickets", ticket["ticket_id"], "team_id", "TEAM-accounts"),
                    _field_change("tickets", ticket["ticket_id"], "priority", "high"),
                ],
            ),
            "reference": [
                ("search_tickets", {"customer_name": customer["name"]}),
                ("list_reference_data", {}),
                ("assign_ticket", {"ticket_id": ticket["ticket_id"], "team_id": "TEAM-accounts"}),
                ("update_ticket", {"ticket_id": ticket["ticket_id"], "priority": "high"}),
            ],
        })

    # -- policy_selection: tier decides which of several policies applies -----
    outages = [t for t in tickets if signal_for_subject(t["subject"]) == "outage"]
    count = 0
    for ticket in outages:
        if count >= 10:
            break
        tier = customers[ticket["customer_id"]]["tier"]
        matching = applicable_policies(tier, "outage")
        if len(matching) != 1:
            continue  # ambiguous by predicate: never generated
        policy_id = matching[0]
        actions = POLICY_ACTIONS[policy_id]
        required = [
            _field_change("tickets", ticket["ticket_id"], field, value)
            for field, value in actions.items()
            if _needs_change(ticket, field, value)
        ]
        if not required:
            continue
        forbidden = []
        if "escalated" not in actions:
            forbidden.append(_field_change("tickets", ticket["ticket_id"], "escalated", 1))
        count += 1
        hard.append({
            "spec": spec(
                task_id=f"SUP-polsel-{count:03d}", family="policy_selection",
                tier="hard", provenance="hard-calibration-derived",
                attributes=attrs(reference_call_count=4, entities_involved=2,
                                 required_mutations=len(required),
                                 retrieval_required=True, policy_reasoning_required=True,
                                 conditional_branches=1, cross_entity_resolution=True),
                prompt=(
                    f"Ticket {ticket['ticket_id']} reports an outage. Different "
                    f"outage policies apply to different customer tiers. Determine "
                    f"this customer's tier, find the outage policy for that tier, "
                    f"and apply exactly what it says."
                ),
                required_changes=required,
                forbidden_changes=forbidden,
                metadata={"expected_policy": policy_id, "customer_tier": tier,
                          "policy_ids": {ticket["ticket_id"]: policy_id}},
            ),
            "reference": [
                ("get_ticket", {"ticket_id": ticket["ticket_id"]}),
                ("search_policy", {"query": "outage tier handling"}),
                ("list_reference_data", {}),
                ("update_ticket", {"ticket_id": ticket["ticket_id"],
                                   **{k: (True if k == "escalated" else v)
                                      for k, v in actions.items() if k != "team_id"}}),
                ("assign_ticket", {"ticket_id": ticket["ticket_id"],
                                   "team_id": actions["team_id"]}),
            ],
        })

    # -- distractor_resolution: several plausible tickets, one correct --------
    shipping = [t for t in tickets if signal_for_subject(t["subject"]) == "shipping_delay"]
    for position in range(min(10, max(0, len(shipping) - 2))):
        target = shipping[position]
        distractors = [t for t in shipping if t["ticket_id"] != target["ticket_id"]][:4]
        if len(distractors) < 3 or not _needs_change(target, "priority", "high"):
            continue
        customer = customers[target["customer_id"]]
        # A "distractor" owned by the target customer is not a distractor, it is an
        # ambiguity: the prompt says "the ticket belonging to <customer>" and two
        # tickets answer to that, one of them forbidden. The fixture fix makes this
        # impossible; asserting it here keeps it impossible.
        distractors = [d for d in distractors if d["customer_id"] != target["customer_id"]]
        if len(distractors) < 3:
            continue
        hard.append({
            "spec": spec(
                task_id=f"SUP-distract-{position + 1:03d}", family="distractor_resolution",
                metadata={"selector_signal": "shipping_delay",
                          "selector_customer": target["customer_id"]},
                tier="hard", provenance="hard-calibration-derived",
                attributes=attrs(reference_call_count=3, entities_involved=2,
                                 required_mutations=1, distractor_count=len(distractors),
                                 cross_entity_resolution=True),
                # The prompt selects on the SIGNAL ("an order has not shipped"),
                # not the topic ("shipping delays"). The topic spans two signals -
                # shipping_delay and shipping_minor - and a customer holds both, so
                # a topic-level selector named two tickets and the task was
                # unresolvable by reading it. The fixture guarantees uniqueness per
                # (customer, signal), so the prompt has to select at that grain.
                prompt=(
                    f"Several customers report that an order has not shipped. Only "
                    f"the ticket belonging to {customer['name']} is confirmed over "
                    f"48 hours. Set that one ticket to high priority. Leave the "
                    f"other not-shipped tickets alone."
                ),
                required_changes=[
                    _field_change("tickets", target["ticket_id"], "priority", "high")
                ],
                forbidden_changes=[
                    _field_change("tickets", d["ticket_id"], "priority", "high")
                    for d in distractors
                ],
            ),
            "reference": [
                ("search_tickets", {"query": "ship"}),
                ("search_tickets", {"customer_name": customer["name"]}),
                ("update_ticket", {"ticket_id": target["ticket_id"], "priority": "high"}),
            ],
        })

    # -- noop_plus_mutation: decide NOT to change one thing, change another ---
    pairs = [t for t in tickets if signal_for_subject(t["subject"]) == "billing_dispute"]
    for position, ticket in enumerate(pairs[:8], start=1):
        # Derived from the policy, never hand-listed - see POLICY_ACTIONS.
        actions = POLICY_ACTIONS["POL-002"]
        noop_required = [
            _field_change("tickets", ticket["ticket_id"], field, value)
            for field, value in actions.items()
            if _needs_change(ticket, field, value)
        ]
        if not noop_required:
            continue
        noop_reference = [("search_policy", {"query": "billing dispute"})]
        if any(c.field == "team_id" for c in noop_required):
            noop_reference.append(("list_reference_data", {}))
            noop_reference.append(("assign_ticket", {"ticket_id": ticket["ticket_id"],
                                                     "team_id": actions["team_id"]}))
        if any(c.field == "priority" for c in noop_required):
            noop_reference.append(("update_ticket", {"ticket_id": ticket["ticket_id"],
                                                     "priority": actions["priority"]}))
        hard.append({
            "spec": spec(
                task_id=f"SUP-noop-{position:03d}", family="noop_plus_mutation",
                tier="hard", provenance="hard-calibration-derived",
                attributes=attrs(reference_call_count=len(noop_reference), entities_involved=2,
                                 required_mutations=len(noop_required), retrieval_required=True,
                                 requires_noop_decision=True, policy_reasoning_required=True),
                prompt=(
                    f"Ticket {ticket['ticket_id']} is a billing dispute for 240. "
                    f"Look up the billing dispute policy and apply it. Note the "
                    f"policy's condition on escalation carefully."
                ),
                metadata={"policy_ids": {ticket["ticket_id"]: "POL-002"}},
                required_changes=noop_required,
                forbidden_changes=[
                    _field_change("tickets", ticket["ticket_id"], "escalated", 1)
                ],
            ),
            "reference": noop_reference,
        })

    # -- multi_ticket_conditional: several tickets, per-ticket branch ---------
    # Both tier-conditional signals, not just performance. The family's structure
    # is "several tickets, per-ticket branch on the customer's tier"; outage is the
    # other signal with tier-specific policies (POL-001/011/012), so it belongs
    # here. Disjoint chunks of one signal capped the family at 4 tasks - a
    # substrate limit, not a design choice.
    conditional_pool = [
        (signal, [t for t in tickets if signal_for_subject(t["subject"]) == signal])
        for signal in ("performance", "outage")
    ]
    groups = [
        (signal, pool[i:i + 3])
        for signal, pool in conditional_pool
        for i in range(0, max(0, len(pool) - 2), 3)
    ]
    for position, (signal, group) in enumerate(groups[:9], start=1):
        if len(group) < 3:
            continue
        query = "performance tier" if signal == "performance" else "outage tier"
        required, reference, policy_ids = [], [("search_policy", {"query": query})], []
        ok = True
        for ticket in group:
            tier = customers[ticket["customer_id"]]["tier"]
            matching = applicable_policies(tier, signal)
            if len(matching) != 1:
                ok = False
                break
            # Every field the policy mandates, not just priority. Requiring only
            # priority while telling the agent to apply the policy failed
            # SUP-mtcond-006/007 10/10: POL-001 mandates escalation for enterprise
            # outages, the agent escalated correctly, and the verifier called it an
            # undeclared mutation. Same defect class as the noop family.
            actions = POLICY_ACTIONS[matching[0]]
            policy_ids.append(matching[0])
            update: dict[str, Any] = {}
            for field, value in actions.items():
                if not _needs_change(ticket, field, value):
                    continue
                required.append(_field_change("tickets", ticket["ticket_id"], field, value))
                if field == "team_id":
                    reference.append(("assign_ticket", {"ticket_id": ticket["ticket_id"],
                                                        "team_id": value}))
                else:
                    update[field] = bool(value) if field == "escalated" else value
            if update:
                reference.append(("update_ticket", {"ticket_id": ticket["ticket_id"], **update}))
        if not ok or not required:
            continue
        hard.append({
            "spec": spec(
                task_id=f"SUP-mtcond-{position:03d}", family="multi_ticket_conditional",
                tier="hard", provenance="hard-calibration-derived",
                attributes=attrs(reference_call_count=len(reference), entities_involved=4,
                                 required_mutations=len(required), retrieval_required=True,
                                 policy_reasoning_required=True, conditional_branches=len(group),
                                 tickets_affected=len(group), cross_entity_resolution=True),
                metadata={"policy_ids": {t["ticket_id"]: pid
                                         for t, pid in zip(group, policy_ids)}},
                prompt=(
                    ("These tickets all report slow performance: "
                     if signal == "performance" else
                     "These tickets all report an outage: ")
                    + ", ".join(t["ticket_id"] for t in group)
                    + ". The correct handling depends on each customer's tier. Look "
                    f"up the {signal} policies and apply the applicable policy to "
                    "each ticket. Change nothing the policies do not require."
                ),
                required_changes=required,
            ),
            "reference": reference,
        })

    return hard
