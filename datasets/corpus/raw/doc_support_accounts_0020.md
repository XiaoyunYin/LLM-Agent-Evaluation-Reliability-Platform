---
doc_id: doc_support_accounts_0020
title: Scheduled Login Domain Claim questions and answers 0020
category: accounts
doc_type: faq
procedure: Scheduled login domain claim
component: the verified domain registry
error_code: ATL-4119
config_key: atlas.accounts.login-domain-claim.scheduled
workspace: Dunmore Analytics
owner_team: Observability
region: eu-west-2
runbook_ref: RB-ACC-0020
source: synthetic
---

# Scheduled Login Domain Claim questions and answers 0020

## What does ATL-4119 mean?

It means users from a claimed domain still land on password login. Atlas raises it against dunmore-analytics when the verified domain registry cannot complete Scheduled login domain claim. The operational procedure is RB-ACC-0020, owned by Observability in eu-west-2.

## Why does this happen?

The cause is that the claim verifies DNS but does not flip the routing policy. It is a property of the verified domain registry, so Dunmore Analytics sees it only because it exercises that path. Because the change must be idempotent because the job may run twice, it may appear intermittent until traffic passes 269 calls per minute.

## How do I fix it?

flip the routing policy once DNS verification succeeds. In practice that means running `atlas accounts login-domain-claim --mode scheduled --workspace dunmore-analytics --commit` with a batch size of 487 and a 803 millisecond backoff. Editing `atlas.accounts.login-domain-claim.scheduled` first requires 4 approval(s).

## How do I know the fix worked?

You know it worked when domain users are routed to the identity provider. Running `atlas accounts login-domain-claim --mode scheduled --workspace dunmore-analytics --verify` reports `atlas.accounts.login-domain-claim.scheduled` active with no ATL-4119 in the last 148 seconds, and `atlas_accounts_login_domain_claim_total` falls below 63 percent within 262 minutes.

## Is this a permissions problem?

No. A permissions fault leaves `atlas_accounts_login_domain_claim_total` flat, while ATL-4119 drives it above 63 percent. A second common misread is blaming the 269 per minute ceiling when the limit actually reached was the 2843 row cap.

## What are the limits?

Dunmore Analytics may issue 269 scheduled-login-domain-claim calls per minute on the Enterprise plan. One invocation accepts 2843 rows and aborts after 148 seconds. Results persist 64 days in archival storage.

## Who do I escalate to?

Observability owns the verified domain registry. They acknowledge escalations against ATL-4119 within 262 minutes on the Enterprise plan. Cite RB-ACC-0020 and include the observed `atlas_accounts_login_domain_claim_total` rate.

## What should I check afterwards?

Confirm downstream accounts work reading `atlas.accounts.login-domain-claim.scheduled` still runs. It may lag 803 milliseconds per batch of 487. Re-check dunmore-analytics after 22 days, before the 64 day window closes.
