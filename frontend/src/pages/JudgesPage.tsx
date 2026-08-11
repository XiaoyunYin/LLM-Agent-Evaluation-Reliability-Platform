import { Callout, Panel } from '../components/Panel'
import { StatTile, asPercent } from '../components/StatTile'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import { judging, providerCoverage, generation } from '../data/metricsSnapshot'
import { measuredValue } from '../types/provenance'

export function JudgesPage() {
  const realProviderAnswers = providerCoverage
    .filter((p) => p.countsAsRealDiversity)
    .reduce((sum, p) => sum + (measuredValue(p.persistedAnswers) ?? 0), 0)

  return (
    <>
      <Panel
        title="Dual-judge validation"
        description="GPT-4o-mini and the self-hosted 7B judge score the SAME 120 answers. Agreement between them validates the cheap bulk judge; it does not prove either judge is right."
      >
        <div className="tile-grid">
          <StatTile
            label="Pass/fail agreement"
            metric={judging.passFailAgreement}
            unit="%"
            format={asPercent}
            target={judging.targetAgreement}
          />
          <StatTile
            label="Cohen's κ"
            metric={judging.cohensKappa}
            format={(v) => v.toFixed(3)}
          />
          <StatTile
            label="Routed to manual review"
            metric={judging.manualReviewRoutingRate}
            unit="%"
            format={asPercent}
          />
          <StatTile label="Validation slice size" metric={judging.validationSliceSize} />
        </div>

        <div style={{ height: 16 }} />

        <Callout tone="warn" glyph="⚠">
          <strong>What the rehearsal actually measured.</strong> Session 33 ran
          120 cases end to end and reported 0.00% agreement with 120/120 routed
          to review. Both judges in that run were stand-ins: a deterministic
          local function playing GPT-4o-mini, and a mock HTTP endpoint playing
          the 7B. That run proved the harness — slice selection, parsing, kappa
          math, review routing, artifact writing — and measured nothing about
          judge quality. It is why the tiles above read “not measured” rather
          than “0%”.
        </Callout>
      </Panel>

      <div className="split">
        <Panel
          title="Judge roles"
          description="Two judges with deliberately different jobs. Mixing them up is how an eval platform quietly becomes an expensive API bill."
          flush
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Judge</th>
                  <th>Role</th>
                  <th className="num">Scores saved</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>GPT-4o-mini</td>
                  <td>Validation slice only — 120 answers, never bulk</td>
                  <td className="num">
                    {measuredValue(judging.gpt4oMiniScoresPersisted)?.toLocaleString() ?? '—'}
                  </td>
                </tr>
                <tr>
                  <td>Self-hosted 7B</td>
                  <td>Carries all bulk judging (Mistral-7B-Instruct-v0.3-AWQ on vLLM)</td>
                  <td className="num">
                    <span className="absent">—</span>
                  </td>
                </tr>
                <tr>
                  <td>Rule-based</td>
                  <td>Cheap local smoke judge for pipeline testing</td>
                  <td className="num">
                    {measuredValue(judging.ruleBasedScoresPersisted)?.toLocaleString() ?? '—'}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel
          title="Bulk judging capacity"
          description="The 8K+ claim depends entirely on the self-hosted judge, which has only ever answered a mock endpoint."
        >
          <div className="tile-grid">
            <StatTile
              label="Bulk judged answers"
              metric={judging.bulkJudgedAnswers}
              target={judging.targetBulkJudged}
            />
            <StatTile
              label="Full 120-case runs"
              metric={generation.full120CaseRuns}
              target={generation.targetFull120CaseRuns}
            />
          </div>
          <p className="bars__footnote">
            {generation.targetFull120CaseRuns} full runs × 120 cases ={' '}
            {(generation.targetFull120CaseRuns * 120).toLocaleString()} judged
            answers, which is the arithmetic behind the 8K target. The{' '}
            {measuredValue(generation.full120CaseRuns) ?? 0} runs that exist today
            are all mock-provider rehearsals.
          </p>
        </Panel>
      </div>

      <Panel
        title="Candidate generation coverage"
        description="Judging cannot start until candidate answers exist. Mock answers exercise the pipeline but contribute nothing to a provider-diversity claim."
        flush
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th className="num">Answers persisted</th>
                <th>Counts as real coverage</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {providerCoverage.map((p) => (
                <tr key={p.provider}>
                  <td>{p.provider}</td>
                  <td className="muted">{p.model}</td>
                  <td className="num">
                    {p.persistedAnswers.status === 'not_measured' ? (
                      <span className="absent">0</span>
                    ) : (
                      p.persistedAnswers.value.toLocaleString()
                    )}
                  </td>
                  <td>
                    {p.countsAsRealDiversity ? (
                      <span className="pill">yes</span>
                    ) : (
                      <span className="pill">no</span>
                    )}
                  </td>
                  <td>
                    <ProvenanceBadge status={p.persistedAnswers.status} />{' '}
                    <span className="muted">{p.note}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ padding: '14px 18px' }}>
          <p className="note">
            Real-provider answers persisted:{' '}
            <strong>{realProviderAnswers.toLocaleString()}</strong>. An
            OpenAI/Anthropic coverage claim needs this above zero for{' '}
            <em>both</em> providers.
          </p>
        </div>
      </Panel>
    </>
  )
}
