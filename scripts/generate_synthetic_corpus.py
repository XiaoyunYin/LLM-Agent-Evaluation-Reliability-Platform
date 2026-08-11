"""Generate the synthetic Atlas Metrics support corpus.

Every document describes one *specific* procedure and carries facts that appear
in no other document: a unique error code, config key, CLI invocation, owning
team, and a set of numeric thresholds. That uniqueness is the point.

The previous generator interpolated only {category} and {number} into a fixed
template, so 9,900 chunks collapsed into 2,262 distinct texts with duplicate
clusters up to 330 members. Because every labeled chunk sat inside such a
cluster, no retriever could prefer the labeled chunk ID over its identical
siblings, and recall@10 was capped at a theoretical 0.0846 regardless of
retrieval quality. See scripts/analyze_corpus_duplication.py.

Generation is deterministic: all per-document values derive from the document's
global index, so re-running reproduces the corpus byte for byte.

Usage:
    python scripts/generate_synthetic_corpus.py
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

OUTPUT_DIR = Path("datasets/corpus/raw")
DOCS_PER_DOMAIN = 110

# 11 topics x 10 qualifiers = 110 unique procedure names per domain.
DOMAIN_TOPICS: dict[str, list[str]] = {
    "accounts": [
        "seat reassignment", "owner transfer", "identity merge", "email rebinding",
        "workspace suspension", "trial conversion", "account reactivation",
        "profile deduplication", "login domain claim", "session revocation",
        "org hierarchy split",
    ],
    "api": [
        "token rotation", "webhook replay", "schema migration", "cursor pagination",
        "idempotency recovery", "rate ceiling raise", "payload compaction",
        "version deprecation", "signature verification", "batch submission",
        "partial response repair",
    ],
    "billing": [
        "invoice reissue", "proration correction", "tax profile update",
        "seat true-up", "credit application", "dunning retry", "currency migration",
        "usage reconciliation", "refund authorization", "contract amendment",
        "overage forgiveness",
    ],
    "dashboards": [
        "widget restoration", "filter inheritance", "layout migration",
        "drilldown repair", "shared view handoff", "refresh scheduling",
        "panel duplication", "legend remapping", "threshold recoloring",
        "snapshot pinning", "cross-filter unlock",
    ],
    "exports": [
        "column remapping", "delivery retry", "archive expiry", "encoding repair",
        "row limit raise", "destination rebinding", "compression switch",
        "manifest regeneration", "partial export resume", "header normalization",
        "checksum reconciliation",
    ],
    "incidents": [
        "severity reclassification", "timeline reconstruction", "pager rerouting",
        "status page correction", "postmortem linking", "blast radius scoping",
        "customer notification", "mitigation rollback", "duplicate merge",
        "escalation handoff", "impact recalculation",
    ],
    "integrations": [
        "connector reauthorization", "field mapping repair", "sync backfill",
        "credential rotation", "endpoint migration", "conflict resolution",
        "throttle negotiation", "sandbox promotion", "payload transformation",
        "orphan record cleanup", "bidirectional sync repair",
    ],
    "permissions": [
        "role scoping", "group inheritance repair", "policy attachment",
        "privilege revocation", "delegation expiry", "least-privilege audit",
        "custom role migration", "resource boundary fix", "approval chain update",
        "service account restriction", "cross-workspace grant",
    ],
    "reports": [
        "schedule correction", "recipient pruning", "template versioning",
        "aggregation repair", "timezone realignment", "subscription transfer",
        "column lineage fix", "delivery window shift", "snapshot comparison",
        "metric redefinition", "rollup reconciliation",
    ],
    "troubleshooting": [
        "cache invalidation", "job queue drain", "stale replica repair",
        "clock skew correction", "connection pool reset", "index rebuild",
        "memory pressure relief", "deadlock resolution", "retry storm damping",
        "config drift reconciliation", "cold start mitigation",
    ],
}

QUALIFIERS = [
    "delegated", "scheduled", "bulk", "regional", "legacy",
    "federated", "sandboxed", "throttled", "audited", "cascading",
]

WORKSPACE_HEADS = [
    "Northwind", "Brightpath", "Cobalt", "Harborview", "Kestrel", "Lumen",
    "Meridian", "Oakfield", "Perihelion", "Quarry", "Redstone", "Silverlake",
    "Tidewater", "Umbra", "Vanguard", "Westmark", "Ashgrove", "Blackpine",
    "Clearwater", "Dunmore", "Eastgate", "Fernhill", "Glacier", "Hollowbrook",
    "Ironwood", "Junegrass", "Kingsley", "Larkspur", "Moorland", "Nightjar",
    "Overton", "Pinecrest", "Ravenswood", "Stonebridge",
]

WORKSPACE_TAILS = [
    "Analytics", "Systems", "Labs", "Group", "Collective", "Partners",
    "Industries", "Networks", "Digital", "Research", "Logistics", "Health",
    "Robotics", "Foundry", "Dynamics", "Interactive", "Media", "Capital",
    "Freight", "Grid", "Biotech", "Studios", "Retail", "Energy", "Aviation",
    "Maritime", "Agritech", "Insurance", "Telecom", "Ceramics", "Optics",
    "Textiles", "Brewing",
]

OWNER_TEAMS = [
    "Platform Reliability", "Identity Services", "Revenue Engineering",
    "Data Delivery", "Ingest Pipeline", "Customer Trust", "Core API",
    "Workspace Experience", "Observability", "Billing Infrastructure",
    "Integrations Guild",
]

REGIONS = [
    "us-west-2", "us-east-1", "eu-central-1", "eu-west-2",
    "ap-southeast-1", "ap-northeast-3", "sa-east-1", "ca-central-1",
]

PLAN_TIERS = ["Starter", "Growth", "Business", "Enterprise"]

STORAGE_CLASSES = ["hot", "warm", "cold", "archival"]


def slugify(value: str) -> str:
    return value.replace(" ", "-").replace("_", "-").lower()


class DocumentFacts:
    """Every field here is unique to one document, or a facet used for filtering."""

    def __init__(self, domain: str, domain_position: int, global_index: int):
        topics = DOMAIN_TOPICS[domain]
        topic = topics[domain_position % len(topics)]
        qualifier = QUALIFIERS[domain_position // len(topics)]

        self.domain = domain
        self.number = domain_position + 1
        self.doc_id = f"doc_support_{domain}_{self.number:04d}"

        self.topic = topic
        self.qualifier = qualifier
        self.procedure = f"{qualifier.title()} {topic}"
        self.procedure_slug = f"{slugify(qualifier)}-{slugify(topic)}"

        # Unique identifiers. Global index guarantees no collision across domains.
        self.error_code = f"ATL-{4100 + global_index}"
        self.config_key = f"atlas.{domain}.{slugify(topic)}.{slugify(qualifier)}"
        self.cli = f"atlas {domain} {slugify(topic)} --mode {slugify(qualifier)}"
        self.metric = f"atlas_{domain}_{slugify(topic).replace('-', '_')}_total"
        self.runbook_ref = f"RB-{domain[:3].upper()}-{self.number:04d}"

        head = WORKSPACE_HEADS[global_index % len(WORKSPACE_HEADS)]
        tail = WORKSPACE_TAILS[global_index // len(WORKSPACE_HEADS) % len(WORKSPACE_TAILS)]
        self.workspace = f"{head} {tail}"
        self.workspace_slug = f"{head.lower()}-{tail.lower()}"

        self.owner_team = OWNER_TEAMS[global_index % len(OWNER_TEAMS)]
        self.region = REGIONS[global_index % len(REGIONS)]
        self.plan_tier = PLAN_TIERS[global_index % len(PLAN_TIERS)]
        self.storage_class = STORAGE_CLASSES[global_index % len(STORAGE_CLASSES)]

        # Numeric facts. Different multipliers keep these from correlating.
        self.retention_days = 7 + (global_index * 3) % 84
        self.rate_limit = 60 + (global_index * 11) % 940
        self.timeout_seconds = 15 + (global_index * 7) % 285
        self.sla_minutes = 15 + (global_index * 13) % 345
        self.threshold_percent = 55 + (global_index * 17) % 45
        self.max_rows = 1_000 + (global_index * 97) % 99_000
        self.batch_size = 50 + (global_index * 23) % 950
        self.backoff_ms = 100 + (global_index * 37) % 4_900
        self.approval_count = 1 + global_index % 4
        self.warning_days = 3 + global_index % 25

    @property
    def title(self) -> str:
        return f"{self.procedure.title()} runbook {self.number:04d}"


def build_document(facts: DocumentFacts) -> str:
    f = facts
    return f"""---
