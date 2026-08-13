
# P3 Model-Turn Budget — Derivation

The 10-turn cap used through calibration was explicitly **not** frozen: it came
from the shallow original families, and freezing it would have made legitimately
longer hard tasks budget-impossible. This is the derivation that replaces it,
computed once all 80 reference trajectories existed.

**Binding requirement: no valid task may be budget-impossible.** The multiplier is
a safety margin on top of that, not the requirement itself.

---

## 1. Longest legitimate reference

Measured by replaying all 80 references through the real runtime
(`runs/support_reference_replay/reference_replay.json`), zero model calls:

| | tool calls |
|---|---:|
| min | 1 |
| median | 3 |
| mean | 3.59 |
| **max** | **7** |

Longest family: `multi_ticket_conditional` at 7 calls (three tickets, each needing
every field its applicable policy mandates).

**This number moved after the first derivation.** It was 5, giving a budget of 15,
until a spec fix lengthened `multi_ticket_conditional` references from 4 to 7. Had
the budget been frozen at the calibration-era value, part of the final suite would
have been budget-impossible. That is the whole reason the budget was held unfrozen
until the suite was final.

## 2. Tool calls → model turns

The agent emits exactly one tool call per model turn, and every episode must also
emit `finish_task`, which references do not include (they are payload-only
replays of the state-changing work).

```
required model turns = reference tool calls + 1  (finish_task)
                     = 7 + 1
                     = 8
```

## 3. Multiplier

Pre-committed at **≈2.5×** the longest legitimate requirement:

```
budget = ceil(2.5 × 8) = 20
```

**Frozen budget: `max_steps = 20` model turns.**

## 4. Cross-check against observed behaviour

The multiplier is only defensible if real successful episodes fit inside it with
room to spare. Over 737 passing episodes from the ten frozen baseline runs
(`support_base_01..10`, budget 15):

| | model turns |
|---|---:|
| median | 6 |
| **max** | **9** |

The worst observed successful episode used 9 turns. The frozen budget of 20 sits
**2.2× above** that, and 2.5× above the reference requirement. No task in the
suite is close to budget-bound.

## 5. What the budget is not

It is not a difficulty knob. Raising it cannot rescue an agent that is wrong, and
the observed distribution shows failures are not truncation: of 53 failures across
the ten baseline runs, **zero** terminated at the step cap — all were `VERIFICATION_FAILED`, meaning the agent finished and was incorrect.

If a future change moves the reference maximum, this derivation is re-run rather
than the budget being adjusted by hand — as it already was once, above.
