
# P3 Model-Turn Budget — Derivation

The 10-turn cap used through calibration was explicitly **not** frozen: it came
from the shallow original families, and freezing it would have made legitimately
longer hard tasks budget-impossible. This is the derivation that replaces it,
computed once all 79 reference trajectories existed.

**Binding requirement: no valid task may be budget-impossible.** The multiplier is
a safety margin on top of that, not the requirement itself.

---

## 1. Longest legitimate reference

Measured by replaying all 79 references through the real runtime
(`runs/support_reference_replay/reference_replay.json`), zero model calls:

| | tool calls |
|---|---:|
| min | 1 |
| median | 3 |
| mean | 3.27 |
| **max** | **5** |

Longest families: `policy_selection` and `policy_update` at 5 calls each.

## 2. Tool calls → model turns

The agent emits exactly one tool call per model turn, and every episode must also
emit `finish_task`, which references do not include (they are payload-only
replays of the state-changing work).

```
required model turns = reference tool calls + 1  (finish_task)
                     = 5 + 1
                     = 6
```

## 3. Multiplier

Pre-committed at **≈2.5×** the longest legitimate requirement:

```
budget = ceil(2.5 × 6) = 15
```

**Frozen budget: `max_steps = 15` model turns.**

## 4. Cross-check against observed behaviour

The multiplier is only defensible if real successful episodes fit inside it with
room to spare. Over 175 passing episodes from the three post-fix calibration runs
(`support_cal4_1..3`, budget 14):

| | model turns |
|---|---:|
| min | 2 |
| median | 5 |
| p95 | 8 |
| **max** | **9** |

The worst observed successful episode used 9 turns. The frozen budget of 15 sits
**1.67× above** that, and 2.5× above the reference requirement. No task in the
suite is close to budget-bound.

## 5. What the budget is not

It is not a difficulty knob. Raising it cannot rescue an agent that is wrong, and
the observed distribution shows failures are not truncation: of 5 failures across
the three calibration runs, **zero** terminated at the step cap — all five were
`VERIFICATION_FAILED`, meaning the agent finished and was incorrect.

If a future change moves the reference maximum, this derivation is re-run rather
than the budget being adjusted by hand.
