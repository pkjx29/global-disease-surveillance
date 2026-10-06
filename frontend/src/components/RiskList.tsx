import type { RiskRow } from '../api'
import { formatCount, formatGrowth, formatPercent } from '../format'
import { RiskBadge } from './Badge'

interface Props {
  rows: RiskRow[]
  selected: string | null
  onSelect: (iso3: string) => void
  limit?: number
}

/** Countries ranked by the model's probability of an outbreak, with the main driver of each score. */
export function RiskList({ rows, selected, onSelect, limit = 8 }: Props) {
  if (rows.length === 0) {
    return <p className="empty">The model has no scores for this week. Scores start after its training cut-off.</p>
  }
  return (
    <ol className="risk-list">
      {rows.slice(0, limit).map((row) => {
        const driver = row.top_drivers[0]
        return (
          <li key={row.iso3}>
            <button type="button" className="row-button" aria-current={row.iso3 === selected} onClick={() => onSelect(row.iso3)}>
              <div className="risk-top">
                <span className="risk-name">{row.country}</span>
                <RiskBadge level={row.risk_level} />
              </div>
              <div className="meter" role="img" aria-label={`Outbreak probability ${formatPercent(row.risk_probability)}`}>
                <div style={{ width: `${Math.max(2, row.risk_probability * 100)}%` }} />
              </div>
              <div className="risk-meta">
                <span>
                  {formatPercent(row.risk_probability)} · {formatCount(row.cases_4w)} cases · {formatGrowth(row.growth_4w)}
                </span>
                {driver && (
                  <span>
                    {driver.effect === 'raises' ? '↑' : '↓'} {driver.label}
                  </span>
                )}
              </div>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
