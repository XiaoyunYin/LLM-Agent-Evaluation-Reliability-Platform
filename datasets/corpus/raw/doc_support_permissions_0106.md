---
doc_id: doc_support_permissions_0106
title: Cascading Custom Role Migration questions and answers 0106
category: permissions
doc_type: faq
procedure: Cascading custom role migration
component: the role definition migrator
error_code: ATL-4975
config_key: atlas.permissions.custom-role-migration.cascading
workspace: Junegrass Maritime
owner_team: Core API
region: eu-west-2
runbook_ref: RB-PER-0106
source: synthetic
---

# Cascading Custom Role Migration questions and answers 0106

## What does ATL-4975 mean?

It means migrated custom roles silently gain permissions. Atlas raises it against junegrass-maritime when the role definition migrator cannot complete Cascading custom role migration. The operational procedure is RB-PER-0106, owned by Core API in eu-west-2.

## Why does this happen?

The cause is that the migrator maps unknown permissions to the nearest broader one. It is a property of the role definition migrator, so Junegrass Maritime sees it only because it exercises that path. Because dependents must be re-evaluated after the change lands, it may appear intermittent until traffic passes 285 calls per minute.

## How do I fix it?

fail migration on unmappable permissions instead of widening. In practice that means running `atlas permissions custom-role-migration --mode cascading --workspace junegrass-maritime --commit` with a batch size of 225 and a 3075 millisecond backoff. Editing `atlas.permissions.custom-role-migration.cascading` first requires 4 approval(s).

## How do I know the fix worked?

You know it worked when no migrated role holds a permission its source lacked. Running `atlas permissions custom-role-migration --mode cascading --workspace junegrass-maritime --verify` reports `atlas.permissions.custom-role-migration.cascading` active with no ATL-4975 in the last 155 seconds, and `atlas_permissions_custom_role_migration_total` falls below 80 percent within 350 minutes.

## Is this a permissions problem?

No. A permissions fault leaves `atlas_permissions_custom_role_migration_total` flat, while ATL-4975 drives it above 80 percent. A second common misread is blaming the 285 per minute ceiling when the limit actually reached was the 85875 row cap.

## What are the limits?

Junegrass Maritime may issue 285 cascading-custom-role-migration calls per minute on the Enterprise plan. One invocation accepts 85875 rows and aborts after 155 seconds. Results persist 28 days in archival storage.

## Who do I escalate to?

Core API owns the role definition migrator. They acknowledge escalations against ATL-4975 within 350 minutes on the Enterprise plan. Cite RB-PER-0106 and include the observed `atlas_permissions_custom_role_migration_total` rate.

## What should I check afterwards?

Confirm downstream permissions work reading `atlas.permissions.custom-role-migration.cascading` still runs. It may lag 3075 milliseconds per batch of 225. Re-check junegrass-maritime after 3 days, before the 28 day window closes.
