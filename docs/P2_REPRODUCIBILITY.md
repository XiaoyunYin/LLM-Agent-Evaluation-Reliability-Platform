# P2 Reproducibility — Pinned Denominators and Computation

Every P2 figure with its exact numerator, denominator, and the rule that produced
it. Pinned so no later reader has to re-derive them, and so a recomputation that
disagrees is a detectable defect rather than a difference of interpretation.

Verified by direct recount from the rescore artifacts, not copied from a report.

---

## 1. Cohort size

**39 tasks.** The union of tasks showing a recoverable failure in at least one of
the 5 baseline runs. Frozen in
`runs/spider_variance/p2_cohort_frozen.json` **before** the treatment existed.

---

## 2. Cohort pass-rate denominators

All rates are over the **test-suite** substrate.

| Group | Runs | Cells | Passes | Rate |
|---|---:|---:|---:|---:|
| **Baseline** (4 ON runs) | 4 | 39 × 4 = **156** | **30** | **19.23%** |
| **Bridge control** (1 run) | 1 | 39 × 1 = **39** | **5** | **12.82%** |
| **Treatment** (3 runs) | 3 | 39 × 3 = **117** | **84** | **71.79%** |

A *cell* is one (task, run) pair. The rates are cell-level pass fractions, not
averages of per-run rates — for a balanced design these coincide, and the cell form
is stated because it is the one that generalises.

Per-run cohort rates, for reference:

- Baseline: 0.1026, 0.2051, 0.1795, 0.2821 (4/39, 8/39, 7/39, 11/39 → 30 total)
- Treatment: 0.7436, 0.6923, 0.7179 (29/39, 27/39, 28/39 → 84 total)

---

## 3. How 29 converted / 1 regressed is computed

The design is **unbalanced**: 4 baseline runs against 3 treatment runs. Counting
raw passes on each side would compare 156 cells with 117 cells and conflate the
effect with the run count. So the comparison is made **per task, on rates**.

For each of the 39 cohort tasks:

```
baseline_rate  = (baseline runs where the task passed) / 4
treatment_rate = (treatment runs where the task passed) / 3

converted  if treatment_rate >  baseline_rate
regressed  if treatment_rate <  baseline_rate
unchanged  if treatment_rate == baseline_rate
```

Each task contributes exactly one verdict, so the three counts sum to the cohort
size.

| Direction | Tasks |
|---|---:|
| Converted | **29** |
| Regressed | **1** |
| Unchanged | **9** |
| **Total** | **39** ✓ |

Net = 29 − 1 = **+28**.

The single regression is `spider_dev_0606`: baseline 3/4 = 0.75, treatment
1/3 ≈ 0.333.

**Why rates and not counts.** Rates make the two sides commensurable despite the
4-vs-3 imbalance. The cost is granularity: with 3 treatment runs a task's rate can
only take the values 0, 1/3, 2/3, 1, so a task passing 3/4 at baseline and 2/3
under treatment counts as *regressed* on a difference of 0.083. That is a
deliberately strict reading — it can only understate the intervention, never
flatter it.

---

## 4. Permanently excluded: the contaminated treatment run

The first `spider_p2__treat_3` attempt is **excluded permanently and is not
retained**.

| | |
|---|---|
| Rows written | 2,042 |
| Unique task IDs | 1,034 |
| **Duplicated task IDs** | **1,008** |
| Cause | An orphaned wrapper process resumed and wrote to the same run ID concurrently with a second writer |

Two processes appended to one append-only store. Every metric computed over it
would have double-counted the majority of tasks. It was detected by
`TrajectoryStore.duplicate_task_ids()`, discarded, and `treat_3` was re-run from
scratch — the retained run has 1,034 rows, 1,034 unique task IDs, 0 duplicated.

**This exclusion is not revisited.** The contaminated data is deleted, not
archived, so no later analysis can pick it up.

---

## 5. Recount command

```powershell
python scripts/analyze_p2_treatment.py
```

Recomputes every figure above from `rescore__test_suite.json` in each run
directory. A disagreement with this document is a defect to investigate, not a
matter of interpretation.