doc_id: {f.doc_id}
title: {f.title}
category: {f.domain}
procedure: {f.procedure}
error_code: {f.error_code}
config_key: {f.config_key}
workspace: {f.workspace}
owner_team: {f.owner_team}
region: {f.region}
runbook_ref: {f.runbook_ref}
source: synthetic
---

# {f.title}

## Overview

Runbook {f.runbook_ref} covers the {f.procedure} procedure for the {f.workspace} \
workspace in Atlas Metrics, hosted in {f.region} on the {f.plan_tier} plan. It applies \
only when the platform emits error {f.error_code}; other {f.domain} faults use a \
different runbook. Ownership sits with the {f.owner_team} team, who accept escalations \
against {f.error_code} within {f.sla_minutes} minutes.

## Symptoms

The customer sees error {f.error_code} with the message "{f.procedure} blocked for \
workspace {f.workspace_slug}". The `{f.metric}` counter rises while the affected \
{f.domain} operation stalls. Requests exceeding {f.rate_limit} calls per minute against \
{f.workspace_slug} amplify the failure, and the operation aborts once it has waited \
{f.timeout_seconds} seconds.

## Prerequisites

Confirm the requester holds an administrator grant on {f.workspace}, then collect \
{f.approval_count} approval(s) before editing `{f.config_key}`. Changes to \
`{f.config_key}` are irreversible after {f.retention_days} days because the prior value \
leaves {f.storage_class} storage on that schedule. Record {f.runbook_ref} and \
{f.error_code} in the case notes.

