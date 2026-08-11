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
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.corpus_vocabulary import (  # noqa: E402
    QUALIFIER_VOCAB,
    TOPIC_VOCAB,
)

OUTPUT_DIR = Path("datasets/corpus/raw")
DOCS_PER_DOMAIN = 110

# Document types carry different section structures so two documents differ in
# shape as well as in subject. A single shared skeleton is what made corpus v0.2
# embed to near-identical vectors.
DOC_TYPES = ("runbook", "postmortem", "reference", "faq")

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

        # Subject-matter vocabulary. This is the axis that lets an embedding
        # model tell two documents apart.
        component, symptom, cause, fix, signal = TOPIC_VOCAB[topic]
        self.component = component
        self.symptom = symptom
        self.cause = cause
        self.fix = fix
        self.signal = signal
        self.actor, self.constraint = QUALIFIER_VOCAB[qualifier]

        self.doc_type = DOC_TYPES[global_index % len(DOC_TYPES)]

    @property
    def title(self) -> str:
        noun = {
            "runbook": "runbook",
            "postmortem": "incident review",
            "reference": "reference",
            "faq": "questions and answers",
        }[self.doc_type]
        return f"{self.procedure.title()} {noun} {self.number:04d}"


def body_runbook(f: DocumentFacts) -> str:
    return f"""## Overview

{f.runbook_ref} describes {f.procedure} for {f.workspace}, where {f.symptom}. The work is \
performed by {f.actor}, and {f.constraint}. The affected component is {f.component}. This \
document applies only when Atlas raises {f.error_code}; other {f.domain} faults are covered \
elsewhere. {f.owner_team} owns the procedure in {f.region}.

## Symptoms

Reporters describe the same thing: {f.symptom}. Atlas raises {f.error_code} against the \
{f.workspace_slug} workspace and `{f.metric}` climbs past {f.threshold_percent} percent. \
Because {f.constraint}, the symptom can look intermittent when {f.component} is under load. \
Requests beyond {f.rate_limit} per minute make it reproducible.

## Root Cause

The underlying fault is that {f.cause}. This is a property of {f.component} rather than of \
any single workspace, so {f.workspace} is affected only because it exercises that path. The \
{f.timeout_seconds} second abort is a consequence, not the cause; raising it hides \
{f.error_code} without repairing {f.component}.

## Resolution

To repair the fault, {f.fix}. Run `{f.cli} --workspace {f.workspace_slug} --commit` with a \
batch size of {f.batch_size}, retrying with a {f.backoff_ms} millisecond backoff. Because \
{f.constraint}, do not exceed {f.max_rows} rows in one invocation. Editing \
`{f.config_key}` requires {f.approval_count} approval(s).

## Verification

The repair has landed when {f.signal}. Confirm with `{f.cli} --workspace \
{f.workspace_slug} --verify`, which should report `{f.config_key}` active and no \
{f.error_code} in the last {f.timeout_seconds} seconds. `{f.metric}` should settle below \
{f.threshold_percent} percent within {f.sla_minutes} minutes.

## Limits

{f.workspace} is capped at {f.rate_limit} {f.procedure_slug} calls per minute on the \
{f.plan_tier} plan in {f.region}. Results persist in {f.storage_class} storage for \
{f.retention_days} days, and Atlas warns {f.warning_days} days before that window closes. \
Payloads above {f.max_rows} rows are refused.

## Escalation

Escalate to {f.owner_team} citing {f.runbook_ref} if {f.error_code} recurs after two \
attempts, or if {f.symptom} persists once {f.signal}. Their acknowledgement target is \
{f.sla_minutes} minutes. Include the value of `{f.config_key}` and the observed \
`{f.metric}` rate.

## Audit

Every {f.procedure} action against {f.workspace} writes an entry tagged {f.runbook_ref}, \
retained {f.retention_days} days in {f.storage_class} storage, recording the actor and both \
values of `{f.config_key}`. Because {f.constraint}, the entry also records whether \
{f.component} was reconciled.

## Follow-Up

Once {f.error_code} clears, confirm downstream {f.domain} jobs reading `{f.config_key}` \
still run. Work depending on {f.component} may lag {f.backoff_ms} milliseconds per batch of \
{f.batch_size}. Re-check {f.workspace_slug} after {f.warning_days} days.
"""


