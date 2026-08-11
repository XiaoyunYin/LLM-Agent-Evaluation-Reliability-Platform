---
doc_id: doc_support_troubleshooting_0016
title: Scheduled Connection Pool Reset incident review 0016
category: troubleshooting
doc_type: postmortem
procedure: Scheduled connection pool reset
component: the connection pool
error_code: ATL-5105
config_key: atlas.troubleshooting.connection-pool-reset.scheduled
workspace: Dunmore Ceramics
owner_team: Ingest Pipeline
region: ap-northeast-3
runbook_ref: RB-TRO-0016
source: synthetic
---

# Scheduled Connection Pool Reset incident review 0016

## Summary

On the Growth plan in ap-northeast-3, Dunmore Ceramics reported that requests queue while the pool reports idle capacity. Atlas raised ATL-5105 for 315 minutes before Ingest Pipeline mitigated. The fault was in the connection pool. Review reference RB-TRO-0016.

## Impact

Dunmore Ceramics was unable to complete Scheduled connection pool reset while ATL-5105 persisted. Roughly 98485 rows were delayed and `atlas_troubleshooting_connection_pool_reset_total` held above 85 percent throughout. Because the change must be idempotent because the job may run twice, dependent work queued rather than failing outright, so the customer-visible symptom was latency rather than error.

## Timeline

Operations first saw `atlas_troubleshooting_connection_pool_reset_total` cross 85 percent. ATL-5105 appeared against dunmore-ceramics once traffic exceeded 775 per minute. The page reached Ingest Pipeline within 315 minutes. Investigation focused on the connection pool after requests queue while the pool reports idle capacity was reproduced with `atlas troubleshooting connection-pool-reset --mode scheduled --dry-run`.

## Root Cause

the pool counts broken connections as available. The condition had existed in the connection pool for some time and became visible only when Dunmore Ceramics crossed 775 calls per minute. The 210 second abort masked it earlier by failing requests before the fault surfaced.

## Remediation

The team applied the standing fix: health-check connections before returning them to callers. This was executed with `atlas troubleshooting connection-pool-reset --mode scheduled --workspace dunmore-ceramics --commit` at a batch size of 365, backing off 2985 milliseconds between attempts, under 2 approval(s) against `atlas.troubleshooting.connection-pool-reset.scheduled`.

## Verification

Recovery was confirmed when available count matches usable connections. `atlas_troubleshooting_connection_pool_reset_total` returned below 85 percent and ATL-5105 stopped appearing for dunmore-ceramics. Because the change must be idempotent because the job may run twice, the team also confirmed the connection pool had reconciled before closing.

## Prevention

To keep the pool counts broken connections as available from recurring, Ingest Pipeline added monitoring on the connection pool that alerts before `atlas_troubleshooting_connection_pool_reset_total` reaches 85 percent. Retention for the diagnostic trail was set to 82 days in warm storage.

## Follow-Up

Re-check dunmore-ceramics after 8 days. Confirm the 775 per minute ceiling and the 98485 row cap still suit Dunmore Ceramics on the Growth plan, and that available count matches usable connections remains true.
