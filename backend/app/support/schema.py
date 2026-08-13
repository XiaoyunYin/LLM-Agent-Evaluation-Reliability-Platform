"""The support-ticket domain: entities, enums, and a deterministic fixture.

Kept deliberately small. The point of P3 is verifying *effects*, so the schema
needs exactly enough structure to make interesting mutations possible — priority,
assignment, status, comments, escalation — and nothing more. Every extra table is
another surface the verifier has to normalize.

**Determinism is a hard requirement.** The fixture is generated from a fixed seed
with no clock reads and no random IDs, so two machines produce byte-identical
databases. A benchmark whose initial state drifts cannot support paired
comparison across runs.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from pathlib import Path

# Bumped whenever the schema or the fixture generation changes. Recorded on every
# run, because a task's expected diff is only meaningful against a known world.
SCHEMA_VERSION = "support_schema_v2"
FIXTURE_VERSION = "support_fixture_v2"
FIXTURE_SEED = 20260813

# Enums are closed sets. Tools validate against them, so an agent cannot invent a
# status and have it silently persist.
PRIORITIES = ("low", "normal", "high", "urgent")
STATUSES = ("open", "in_progress", "waiting_customer", "escalated", "resolved", "closed")
TEAMS = ("billing", "technical", "accounts", "shipping")
TIERS = ("free", "pro", "enterprise")

DDL = """
CREATE TABLE teams (
    team_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    queue       TEXT NOT NULL
);

CREATE TABLE agents (
    agent_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    team_id     TEXT NOT NULL REFERENCES teams(team_id),
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    tier        TEXT NOT NULL,
    region      TEXT NOT NULL
);

CREATE TABLE tickets (
    ticket_id   TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    priority    TEXT NOT NULL,
    status      TEXT NOT NULL,
    team_id     TEXT REFERENCES teams(team_id),
    assignee_id TEXT REFERENCES agents(agent_id),
    escalated   INTEGER NOT NULL DEFAULT 0,
    created_seq INTEGER NOT NULL
);

CREATE TABLE comments (
    comment_id  TEXT PRIMARY KEY,
    ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
    author      TEXT NOT NULL,
    body        TEXT NOT NULL,
    reason_code TEXT,
    created_seq INTEGER NOT NULL
);

