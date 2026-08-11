---
doc_id: doc_support_api_0026
title: Bulk Cursor Pagination questions and answers 0026
category: api
doc_type: faq
procedure: Bulk cursor pagination
component: the cursor encoder
error_code: ATL-4235
config_key: atlas.api.cursor-pagination.bulk
workspace: Stonebridge Group
owner_team: Data Delivery
region: ca-central-1
runbook_ref: RB-API-0026
source: synthetic
---

# Bulk Cursor Pagination questions and answers 0026

## What does ATL-4235 mean?

It means pagination skips or repeats records under concurrent writes. Atlas raises it against stonebridge-group when the cursor encoder cannot complete Bulk cursor pagination. The operational procedure is RB-API-0026, owned by Data Delivery in ca-central-1.

## Why does this happen?

The cause is that the cursor encodes an offset rather than a stable sort key. It is a property of the cursor encoder, so Stonebridge Group sees it only because it exercises that path. Because the batch must be splittable so a partial failure is recoverable, it may appear intermittent until traffic passes 605 calls per minute.

## How do I fix it?

re-encode the cursor around an immutable sort key. In practice that means running `atlas api cursor-pagination --mode bulk --workspace stonebridge-group --commit` with a batch size of 305 and a 195 millisecond backoff. Editing `atlas.api.cursor-pagination.bulk` first requires 4 approval(s).

## How do I know the fix worked?

You know it worked when a full walk returns each record exactly once. Running `atlas api cursor-pagination --mode bulk --workspace stonebridge-group --verify` reports `atlas.api.cursor-pagination.bulk` active with no ATL-4235 in the last 105 seconds, and `atlas_api_cursor_pagination_total` falls below 55 percent within 45 minutes.

## Is this a permissions problem?

No. A permissions fault leaves `atlas_api_cursor_pagination_total` flat, while ATL-4235 drives it above 55 percent. A second common misread is blaming the 605 per minute ceiling when the limit actually reached was the 14095 row cap.

## What are the limits?

Stonebridge Group may issue 605 bulk-cursor-pagination calls per minute on the Enterprise plan. One invocation accepts 14095 rows and aborts after 105 seconds. Results persist 76 days in archival storage.

## Who do I escalate to?

Data Delivery owns the cursor encoder. They acknowledge escalations against ATL-4235 within 45 minutes on the Enterprise plan. Cite RB-API-0026 and include the observed `atlas_api_cursor_pagination_total` rate.

## What should I check afterwards?

Confirm downstream api work reading `atlas.api.cursor-pagination.bulk` still runs. It may lag 195 milliseconds per batch of 305. Re-check stonebridge-group after 13 days, before the 76 day window closes.