def body_postmortem(f: DocumentFacts) -> str:
    return f"""## Summary

On the {f.plan_tier} plan in {f.region}, {f.workspace} reported that {f.symptom}. Atlas \
raised {f.error_code} for {f.sla_minutes} minutes before {f.owner_team} mitigated. The \
fault was in {f.component}. Review reference {f.runbook_ref}.

## Impact

{f.workspace} was unable to complete {f.procedure} while {f.error_code} persisted. Roughly \
{f.max_rows} rows were delayed and `{f.metric}` held above {f.threshold_percent} percent \
throughout. Because {f.constraint}, dependent work queued rather than failing outright, so \
the customer-visible symptom was latency rather than error.

## Timeline

Operations first saw `{f.metric}` cross {f.threshold_percent} percent. {f.error_code} \
appeared against {f.workspace_slug} once traffic exceeded {f.rate_limit} per minute. The \
page reached {f.owner_team} within {f.sla_minutes} minutes. Investigation focused on \
{f.component} after {f.symptom} was reproduced with `{f.cli} --dry-run`.

## Root Cause

{f.cause}. The condition had existed in {f.component} for some time and became visible only \
when {f.workspace} crossed {f.rate_limit} calls per minute. The {f.timeout_seconds} second \
abort masked it earlier by failing requests before the fault surfaced.

## Remediation

The team applied the standing fix: {f.fix}. This was executed with `{f.cli} --workspace \
{f.workspace_slug} --commit` at a batch size of {f.batch_size}, backing off {f.backoff_ms} \
milliseconds between attempts, under {f.approval_count} approval(s) against \
`{f.config_key}`.

## Verification

Recovery was confirmed when {f.signal}. `{f.metric}` returned below \
{f.threshold_percent} percent and {f.error_code} stopped appearing for {f.workspace_slug}. \
Because {f.constraint}, the team also confirmed {f.component} had reconciled before closing.

## Prevention

To keep {f.cause} from recurring, {f.owner_team} added monitoring on {f.component} that \
alerts before `{f.metric}` reaches {f.threshold_percent} percent. Retention for the \
diagnostic trail was set to {f.retention_days} days in {f.storage_class} storage.

## Follow-Up

Re-check {f.workspace_slug} after {f.warning_days} days. Confirm the {f.rate_limit} per \
minute ceiling and the {f.max_rows} row cap still suit {f.workspace} on the {f.plan_tier} \
plan, and that {f.signal} remains true.
"""


def body_reference(f: DocumentFacts) -> str:
    return f"""## Overview

This reference documents {f.procedure} as implemented by {f.component} in Atlas Metrics. It \
is written for {f.actor}. The controlling setting is `{f.config_key}` and the associated \
failure is {f.error_code}. See {f.runbook_ref} for the operational procedure.

## Behavior

{f.component} performs {f.procedure} whenever the workspace configuration changes. Because \
{f.constraint}, the operation is ordered rather than concurrent. A correct run ends when \
{f.signal}. An incorrect run is visible as {f.symptom}.

## Configuration

`{f.config_key}` accepts the batch size, currently {f.batch_size}, and the retry backoff, \
currently {f.backoff_ms} milliseconds. Editing it requires {f.approval_count} approval(s). \
The prior value is retained {f.retention_days} days in {f.storage_class} storage. Apply \
changes with `{f.cli} --workspace {f.workspace_slug} --commit`.

## Limits

On the {f.plan_tier} plan in {f.region}, {f.workspace} may issue {f.rate_limit} \
{f.procedure_slug} calls per minute. A single invocation accepts at most {f.max_rows} rows \
and aborts after {f.timeout_seconds} seconds. Atlas warns {f.warning_days} days before the \
{f.retention_days} day window closes.

## Errors

{f.error_code} is raised when {f.symptom}. The documented cause is that {f.cause}. It is \
distinct from a plain permissions fault: a permissions fault leaves `{f.metric}` flat, \
while {f.error_code} drives it above {f.threshold_percent} percent. It is also distinct \
from exceeding the {f.max_rows} row cap.

## Resolution

The supported repair is to {f.fix}. {f.owner_team} owns {f.component} and acknowledges \
escalations against {f.error_code} within {f.sla_minutes} minutes. Cite {f.runbook_ref} and \
include the current value of `{f.config_key}`.

## Verification

Run `{f.cli} --workspace {f.workspace_slug} --verify`. The command confirms {f.signal} and \
reports no {f.error_code} within the last {f.timeout_seconds} seconds. `{f.metric}` should \
sit below {f.threshold_percent} percent within {f.sla_minutes} minutes.

## Related

Behavior of {f.component} interacts with downstream {f.domain} work that reads \
`{f.config_key}`. Dependent jobs may lag {f.backoff_ms} milliseconds per batch of \
{f.batch_size}. Audit entries are tagged {f.runbook_ref}.
"""