CREATE TABLE policies (
    policy_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    topic       TEXT NOT NULL,
    -- Structured applicability predicate, as JSON. Prose interpretation is not an
    -- applicability test: a task whose applicable policy can only be decided by
    -- reading English cannot be QA'd for uniqueness, so an ambiguous task would
    -- reach the agent and present as a confusing failure.
    applies_to  TEXT NOT NULL
);
"""

# Policy corpus. Deliberately specific: each policy states a rule an agent can only
# follow by retrieving it, so `search_policy` usage is measurable rather than
# guessable from the ticket text alone.
POLICIES = [
    ("POL-001", "Enterprise escalation window", "technical",
     "Enterprise-tier customers reporting an outage must be escalated within one "
     "business hour and assigned to the technical team. Set the escalated flag to "
     "true (this is the escalated field, not the status field) and set priority "
     "to urgent. Leave status unchanged.",
     {"tier": ["enterprise"], "signal": "outage"}),
    ("POL-002", "Billing dispute handling", "billing",
     "Billing disputes are assigned to the billing team at normal priority. Do not "
     "escalate a billing dispute unless the disputed amount exceeds 5000.",
     {"signal": "billing_dispute"}),
    ("POL-003", "Refund approval threshold", "billing",
     "Refunds above 500 require a comment with reason code REFUND_APPROVAL before "
     "the ticket may be resolved.",
     {"signal": "refund"}),
    ("POL-004", "Shipping delay policy", "shipping",
     "Shipping delays are handled by the shipping team at high priority when the "
     "delay exceeds 48 hours.",
     {"signal": "shipping_delay"}),
    ("POL-005", "Account lockout procedure", "accounts",
     "Account lockouts are assigned to the accounts team at high priority and "
     "require a comment with reason code IDENTITY_CHECK.",
     {"signal": "lockout"}),
    ("POL-006", "Free-tier performance issues", "technical",
     "Free-tier customers reporting a performance issue are handled at low "
     "priority by the technical team.",
     {"tier": ["free"], "signal": "performance"}),
    ("POL-007", "Security report handling", "technical",
     "Security reports must have the escalated flag set to true (this is the "
     "escalated field, not the status field), priority set to urgent, and be "
     "assigned to the technical team. Leave status unchanged. They require a "
     "comment with reason code SECURITY_TRIAGE.",
     {"signal": "security"}),
    ("POL-008", "Waiting on customer", "technical",
     "A ticket blocked on customer information moves to status waiting_customer "
     "and keeps its current priority.",
     {"signal": "blocked_on_customer"}),
    ("POL-009", "Duplicate tickets", "accounts",
     "Duplicate tickets are closed with a comment carrying reason code DUPLICATE. "
     "Do not reassign a duplicate.",
     {"signal": "duplicate"}),
    ("POL-010", "Enterprise billing priority", "billing",
     "Enterprise-tier billing issues are handled at high priority by the billing "
     "team, even when the amount is small.",
     {"tier": ["enterprise"], "signal": "billing_general"}),
    ("POL-011", "Pro-tier outage handling", "technical",
     "Pro-tier customers reporting an outage are assigned to the technical team at "
     "high priority. Do NOT set the escalated flag for pro-tier outages.",
     {"tier": ["pro"], "signal": "outage"}),
    ("POL-012", "Free-tier outage handling", "technical",
     "Free-tier customers reporting an outage are assigned to the technical team "
     "at normal priority. Do NOT set the escalated flag for free-tier outages.",
     {"tier": ["free"], "signal": "outage"}),
    ("POL-013", "Pro-tier performance issues", "technical",
     "Pro-tier customers reporting a performance issue are handled at normal "
     "priority by the technical team.",
     {"tier": ["pro"], "signal": "performance"}),
    ("POL-014", "Enterprise performance issues", "technical",
     "Enterprise-tier customers reporting a performance issue are handled at high "
     "priority by the technical team.",
     {"tier": ["enterprise"], "signal": "performance"}),
]

_TEAMS = [
    ("TEAM-billing", "Billing", "billing"),
    ("TEAM-technical", "Technical", "technical"),
    ("TEAM-accounts", "Accounts", "accounts"),
    ("TEAM-shipping", "Shipping", "shipping"),
]

_AGENTS = [
    ("AG-001", "Ada", "TEAM-technical"),
    ("AG-002", "Blair", "TEAM-technical"),
    ("AG-003", "Chen", "TEAM-billing"),
    ("AG-004", "Dev", "TEAM-billing"),
    ("AG-005", "Eze", "TEAM-accounts"),
    ("AG-006", "Faye", "TEAM-shipping"),
]

# (subject, topic, body, signal). The signal is the machine-readable fact a policy
# predicate matches on, so applicability never depends on parsing prose.
_SUBJECTS = [
    ("Cannot log in after password reset", "accounts",
     "Account lockout after three failed attempts.", "lockout"),
    ("Charged twice for March invoice", "billing",
     "Duplicate charge of 240 on the March invoice.", "billing_dispute"),
    ("Order has not shipped", "shipping",
     "Order placed 60 hours ago and still not dispatched.", "shipping_delay"),
    ("API returns 500 on every request", "technical",
     "Complete outage of the reporting API.", "outage"),
    ("Refund request for annual plan", "billing",
     "Requesting a refund of 900 for an unused annual plan.", "refund"),
    ("Possible data exposure", "technical",
     "Security report: another customer's data visible in export.", "security"),
    ("Need invoice copy", "billing",
     "Requesting a copy of the February invoice.", "billing_general"),
    ("Shipment delayed by one day", "shipping",
     "Delivery is about 20 hours late.", "shipping_delay"),
    ("Cannot add team member", "accounts",
     "Seat limit reached when adding a user.", "lockout"),
    ("Dashboard loads slowly", "technical",
     "Reports take about 30 seconds to load.", "performance"),
]


def applicable_policies(tier: str, signal: str) -> list[str]:
    """Policy ids whose predicate matches. The single source of applicability.

    Used by task generation AND, independently, by QA, which asserts that an
    intended single-policy task has exactly one match. Applicability decided by
    reading prose cannot be checked that way, so an ambiguous task would reach the
    agent and present as a confusing failure rather than a caught defect.
    """
    matches = []
    for policy_id, _title, _topic, _body, applies in POLICIES:
        if "tier" in applies and tier not in applies["tier"]:
            continue
        if "signal" in applies and applies["signal"] != signal:
            continue
        matches.append(policy_id)
    return matches


def signal_for_subject(subject: str) -> str | None:
    for entry_subject, _topic, _body, signal in _SUBJECTS:
        if entry_subject == subject:
            return signal
    return None


def _seeded_rows(count: int) -> tuple[list, list]:
    """Generate customers and tickets deterministically.

    `random.Random(FIXTURE_SEED)` with no clock reads means the same rows on every
    machine. `created_seq` replaces a timestamp for the same reason: an ordering
    that is real but not wall-clock dependent.
    """
    rng = random.Random(FIXTURE_SEED)
    customers = []
    for index in range(1, 21):
        customers.append(
            (
                f"CUST-{index:03d}",
                f"Customer {index:03d}",
                rng.choice(TIERS),
                rng.choice(("emea", "amer", "apac")),
            )
        )

    tickets = []
    for index in range(1, count + 1):
        subject, topic, body, _signal = _SUBJECTS[(index - 1) % len(_SUBJECTS)]
        customer = customers[(index - 1) % len(customers)]
        tickets.append(
            (
                f"TKT-{index:04d}",
                customer[0],
                subject,
                body,
                rng.choice(PRIORITIES),
                "open" if index % 4 else "in_progress",
                None,
                None,
                0,
                index,
            )
        )
    return customers, tickets


def build_fixture(path: Path, ticket_count: int = 60) -> str:
    """Create the seeded database and return its content hash.

    The hash pins the initial world. A task's expected diff means nothing without
    it, so it is recorded alongside every frozen task.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.executemany("INSERT INTO teams VALUES (?, ?, ?)", _TEAMS)
    connection.executemany(
        "INSERT INTO agents (agent_id, name, team_id, active) VALUES (?, ?, ?, 1)",
        _AGENTS,
    )

    customers, tickets = _seeded_rows(ticket_count)
    connection.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)
    connection.executemany(
        "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tickets
    )
    connection.executemany(
        "INSERT INTO policies (policy_id, title, topic, body, applies_to) "
        "VALUES (?, ?, ?, ?, ?)",
        [(pid, title, topic, body, json.dumps(applies, sort_keys=True))
         for pid, title, topic, body, applies in POLICIES],
    )
    connection.commit()
    connection.close()

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
