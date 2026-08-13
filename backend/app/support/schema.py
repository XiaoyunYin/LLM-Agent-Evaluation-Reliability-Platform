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
import random
import sqlite3
from pathlib import Path

# Bumped whenever the schema or the fixture generation changes. Recorded on every
# run, because a task's expected diff is only meaningful against a known world.
SCHEMA_VERSION = "support_schema_v1"
FIXTURE_VERSION = "support_fixture_v1"
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
    topic       TEXT NOT NULL
);
"""

# Policy corpus. Deliberately specific: each policy states a rule an agent can only
# follow by retrieving it, so `search_policy` usage is measurable rather than
# guessable from the ticket text alone.
POLICIES = [
    ("POL-001", "Enterprise escalation window", "technical",
     "Enterprise-tier customers reporting an outage must be escalated within one "
     "business hour and assigned to the technical team. Set priority to urgent."),
    ("POL-002", "Billing dispute handling", "billing",
     "Billing disputes are assigned to the billing team at normal priority. Do not "
     "escalate a billing dispute unless the disputed amount exceeds 5000."),
    ("POL-003", "Refund approval threshold", "billing",
     "Refunds above 500 require a comment with reason code REFUND_APPROVAL before "
     "the ticket may be resolved."),
    ("POL-004", "Shipping delay policy", "shipping",
     "Shipping delays under 48 hours are handled at low priority by the shipping "
     "team. Delays over 48 hours move to high priority."),
    ("POL-005", "Account lockout procedure", "accounts",
     "Account lockouts are assigned to the accounts team at high priority and "
     "require a comment with reason code IDENTITY_CHECK."),
    ("POL-006", "Free-tier response targets", "technical",
     "Free-tier customers are handled at low priority unless the issue is a "
     "security report, which is always urgent."),
    ("POL-007", "Security report handling", "technical",
     "Security reports are escalated immediately, set to urgent, assigned to the "
     "technical team, and require a comment with reason code SECURITY_TRIAGE."),
    ("POL-008", "Waiting on customer", "technical",
     "A ticket blocked on customer information moves to status waiting_customer "
     "and keeps its current priority."),
    ("POL-009", "Duplicate tickets", "accounts",
     "Duplicate tickets are closed with a comment carrying reason code DUPLICATE. "
     "Do not reassign a duplicate."),
    ("POL-010", "Enterprise billing priority", "billing",
     "Enterprise-tier billing issues are handled at high priority by the billing "
     "team, even when the amount is small."),
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

_SUBJECTS = [
    ("Cannot log in after password reset", "accounts", "Account lockout after three failed attempts."),
    ("Charged twice for March invoice", "billing", "Duplicate charge of 240 on the March invoice."),
    ("Order has not shipped", "shipping", "Order placed 60 hours ago and still not dispatched."),
    ("API returns 500 on every request", "technical", "Complete outage of the reporting API."),
    ("Refund request for annual plan", "billing", "Requesting a refund of 900 for an unused annual plan."),
    ("Possible data exposure", "technical", "Security report: another customer's data visible in export."),
    ("Need invoice copy", "billing", "Requesting a copy of the February invoice."),
    ("Shipment delayed by one day", "shipping", "Delivery is about 20 hours late."),
    ("Cannot add team member", "accounts", "Seat limit reached when adding a user."),
    ("Dashboard loads slowly", "technical", "Reports take about 30 seconds to load."),
]


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
        subject, topic, body = _SUBJECTS[(index - 1) % len(_SUBJECTS)]
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
        "INSERT INTO policies (policy_id, title, topic, body) VALUES (?, ?, ?, ?)",
        POLICIES,
    )
    connection.commit()
    connection.close()

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
