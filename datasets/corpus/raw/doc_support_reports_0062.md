---
doc_id: doc_support_reports_0062
title: Federated Column Lineage Fix incident review 0062
category: reports
doc_type: postmortem
procedure: Federated column lineage fix
component: the lineage tracker
error_code: ATL-5041
config_key: atlas.reports.column-lineage-fix.federated
workspace: Hollowbrook Insurance
owner_team: Core API
region: ap-northeast-3
runbook_ref: RB-REP-0062
source: synthetic
---

# Federated Column Lineage Fix incident review 0062

## Summary

On the Growth plan in ap-northeast-3, Hollowbrook Insurance reported that a renamed source column breaks reports without warning. Atlas raised ATL-5041 for 173 minutes before Core API mitigated. The fault was in the lineage tracker. Review reference RB-REP-0062.

## Impact

Hollowbrook Insurance was unable to complete Federated column lineage fix while ATL-5041 persisted. Roughly 92277 rows were delayed and `atlas_reports_column_lineage_fix_total` held above 77 percent throughout. Because the external provider must confirm the identity before the change, dependent work queued rather than failing outright, so the customer-visible symptom was latency rather than error.

## Timeline

Operations first saw `atlas_reports_column_lineage_fix_total` cross 77 percent. ATL-5041 appeared against hollowbrook-insurance once traffic exceeded 71 per minute. The page reached Core API within 173 minutes. Investigation focused on the lineage tracker after a renamed source column breaks reports without warning was reproduced with `atlas reports column-lineage-fix --mode federated --dry-run`.

## Root Cause

lineage records display names rather than stable column identifiers. The condition had existed in the lineage tracker for some time and became visible only when Hollowbrook Insurance crossed 71 calls per minute. The 47 second abort masked it earlier by failing requests before the fault surfaced.

## Remediation

The team applied the standing fix: track lineage on stable column identifiers. This was executed with `atlas reports column-lineage-fix --mode federated --workspace hollowbrook-insurance --commit` at a batch size of 793, backing off 617 milliseconds between attempts, under 2 approval(s) against `atlas.reports.column-lineage-fix.federated`.

## Verification

Recovery was confirmed when renames upstream leave reports intact. `atlas_reports_column_lineage_fix_total` returned below 77 percent and ATL-5041 stopped appearing for hollowbrook-insurance. Because the external provider must confirm the identity before the change, the team also confirmed the lineage tracker had reconciled before closing.

## Prevention

To keep lineage records display names rather than stable column identifiers from recurring, Core API added monitoring on the lineage tracker that alerts before `atlas_reports_column_lineage_fix_total` reaches 77 percent. Retention for the diagnostic trail was set to 58 days in warm storage.

## Follow-Up

Re-check hollowbrook-insurance after 19 days. Confirm the 71 per minute ceiling and the 92277 row cap still suit Hollowbrook Insurance on the Growth plan, and that renames upstream leave reports intact remains true.
