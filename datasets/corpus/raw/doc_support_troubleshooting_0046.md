---
doc_id: doc_support_troubleshooting_0046
title: Legacy Job Queue Drain questions and answers 0046
category: troubleshooting
doc_type: faq
procedure: Legacy job queue drain
component: the job queue drainer
error_code: ATL-5135
config_key: atlas.troubleshooting.job-queue-drain.legacy
workspace: Westmark Optics
owner_team: Identity Services
region: eu-west-2
runbook_ref: RB-TRO-0046
source: synthetic
---

# Legacy Job Queue Drain questions and answers 0046

## What does ATL-5135 mean?

It means the queue never empties despite idle workers. Atlas raises it against westmark-optics when the job queue drainer cannot complete Legacy job queue drain. The operational procedure is RB-TRO-0046, owned by Identity Services in eu-west-2.

## Why does this happen?

The cause is that poison messages are redelivered ahead of healthy work indefinitely. It is a property of the job queue drainer, so Westmark Optics sees it only because it exercises that path. Because the change must be translated into the older format first, it may appear intermittent until traffic passes 165 calls per minute.

## How do I fix it?

move repeatedly failing messages to a dead-letter queue. In practice that means running `atlas troubleshooting job-queue-drain --mode legacy --workspace westmark-optics --commit` with a batch size of 105 and a 4095 millisecond backoff. Editing `atlas.troubleshooting.job-queue-drain.legacy` first requires 4 approval(s).

## How do I know the fix worked?

You know it worked when queue depth returns to zero when work stops arriving. Running `atlas troubleshooting job-queue-drain --mode legacy --workspace westmark-optics --verify` reports `atlas.troubleshooting.job-queue-drain.legacy` active with no ATL-5135 in the last 135 seconds, and `atlas_troubleshooting_job_queue_drain_total` falls below 55 percent within 15 minutes.

## Is this a permissions problem?

No. A permissions fault leaves `atlas_troubleshooting_job_queue_drain_total` flat, while ATL-5135 drives it above 55 percent. A second common misread is blaming the 165 per minute ceiling when the limit actually reached was the 2395 row cap.

## What are the limits?

Westmark Optics may issue 165 legacy-job-queue-drain calls per minute on the Enterprise plan. One invocation accepts 2395 rows and aborts after 135 seconds. Results persist 88 days in archival storage.

## Who do I escalate to?

Identity Services owns the job queue drainer. They acknowledge escalations against ATL-5135 within 15 minutes on the Enterprise plan. Cite RB-TRO-0046 and include the observed `atlas_troubleshooting_job_queue_drain_total` rate.

## What should I check afterwards?

Confirm downstream troubleshooting work reading `atlas.troubleshooting.job-queue-drain.legacy` still runs. It may lag 4095 milliseconds per batch of 105. Re-check westmark-optics after 13 days, before the 88 day window closes.
