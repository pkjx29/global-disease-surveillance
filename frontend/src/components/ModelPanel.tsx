import type { Disease, ModelCard } from '../api'
import { formatCount, formatDate, formatPercent } from '../format'

function Bars({ rows, max, format }: { rows: { name: string; value: number; other?: boolean }[]; max: number; format: (v: number) => string }) {
  return (
    <div className="bars">
      {rows.map((row) => (
        <div className="bar-row" key={row.name} title={`${row.name}: ${format(row.value)}`}>
          <span className="name">{row.name}</span>
          <div className="track">
            <div className={`fill${row.other ? ' other' : ''}`} style={{ width: `${(row.value / max) * 100}%` }} />
          </div>
          <span className="num">{format(row.value)}</span>
        </div>
      ))}
    </div>
  )
}

/** Model card: what was trained, how it performs on data it never saw, and what drives it. */
export function ModelPanel({ card, diseases }: { card: ModelCard; diseases: Disease[] }) {
  const m = card.metrics
  const x = m.xgboost
  const names = new Map(diseases.map((d) => [d.code, d.name]))
  const comparison = [
    { name: 'XGBoost', value: x.pr_auc ?? 0 },
    { name: 'Logistic regression', value: m.baseline_logistic_regression.pr_auc ?? 0, other: true },
    { name: 'Growth-rate rule', value: m.baseline_persistence.pr_auc ?? 0, other: true },
    { name: 'Random guess (base rate)', value: x.prevalence ?? 0, other: true },
  ]
  const importance = card.feature_importance.slice(0, 10).map((f) => ({ name: f.label, value: f.mean_abs_shap }))

  return (
    <>
      <div className="stats">
        <div className="stat">
          <div className="label">ROC-AUC</div>
          <div className="value">{x.roc_auc?.toFixed(3)}</div>
          <div className="note">held-out weeks</div>
        </div>
        <div className="stat">
          <div className="label">Average precision</div>
          <div className="value">{x.pr_auc?.toFixed(3)}</div>
          <div className="note">base rate {formatPercent(x.prevalence, 1)}</div>
        </div>
        <div className="stat">
          <div className="label">Outbreaks in top 10%</div>
          <div className="value">{formatPercent(x.capture_top_10pct)}</div>
          <div className="note">of all outbreaks</div>
        </div>
        <div className="stat">
          <div className="label">Held-out rows</div>
          <div className="value">{formatCount(m.test_rows)}</div>
          <div className="note">country-weeks</div>
        </div>
      </div>
      <p className="sub">
        Predicts whether {m.definition}. Trained on data up to {formatDate(card.train_end)}; every figure here is measured on{' '}
        {formatDate(m.test_period[0])} to {formatDate(m.test_period[1])}, which the model never saw.
      </p>

      <h3>Average precision against simpler approaches</h3>
      <Bars rows={comparison} max={Math.max(...comparison.map((r) => r.value))} format={(v) => v.toFixed(3)} />

      <h3>What drives the predictions (mean |SHAP|)</h3>
      <Bars rows={importance} max={Math.max(...importance.map((r) => r.value))} format={(v) => v.toFixed(2)} />

      <h3>By disease</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Disease</th>
            <th scope="col" className="num">Rows</th>
            <th scope="col" className="num">Outbreaks</th>
            <th scope="col" className="num">ROC-AUC</th>
            <th scope="col" className="num">Avg precision</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(m.by_disease).map(([code, d]) => (
            <tr key={code}>
              <td>{names.get(code) ?? code}</td>
              <td className="num">{formatCount(d.n)}</td>
              <td className="num">{formatCount(d.positives)}</td>
              <td className="num">{d.roc_auc?.toFixed(3) ?? '–'}</td>
              <td className="num">{d.pr_auc?.toFixed(3) ?? '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Stability over time (re-trained before each year, tested on that year)</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Test year</th>
            <th scope="col" className="num">Training rows</th>
            <th scope="col" className="num">Outbreaks</th>
            <th scope="col" className="num">ROC-AUC</th>
            <th scope="col" className="num">Avg precision</th>
          </tr>
        </thead>
        <tbody>
          {m.rolling_origin.map((fold) => (
            <tr key={fold.test_year}>
              <td>{fold.test_year}</td>
              <td className="num">{formatCount(fold.train_rows)}</td>
              <td className="num">{formatCount(fold.positives)}</td>
              <td className="num">{fold.roc_auc.toFixed(3)}</td>
              <td className="num">{fold.pr_auc.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