def body_faq(f: DocumentFacts) -> str:
    return f"""## What does {f.error_code} mean?

It means {f.symptom}. Atlas raises it against {f.workspace_slug} when {f.component} cannot \
complete {f.procedure}. The operational procedure is {f.runbook_ref}, owned by \
{f.owner_team} in {f.region}.

## Why does this happen?

The cause is that {f.cause}. It is a property of {f.component}, so {f.workspace} sees it \
only because it exercises that path. Because {f.constraint}, it may appear intermittent \
until traffic passes {f.rate_limit} calls per minute.

## How do I fix it?

{f.fix}. In practice that means running `{f.cli} --workspace {f.workspace_slug} --commit` \
with a batch size of {f.batch_size} and a {f.backoff_ms} millisecond backoff. Editing \
`{f.config_key}` first requires {f.approval_count} approval(s).

## How do I know the fix worked?

You know it worked when {f.signal}. Running `{f.cli} --workspace {f.workspace_slug} \
--verify` reports `{f.config_key}` active with no {f.error_code} in the last \
{f.timeout_seconds} seconds, and `{f.metric}` falls below {f.threshold_percent} percent \
within {f.sla_minutes} minutes.

## Is this a permissions problem?

No. A permissions fault leaves `{f.metric}` flat, while {f.error_code} drives it above \
{f.threshold_percent} percent. A second common misread is blaming the {f.rate_limit} per \
minute ceiling when the limit actually reached was the {f.max_rows} row cap.

## What are the limits?

{f.workspace} may issue {f.rate_limit} {f.procedure_slug} calls per minute on the \
{f.plan_tier} plan. One invocation accepts {f.max_rows} rows and aborts after \
{f.timeout_seconds} seconds. Results persist {f.retention_days} days in {f.storage_class} \
storage.

## Who do I escalate to?

{f.owner_team} owns {f.component}. They acknowledge escalations against {f.error_code} \
within {f.sla_minutes} minutes on the {f.plan_tier} plan. Cite {f.runbook_ref} and include \
the observed `{f.metric}` rate.

## What should I check afterwards?

Confirm downstream {f.domain} work reading `{f.config_key}` still runs. It may lag \
{f.backoff_ms} milliseconds per batch of {f.batch_size}. Re-check {f.workspace_slug} after \
{f.warning_days} days, before the {f.retention_days} day window closes.
"""


BODY_BUILDERS = {
    "runbook": body_runbook,
    "postmortem": body_postmortem,
    "reference": body_reference,
    "faq": body_faq,
}


def build_document(facts: DocumentFacts) -> str:
    f = facts
    front_matter = f"""---
doc_id: {f.doc_id}
title: {f.title}
category: {f.domain}
doc_type: {f.doc_type}
procedure: {f.procedure}
component: {f.component}
error_code: {f.error_code}
config_key: {f.config_key}
workspace: {f.workspace}
owner_team: {f.owner_team}
region: {f.region}
runbook_ref: {f.runbook_ref}
source: synthetic
---

# {f.title}

"""
    return front_matter + BODY_BUILDERS[f.doc_type](f)


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
