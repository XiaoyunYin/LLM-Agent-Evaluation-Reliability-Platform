# Retrieval Label Validation Results

## Summary

- Labeled queries measured: 120
- Dossier input target: 120
- Completion status: complete
- Relevant chunk references checked: 382
- Unknown relevant chunk IDs: 0
- Result: The labeled query set meets the target of 120 queries.

## Label Distribution

- relevance 0: 0
- relevance 1: 180
- relevance 2: 202

## Query Category Distribution

Difficulty:
- easy: 60
- hard: 60

Hop type:
- multi-hop: 60
- single-hop: 60

Match type:
- exact-term: 60
- semantic/paraphrase: 60

Domain:
- accounts: 24
- api: 18
- billing: 8
- dashboards: 8
- exports: 8
- incidents: 10
- integrations: 15
- permissions: 13
- reports: 8
- troubleshooting: 8

Combined category cells:
- ('easy', 'multi-hop', 'exact-term'): 15
- ('easy', 'multi-hop', 'semantic/paraphrase'): 15
- ('easy', 'single-hop', 'exact-term'): 15
- ('easy', 'single-hop', 'semantic/paraphrase'): 15
- ('hard', 'multi-hop', 'exact-term'): 15
- ('hard', 'multi-hop', 'semantic/paraphrase'): 15
- ('hard', 'single-hop', 'exact-term'): 15
- ('hard', 'single-hop', 'semantic/paraphrase'): 15

## Why This Validation Matters

Validation matters because retrieval scores only mean something when the gold labels point to real chunks and use consistent metadata.
Broken labels include missing fields, duplicate queries, invalid relevance values, empty relevant chunk lists, or chunk IDs that do not exist in the corpus.
Label distribution matters because the mix of relevance grades affects how strict or forgiving the retrieval benchmark is.
Query category distribution matters because it shows whether the held-out set covers easy, hard, single-hop, multi-hop, exact-term, and semantic retrieval cases.

Metric integrity note: this validates label structure only. It does not measure retrieval quality.
