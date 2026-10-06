import type { Disease } from '../api'
import { formatDate } from '../format'
import { METRIC_LABELS, type Metric } from '../metrics'

interface Props {
  diseases: Disease[]
  disease: string
  onDisease: (code: string) => void
  metric: Metric
  onMetric: (metric: Metric) => void
  weeks: string[]
  weekIndex: number
  onWeekIndex: (index: number) => void
}

/** The single filter row: everything below it re-renders against this selection. */
export function FilterBar({ diseases, disease, onDisease, metric, onMetric, weeks, weekIndex, onWeekIndex }: Props) {
  const last = weeks.length - 1
  return (
    <section className="filters" aria-label="Filters">
      <div className="field">
        <span className="label">Disease</span>
        <div className="segmented" role="group" aria-label="Disease">
          {diseases.map((d) => (
            <button key={d.code} type="button" aria-pressed={d.code === disease} onClick={() => onDisease(d.code)}>
              {d.name}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="metric">Map shows</label>
        <select id="metric" value={metric} onChange={(e) => onMetric(e.target.value as Metric)}>
          {Object.entries(METRIC_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field week">
        <label htmlFor="week">Week</label>
        <div className="week-row">
          <input
            id="week"
            type="range"
            min={0}
            max={Math.max(last, 0)}
            value={Math.max(weekIndex, 0)}
            onChange={(e) => onWeekIndex(Number(e.target.value))}
            aria-valuetext={weeks[weekIndex] ? `Week of ${formatDate(weeks[weekIndex])}` : undefined}
          />
          <strong>{weeks[weekIndex] ? `Week of ${formatDate(weeks[weekIndex])}` : '–'}</strong>
          <button type="button" className="link" disabled={weekIndex === last} onClick={() => onWeekIndex(last)}>
            Latest
          </button>
        </div>
      </div>
    </section>
  )
}
