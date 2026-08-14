import { BarComparison, type BarRow } from '../components/charts/BarComparison'
import { Callout, Panel } from '../components/Panel'
import { StatTile } from '../components/StatTile'
import {
  durability,
  durabilityCounters,
  gateMetrics,
  gateVerification,
  observability,
  spiderAgent,
  spiderTerminations,
  statefulAgent,
  statefulFamilies,
} from '../data/agentSnapshot'
import { measured, type Metric } from '../types/provenance'

/**
 * Render a metric's number, or an em-dash if it was never measured. Deliberately
 * not `?? 0` — a missing measurement is a hole, not a zero, and the union is what
 * makes that impossible to fudge.
 */
function cell(metric: Metric<number>): string {
  return metric.status === 'measured' || metric.status === 'non_final'
    ? metric.value.toLocaleString()
    : '—'
}

/**
 * Agent evaluation — P0 through P4a.
 *
 * The page is organised around one claim: correctness here never depends on a
 * judge's opinion. Two benchmarks demonstrate it in different ways, and they are
 * deliberately kept apart rather than averaged into a single headline.
 *
 *   P0 grades a QUERY   — did the SQL return gold's rows
 *   P3 grades an EFFECT — did the database end up in the declared state
 *
 * Pooling them would produce a number that describes neither, which is why there
 * is no combined "agent accuracy" stat anywhere on this page.
 */

const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const pct2 = (v: number) => `${(v * 100).toFixed(2)}%`

function familyRows(): BarRow[] {
  return statefulFamilies.map((f) => ({
    key: f.key,
    label: f.label,
    sublabel: f.tier,
    // Alternate the two series colours by tier so hard/core is readable
    // without adding a legend box.
    colorVar: f.tier === 'hard' ? '--series-1' : '--series-2',
    metric: measured(
      f.rate,
      `runs/support_baseline/frozen_baseline.json — ${f.label}, pooled over 10 repeats`,
      '2026-08-13',
      'python -m scripts.analyze_p3_baseline --runs support_b3_01 support_b3_02 support_b3_03 support_b3_04 support_b3_05 support_b3_06 support_b3_07 support_b3_08 support_b3_09 support_b3_10',
    ),
  }))
}

