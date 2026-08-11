---
doc_id: doc_support_troubleshooting_0052
title: Legacy Deadlock Resolution incident review 0052
category: troubleshooting
doc_type: postmortem
procedure: Legacy deadlock resolution
component: the lock ordering policy
error_code: ATL-5141
config_key: atlas.troubleshooting.deadlock-resolution.legacy
workspace: Fernhill Optics
owner_team: Workspace Experience
region: us-east-1
runbook_ref: RB-TRO-0052
source: synthetic
---

# Legacy Deadlock Resolution incident review 0052

## Summary

On the Growth plan in us-east-1, Fernhill Optics reported that concurrent operations block one another indefinitely. Atlas raised ATL-5141 for 93 minutes before Workspace Experience mitigated. The fault was in the lock ordering policy. Review reference RB-TRO-0052.

## Impact

Fernhill Optics was unable to complete Legacy deadlock resolution while ATL-5141 persisted. Roughly 2977 rows were delayed and `atlas_troubleshooting_deadlock_resolution_total` held above 67 percent throughout. Because the change must be translated into the older format first, dependent work queued rather than failing outright, so the customer-visible symptom was latency rather than error.

## Timeline

Operations first saw `atlas_troubleshooting_deadlock_resolution_total` cross 67 percent. ATL-5141 appeared against fernhill-optics once traffic exceeded 231 per minute. The page reached Workspace Experience within 93 minutes. Investigation focused on the lock ordering policy after concurrent operations block one another indefinitely was reproduced with `atlas troubleshooting deadlock-resolution --mode legacy --dry-run`.

## Root Cause

two paths acquire the same locks in opposite order. The condition had existed in the lock ordering policy for some time and became visible only when Fernhill Optics crossed 231 calls per minute. The 177 second abort masked it earlier by failing requests before the fault surfaced.

## Remediation

The team applied the standing fix: impose a global lock acquisition order on both paths. This was executed with `atlas troubleshooting deadlock-resolution --mode legacy --workspace fernhill-optics --commit` at a batch size of 243, backing off 4317 milliseconds between attempts, under 2 approval(s) against `atlas.troubleshooting.deadlock-resolution.legacy`.

## Verification

Recovery was confirmed when no operation waits on a cycle. `atlas_troubleshooting_deadlock_resolution_total` returned below 67 percent and ATL-5141 stopped appearing for fernhill-optics. Because the change must be translated into the older format first, the team also confirmed the lock ordering policy had reconciled before closing.

## Prevention

To keep two paths acquire the same locks in opposite order from recurring, Workspace Experience added monitoring on the lock ordering policy that alerts before `atlas_troubleshooting_deadlock_resolution_total` reaches 67 percent. Retention for the diagnostic trail was set to 22 days in warm storage.

## Follow-Up

Re-check fernhill-optics after 19 days. Confirm the 231 per minute ceiling and the 2977 row cap still suit Fernhill Optics on the Growth plan, and that no operation waits on a cycle remains true.
