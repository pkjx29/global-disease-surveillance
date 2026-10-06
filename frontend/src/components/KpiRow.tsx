import type { GlobalWeek, RiskRow } from '../api'
import { formatCount, formatDelta } from '../format'

interface Props {
  week: GlobalWeek | undefined
  previous: GlobalWeek | undefined
  riskRows: RiskRow[] | undefined
  alertsTotal: number | undefined
}

function Delta({ current, previous }: { current: number; previous: number | undefined }) {
  const text = previous === undefined ? null : formatDelta(current, previous)
  if (!text) return <div className="delta">no previous week</div>
  const rising = current >= (previous ?? 0)
  return (
    <div className="delta">
      <b className={rising ? 'up' : 'down'}>
        {rising ? '▲' : '▼'} {text}
      </b>{' '}
      vs previous week
    </div>
  )
}

/** Headline figures for the selected disease and week. */
export function KpiRow({ week, previous, riskRows, alertsTotal }: Props) {
  const highRisk = riskRows?.filter((r) => r.risk_level === 'High' || r.risk_level === 'Critical').length
  return (
    <section className="kpis" aria-label="Key figures">
      <div className="card kpi">
        <div className="label">New cases this week</div>
        <div className="value">{formatCount(week?.new_cases)}</div>
        {week && <Delta current={week.new_cases} previous={previous?.new_cases} />}
      </div>
      <div className="card kpi">
        <div className="label">New deaths this week</div>
        <div className="value">{formatCount(week?.new_deaths)}</div>
        {week && <Delta current={week.new_deaths} previous={previous?.new_deaths} />}
      </div>
      <div className="card kpi">
        <div className="label">Countries reporting cases</div>
        <div className="value">{formatCount(week?.countries_reporting)}</div>
        <div className="delta">with at least one case</div>
      </div>
      <div className="card kpi">
        <div className="label">Countries at high risk</div>
        <div className="value">{riskRows && riskRows.length > 0 ? formatCount(highRisk) : '–'}</div>
        <div className="delta">{riskRows && riskRows.length > 0 ? `of ${riskRows.length} scored by the model` : 'no model scores for this week'}</div>
      </div>
      <div className="card kpi">
        <div className="label">Stream alerts raised</div>
        <div className="value">{formatCount(alertsTotal)}</div>
        <div className="delta">by the Flink job, all diseases</div>
      </div>
    </section>
  )
}