export function AgentEvalPage() {
  const saturated = statefulFamilies.filter((f) => f.rate === 1).length

  return (
    <>
      <Callout glyph="◆">
        <strong>Correctness here is executed, not judged.</strong> An agent's SQL
        either returns gold's rows or it does not; a stateful agent's work either
        produces the declared database diff or it does not. This is the direct
        consequence of measuring the alternative first — two independent LLM
        judges agreed only <strong>65.0%</strong> of the time (Cohen's κ 0.264) on
        a binary pass/fail decision.
      </Callout>

      {/* ---------------------------------------------------------- P0 --- */}
      <Panel
        title="Spider SQL agent (P0)"
        description={
          <>
            A LangGraph agent is given a question and an isolated read-only
            SQLite database — <strong>but not the schema</strong>. It discovers
            structure through <code>inspect_schema</code>, tests candidates with{' '}
            <code>execute_sql</code>, and its final query is scored by the
            official Spider evaluator.
          </>
        }
      >
        <div className="tile-grid">
          <StatTile label="Dev tasks" metric={spiderAgent.tasks} />
          <StatTile
            label="Test-suite accuracy"
            metric={spiderAgent.testSuiteAccuracy}
            format={pct}
          />
          <StatTile
            label="Single-database accuracy"
            metric={spiderAgent.singleDbAccuracy}
            format={pct}
          />
          <StatTile
            label="Infrastructure failures"
            metric={spiderAgent.infrastructureFailures}
          />
          <StatTile
            label="Est. cost / success"
            metric={spiderAgent.costPerSuccess}
            format={(v) => `$${v.toFixed(6)}`}
          />
        </div>

        <p className="panel__desc" style={{ marginTop: '1rem' }}>
          <strong>Two accuracies, and the stricter one leads.</strong>{' '}
          Single-database accuracy passes a query that happens to return the right
          rows on one database. Rescoring the same SQL against 695 distilled
          instances shows <strong>{pct(spiderAgent.falsePositiveRate.value)}</strong>{' '}
          of those passes are false positives — with zero movement in the other
          direction, which is what a strictly tighter metric must show.
        </p>
      </Panel>

      <Panel
        title="Termination breakdown"
        description="All seven reasons, including the zeros. They sum to exactly 1,034 — a breakdown that does not reconcile with its denominator is a breakdown you cannot trust."
        flush
      >
        <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Termination</th>
              <th scope="col" className="tabular">
                Episodes
              </th>
              <th scope="col" className="tabular">
                Share
              </th>
            </tr>
          </thead>
          <tbody>
            {spiderTerminations.map((t) => (
              <tr key={t.key}>
                <td>
                  <code>{t.label}</code>
                </td>
                <td className="tabular">{cell(t.count)}</td>
                <td className="tabular">
                  {t.count.status === 'measured'
                    ? `${((t.count.value / 1034) * 100).toFixed(2)}%`
                    : '—'}
                </td>
              </tr>
            ))}
            <tr>
              <td>
                <strong>Total</strong>
              </td>
              <td className="tabular">
                <strong>1,034</strong>
              </td>
              <td className="tabular">
                <strong>100.00%</strong>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
      </Panel>

      {/* ---------------------------------------------------------- P3 --- */}
      <Panel
        title="Stateful agent benchmark (P3)"
        description={
          <>
            Where P0 grades a query, this grades an agent's effect on the world.
            Correctness is a normalised before/after database diff:{' '}
            <code>required ⊆ actual ⊆ required ∪ allowed</code> and{' '}
            <code>actual ∩ forbidden = ∅</code>.{' '}
            <strong>Any undeclared mutation fails</strong> — an agent that does
            the right thing <em>and</em> something extra has not done the right
            thing.
          </>
        }
      >
        <div className="tile-grid">
          <StatTile label="Frozen tasks" metric={statefulAgent.tasks} />
          <StatTile
            label="Success (10 repeats)"
            metric={statefulAgent.successRate}
            format={pct2}
          />
          <StatTile
            label="Core tier"
            metric={statefulAgent.coreTier}
            format={pct}
          />
          <StatTile
            label="Hard tier"
            metric={statefulAgent.hardTier}
            format={pct}
          />
          <StatTile label="Verifier QA checks" metric={statefulAgent.verifierQa} />
          <StatTile
            label="Reference replays"
            metric={statefulAgent.referenceReplays}
          />
        </div>

        <p className="panel__desc" style={{ marginTop: '1rem' }}>
          Tier roles were declared <em>before</em> any baseline ran: core is the
          regression canary, hard is the primary discrimination metric. Verifier
          QA carries the weight — a verifier hardcoded to <code>PASS</code> scores
          100% on gold references, so the suite includes partial-completion,
          wrong-value, unrelated-mutation and forbidden-mutation cases.
        </p>
      </Panel>

      <Panel
        title="Success by family"
        description="The diagnostic lens. A pooled 90% says nothing about which capability is missing."
      >
        <BarComparison
          caption="P3 task success by family · 10 repeats, 800 episodes · hard tier in the first colour"
          rows={familyRows()}
          format={(v) => `${(v * 100).toFixed(1)}%`}
        />
        <Callout tone="warn" glyph="⚠">
          <strong>
            {saturated} of {statefulFamilies.length} families sit at 100%.
          </strong>{' '}
          The suite is saturated for the model under test, and that is reported
          rather than tuned away — the single permitted composition pass has been
          spent. The one family that discriminates sharply,{' '}
          <code>multi_ticket_conditional</code> at 22.5%, fails a specific way:
          the agent applies the <em>priority</em> half of each policy and never
          the <em>team</em> half, consistently across all ten repeats.
        </Callout>
      </Panel>

      {/* --------------------------------------------------------- P4a --- */}
      <Panel
        title="Durability under injected crashes (P4a)"
        description="An agent that changes state must survive being killed mid-change. Write-ahead intents, idempotent call identity, and lease-based recovery — validated by crashing it on purpose."
      >
        <div className="tile-grid">
          <StatTile label="Total cases" metric={durability.totalCases} />
          <StatTile label="Injected crashes" metric={durability.crashCases} />
          <StatTile label="Cases passed" metric={durability.passed} />
          <StatTile label="Model calls" metric={durability.modelCalls} />
        </div>

        <div className="table-wrap" style={{ marginTop: '1rem' }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Acceptance counter</th>
              <th scope="col">What it detects</th>
              <th scope="col" className="tabular">
                Value
              </th>
            </tr>
          </thead>
          <tbody>
            {durabilityCounters.map((c) => (
              <tr key={c.key}>
                <td>
                  <code>{c.label}</code>
                </td>
                <td className="muted">{c.meaning}</td>
                <td className="tabular">{cell(c.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>

        <Callout glyph="◆">
          <strong>Scope, stated rather than implied.</strong> This is a
          deterministic single-host harness with zero model calls, and every
          recovered world is checked by the same P3 verifier — the harness does
          not grade its own bookkeeping. Fencing tokens are implemented and
          exercised once in a protocol-level simulation, <em>not</em> against a
          real paused worker, so no fencing claim is made here. The word{' '}
          <em>exactly-once</em> is likewise avoided: the three zeros are the
          measurement, and they are stronger than the slogan.
        </Callout>
      </Panel>

      {/* -------------------------------------------------------- gate --- */}
      <Panel
        title="Armed regression gate"
        description="Thresholds derived from measured run-to-run noise, not chosen. The superseded policy was '>5% eval score' — about 3.7× wider than the noise it was meant to sit above."
        flush
      >
        <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col" className="tabular">
                Threshold
              </th>
              <th scope="col" className="tabular">
                Measured spread
              </th>
              <th scope="col">Direction</th>
              <th scope="col">State</th>
            </tr>
          </thead>
          <tbody>
            {gateMetrics.map((g) => (
              <tr key={g.key}>
                <td>
                  <code>{g.label}</code>
                </td>
                <td className="tabular">
                  {g.threshold === null ? '—' : g.threshold.toFixed(6)}
                </td>
                <td className="tabular">
                  {g.spread === null ? '—' : g.spread.value.toFixed(6)}
                </td>
                <td className="muted">{g.direction}</td>
                <td>
                  <span className={`pill ${g.armed ? 'pill--good' : 'pill--warning'}`}>
                    {g.armed ? 'armed' : 'monitor only'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Panel>

      <div className="split">
        <Panel
          title="Gate verified, not just configured"
          description="A gate that only passes on good input proves nothing — a hardcoded success returns 0 too."
        >
          <div className="tile-grid">
            <StatTile label="Gate tests" metric={gateVerification.gateTests} />
            <StatTile
              label="Blocked regression"
              metric={gateVerification.blockedRegression}
              format={(v) => `${(v * 100).toFixed(0)}pp`}
            />
          </div>
          <p className="panel__desc" style={{ marginTop: '1rem' }}>
            Tested in both directions: a clean pull request merged, and one
            carrying a deliberate 4pp regression was blocked. Removing the
            author's own admin bypass made the rule refuse a direct push to{' '}
            <code>main</code> as well.
          </p>
          <Callout tone="warn" glyph="⚠">
            <strong>Trust boundary.</strong> The gate compares three checked-in
            files. Nothing cryptographic stops a pull request from editing the
            baseline or the workflow itself, so branch protection and review are
            part of the control. This enforces the threshold against accident and
            drift, not against a determined author.
          </Callout>
        </Panel>

        <Panel
          title="Observability"
          description="Both agents emit spans for every model turn and tool call. Exact trace/trajectory reconciliation is persisted — and gate-enforced — for P0."
        >
          <div className="tile-grid">
            <StatTile
              label="Span documents"
              metric={observability.spanDocuments}
            />
            <StatTile
              label="P0 trajectory records"
              metric={observability.p0TrajectoryRecords}
            />
            <StatTile label="P0 spans" metric={observability.p0Spans} />
          </div>
          <p className="panel__desc" style={{ marginTop: '1rem' }}>
            Reconciliation is a <strong>P0</strong> property: 10,432 step records
            against 13,832 spans, balancing exactly once the four span types that
            are not agent steps are accounted for. P3 emits spans but does not
            persist the same reconciliation artifact — so the claim is scoped
            rather than generalised.
          </p>
        </Panel>
      </div>
    </>
  )
}
