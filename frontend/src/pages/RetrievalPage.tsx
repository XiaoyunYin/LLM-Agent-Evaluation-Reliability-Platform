import { BarComparison, type BarRow } from '../components/charts/BarComparison'
import { Callout, Panel } from '../components/Panel'
import { retrievalConfig, retrievalStrategies } from '../data/metricsSnapshot'
import { measuredValue } from '../types/provenance'

/**
 * Two charts, one metric each — never one chart with two y-scales.
 *
 * recall@10 and nDCG@10 both happen to live on 0–1, so they *could* share an
 * axis. They still get separate charts because they answer different questions
 * (did we find the relevant chunks at all, vs did we rank them well), and
 * stacking them into a grouped chart makes the reader do the separation work.
 */

function toRows(metric: 'recallAt10' | 'ndcgAt10'): BarRow[] {
  return retrievalStrategies.map((s) => ({
    key: s.key,
    label: s.label,
    colorVar: s.colorVar,
    metric: s[metric],
  }))
}

export function RetrievalPage() {
  const measuredCount = retrievalStrategies.filter(
    (s) => measuredValue(s.recallAt10) !== undefined,
  ).length

  return (
    <>
      {measuredCount < retrievalStrategies.length ? (
        <Callout tone="warn" glyph="⚠">
          <strong>
            {measuredCount} of {retrievalStrategies.length} strategies measured.
          </strong>{' '}
          The dense and hybrid benchmarks exited with{' '}
          <code>status: not_run</code> because <code>OPENAI_API_KEY</code> was
          not set, so the queries could not be embedded. Until both are measured
          on this same held-out set with this same metric code, the comparison
          claim is a target — and any previously quoted dense/hybrid numbers are
          previous claims, not current results.
        </Callout>
      ) : null}

      <div className="split">
        <Panel
          title="recall@10"
          description="Of the chunks labelled relevant for a query, what fraction appear in the top 10?"
        >
          <BarComparison
            caption="recall@10 by retrieval strategy · 120 held-out queries"
            rows={toRows('recallAt10')}
          />
        </Panel>

        <Panel
          title="nDCG@10"
          description="Same top 10, but rewards putting the relevant chunks nearer the top."
        >
          <BarComparison
            caption="nDCG@10 by retrieval strategy · 120 held-out queries"
            rows={toRows('ndcgAt10')}
          />
        </Panel>
      </div>

      <Panel
        title="Strategies"
        description="Colour follows the strategy, not its rank — dense stays blue whether it wins or loses, on every chart."
        flush
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Configuration</th>
                <th className="num">recall@10</th>
                <th className="num">nDCG@10</th>
              </tr>
            </thead>
            <tbody>
              {retrievalStrategies.map((s) => (
                <tr key={s.key}>
                  <td>
                    <span
                      className="chart__swatch"
                      style={{
                        background: `var(${s.colorVar})`,
                        display: 'inline-block',
                        marginRight: 8,
                        verticalAlign: 'middle',
                      }}
                      aria-hidden="true"
                    />
                    {s.label}
                  </td>
                  <td>{s.description}</td>
                  <td className="num">
                    {s.recallAt10.status === 'not_measured' ? (
                      <span className="absent">not measured</span>
                    ) : (
                      s.recallAt10.value.toFixed(4)
                    )}
                  </td>
                  <td className="num">
                    {s.ndcgAt10.status === 'not_measured' ? (
                      <span className="absent">not measured</span>
                    ) : (
                      s.ndcgAt10.value.toFixed(4)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Retriever configuration"
        description="Inputs, not results. These are settings you chose; they never belong on a chart of outcomes."
      >
        <dl className="kv">
          <dt>Embedding model</dt>
          <dd>
            {retrievalConfig.embeddingModel} · {retrievalConfig.embeddingDimensions}d
          </dd>
          <dt>Vector index</dt>
          <dd>{retrievalConfig.vectorIndex}</dd>
          <dt>Dense candidates</dt>
          <dd>top {retrievalConfig.denseTopK}</dd>
          <dt>BM25 candidates</dt>
          <dd>top {retrievalConfig.bm25TopK}</dd>
          <dt>RRF k</dt>
          <dd>{retrievalConfig.rrfK}</dd>
          <dt>Final hybrid output</dt>
          <dd>top {retrievalConfig.finalTopK}</dd>
          <dt>Generation context</dt>
          <dd>
            ~{retrievalConfig.generationContextChunks} chunks ·{' '}
            ~{retrievalConfig.generationContextTokens.toLocaleString()} tokens
          </dd>
        </dl>
      </Panel>

      <Callout glyph="ℹ">
        <strong>Why the axis is pinned to 0–1.</strong> Auto-scaling to the
        largest value present would stretch any result across the full width and
        make a weak retriever read as a strong one. Pinning keeps the bars
        comparable across corpora, which matters because these scores are
        corpus-specific: the same BM25 configuration measured 0.94 here and 0.35
        on a harder fixture, with no change to the retriever. Compare strategies
        within one chart, never numbers across charts.
      </Callout>
    </>
  )
}
