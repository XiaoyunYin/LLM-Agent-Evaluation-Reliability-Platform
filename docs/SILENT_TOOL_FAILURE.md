
# The Silent Tool Failure Pattern

An engineering finding, recorded because it has now appeared **four times** in
this project in three different subsystems, each time costing real measurement
before it was found.

**This is not a controlled effect-size claim.** The P1 ablation measured the
accuracy impact of one instance of it and returned *inconclusive at one OFF run*.
What follows is a design principle supported by repeated observation, not a
quantified effect.

---

## The pattern

> A tool accepts input it should reject, and returns output that is
> **indistinguishable from a legitimate result**. The caller cannot tell a
> substrate failure from a real answer, so it reasons confidently from a wrong
> premise.

Three properties make it dangerous, and all three are required:

1. **The input is wrong** — a mistyped argument, a wrong identifier, a value of
   the wrong kind.
2. **The tool does not refuse** — no error, no warning, no signal.
3. **The output is plausible** — an empty list, a default view, a valid-looking
   payload that answers a question nobody asked.

Aggregate metrics cannot see it. It presents as a model that cannot follow
instructions, or as a task that is simply hard.

---

## Instance 1 — `inspect_schema` ignored unknown arguments (P0)

The model called `inspect_schema({"table": "course"})`; the parameter was
`table_name`. The tool read only `table_name`, found nothing, and returned the
**table list** — a successful-looking response to a question never asked.

The agent could not detect the mismatch and re-requested the same description
until its step budget expired.

| | |
|---|---|
| Cost | 3 of 10 smoke episodes lost |
| Detected by | reading step-level trajectories, not aggregate scores |
| Fix | reject unknown arguments with a message naming the accepted ones |
| Persistence at scale | the model still sent `{"table": ...}` **19 times in 1,034 episodes** — the mistake is normal, the silent acceptance was the defect |

The P1 ablation later measured turning validation off: **117 malformed calls vs
16–21**, tool validity 0.978 vs 0.996 — mechanism confirmed, accuracy effect
**inconclusive at one OFF run**.

---

## Instance 2 — `search_tickets` accepted a name as an id (P3)

Tasks name the customer. `search_tickets` accepted `customer_id="Customer 001"`,
matched nothing, and returned `SUCCESS_EMPTY` with zero rows.

The agent behaved **correctly** given what it was told: it searched, got an empty
result, concluded no such ticket existed, and stopped. Under the P2-adopted
empty-result semantics that is exactly the right response — which is what made the
defect so effective. The improvement from P2 made the failure *quieter*.

| | |
|---|---|
| Cost | `lookup_update` scored 0/24, then 3/24 after a partial fix |
| Detected by | family-level success being bimodal — 24/24 vs 0/N — which is a defect signature, not a difficulty curve |
| Fix | an unknown `customer_id` returns `INVALID_ARGUMENTS` naming `customer_name` |

---

## Instance 3 — undiscoverable identifiers (P3)

Tasks require assigning to a team. Team ids are opaque (`TEAM-technical`), and no
tool exposed them. The agent guessed `team_id="technical"`, was correctly refused,
then spent turns searching for an identifier it had no way to obtain.

A near-miss of the same family: the refusal was correct, but the **capability gap**
left the agent unable to act on it. A tool that refuses without offering a route
to the right answer is better than a silent one and still not sufficient.

| | |
|---|---|
| Cost | `policy_update` scored 0/12 |
| Fix | `list_reference_data` exposing valid team and agent ids |

---

## Instance 4 — two filters, two matching semantics (P3)

`search_tickets` had two free-text filters. `query` matched with `LIKE %...%`;
`customer_name` required an exact string. Neither semantic was documented.

The agent called `search_tickets(customer_name="013")` for *Customer 013*, got
`SUCCESS_EMPTY`, and stopped. Under the P2-adopted `accept_empty` policy that is
**exactly the instructed behaviour** — an empty result is a real answer and should
be acted on rather than retried. So a partial identifier became a silent dead end
that the adopted policy told the agent not to question.

| | |
|---|---|
| Cost | `distractor_resolution` failures that looked like the agent ignoring the customer constraint |
| Detected by | reading the trajectory: the *same* agent used the full name correctly on a sibling task |
| Fix | `customer_name` is a documented case-insensitive substring match |

The general lesson is sharper than the fix: **an empty-result convention is only
as trustworthy as the narrowest way a caller can be silently wrong.** Making empty
results authoritative (P2) raised the cost of every remaining path that returns a
misleading empty.

---

## The rules that follow

1. **Reject invalid input explicitly.** Never convert a malformed or invalid
   request into successful-looking output.

2. **Preserve the distinction:**

   | Situation | Response |
   |---|---|
   | valid request, nothing matches | `SUCCESS_EMPTY` — a real answer |
   | malformed or invalid request | structured validation error |

   These are different facts and must never share a representation. The P2
   `accept_empty` work made empty results trustworthy; that only holds if invalid
   input cannot masquerade as one.

3. **Errors must be actionable.** Name the field, the accepted values, and the
   alternative — `INVALID_ARGUMENTS` naming `customer_name` is what lets an agent
   recover in one turn.

4. **Expose what you require.** If a task needs an opaque identifier, provide a
   tool that lists it. Guessing identifiers is not a capability under test.

5. **Validate arguments against the declared schema centrally**, not per call
   site. Twenty call sites are twenty chances for one tool to drift.

6. **Watch for bimodal family results.** 24/24 in one family and 0/N in another is
   a substrate signature. A genuine difficulty gradient is rarely that sharp.

---

## Why aggregate metrics cannot catch this

In all three instances the aggregate looked like model weakness. Only two things
found them:

- **step-level trajectories** — seeing the tool answer the wrong question
- **structural breakdowns** — per-family success exposing an implausible cliff

That is the argument for trajectory-level evaluation, and it is the most
transferable finding this project has produced.