## Diagnostic Steps

Run `{f.cli} --workspace {f.workspace_slug} --dry-run` and compare the reported value of \
`{f.config_key}` with the expected baseline. If `{f.metric}` exceeds \
{f.threshold_percent} percent of its ceiling for the {f.workspace_slug} workspace, the \
{f.procedure} path is saturated rather than misconfigured, and error {f.error_code} is a \
symptom instead of the cause.

## Resolution

Apply `{f.cli} --workspace {f.workspace_slug} --commit` with a batch size of \
{f.batch_size}. The command retries with a {f.backoff_ms} millisecond backoff and gives \
up after {f.timeout_seconds} seconds. Processing more than {f.max_rows} rows in one \
invocation for {f.workspace} is unsupported and re-raises {f.error_code}. Split larger \
jobs into batches of {f.batch_size}.

## Limits and Quotas

The {f.plan_tier} plan caps {f.workspace} at {f.rate_limit} {f.procedure_slug} calls per \
minute in {f.region}. Results persist in {f.storage_class} storage for \
{f.retention_days} days. Exports tied to {f.runbook_ref} refuse payloads above \
{f.max_rows} rows. Atlas warns {f.warning_days} days before the {f.retention_days} day \
window closes on {f.workspace_slug}.

## Verification

After the change, `{f.cli} --workspace {f.workspace_slug} --verify` should report \
`{f.config_key}` as active with no occurrences of {f.error_code} in the last \
{f.timeout_seconds} seconds. Ask the customer to confirm from {f.workspace} directly. \
The `{f.metric}` counter should settle below {f.threshold_percent} percent within \
{f.sla_minutes} minutes.

## Escalation

Escalate to {f.owner_team} if {f.error_code} recurs on {f.workspace_slug} after two \
attempts, citing {f.runbook_ref}. Their acknowledgement target is {f.sla_minutes} \
minutes for the {f.plan_tier} plan in {f.region}. Include the value of \
`{f.config_key}`, the observed `{f.metric}` rate, and whether the {f.rate_limit} per \
minute ceiling was reached.

## Common Misdiagnoses

Error {f.error_code} is often confused with a plain permissions fault on \
{f.workspace_slug}, but a permissions fault leaves `{f.metric}` flat while {f.error_code} \
drives it above {f.threshold_percent} percent. A second misread is blaming the \
{f.rate_limit} per minute ceiling when the true limit reached was the {f.max_rows} row \
cap. Check `{f.config_key}` before assuming either.

## Audit and Logging

Every {f.procedure} action against {f.workspace} writes an audit entry tagged \
{f.runbook_ref} and retained for {f.retention_days} days in {f.storage_class} storage. \
The entry records the actor, the prior and new values of `{f.config_key}`, and whether \
{f.error_code} was observed. Never log raw credentials for {f.workspace_slug}; redact \
them before attaching evidence to the case.

## Related Follow-Up

Once {f.error_code} clears on {f.workspace}, confirm downstream {f.domain} jobs that \
read `{f.config_key}` still run. Scheduled work reading {f.procedure_slug} output may \
lag by up to {f.backoff_ms} milliseconds per batch of {f.batch_size}. Re-check \
{f.workspace_slug} after {f.warning_days} days, before the {f.retention_days} day \
{f.storage_class} retention window expires.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing documents first so stale files cannot survive.",
    )
    args = parser.parse_args()

    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    global_index = 0
    for domain in sorted(DOMAIN_TOPICS):
        expected = len(DOMAIN_TOPICS[domain]) * len(QUALIFIERS)
        if expected < DOCS_PER_DOMAIN:
            raise ValueError(
                f"{domain} can only form {expected} unique procedures, "
                f"need {DOCS_PER_DOMAIN}"
            )
        for position in range(DOCS_PER_DOMAIN):
            facts = DocumentFacts(domain, position, global_index)
            (args.output_dir / f"{facts.doc_id}.md").write_text(
                build_document(facts), encoding="utf-8"
            )
            total += 1
            global_index += 1

    print(f"Generated {total} documents in {args.output_dir}")
    print(f"Domains: {len(DOMAIN_TOPICS)}  Documents per domain: {DOCS_PER_DOMAIN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
