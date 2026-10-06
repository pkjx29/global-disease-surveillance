import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from './api'
import { FilterBar } from './components/FilterBar'
import { KpiRow } from './components/KpiRow'
import { LiveAlerts } from './components/LiveAlerts'
import { ModelPanel } from './components/ModelPanel'
import { RiskList } from './components/RiskList'
import { SeriesPanel } from './components/SeriesPanel'
import { WorldMap } from './components/WorldMap'
import { formatDate } from './format'
import { METRIC_LABELS, type Metric } from './metrics'

export default function App() {
  const [disease, setDisease] = useState('covid19')
  const [metric, setMetric] = useState<Metric>('incidence_4w')
  const [pickedWeek, setPickedWeek] = useState<number | null>(null) // null = follow the latest week
  const [selected, setSelected] = useState<string | null>(null)

  const diseases = useQuery({ queryKey: ['diseases'], queryFn: api.diseases })
  const countries = useQuery({ queryKey: ['countries'], queryFn: api.countries, staleTime: Infinity })
  const modelCard = useQuery({ queryKey: ['model'], queryFn: api.modelCard })
  const status = useQuery({ queryKey: ['stream-status'], queryFn: api.streamStatus, refetchInterval: 5000 })
  const globalSeries = useQuery({ queryKey: ['global', disease], queryFn: () => api.globalSeries(disease), placeholderData: keepPreviousData })

  const current = diseases.data?.find((d) => d.code === disease)
  // the slider stops at the last week with broad reporting; later weeks cover only a few countries
  const lastWeek = current?.last_week
  const series = useMemo(() => (globalSeries.data ?? []).filter((w) => !lastWeek || w.week_start <= lastWeek), [globalSeries.data, lastWeek])
  const weeks = useMemo(() => series.map((w) => w.week_start), [series])
  const weekIndex = pickedWeek === null ? weeks.length - 1 : Math.min(pickedWeek, weeks.length - 1)
  const week = weeks[weekIndex]

  const map = useQuery({ queryKey: ['map', disease, week], queryFn: () => api.map(disease, week), enabled: !!week, placeholderData: keepPreviousData })
  const risk = useQuery({ queryKey: ['risk', disease, week], queryFn: () => api.riskScores(disease, week), enabled: !!week, placeholderData: keepPreviousData })
  const country = useQuery({ queryKey: ['series', disease, selected], queryFn: () => api.timeseries(disease, selected!), enabled: !!selected, retry: false })
  const history = useQuery({ queryKey: ['risk-history', disease, selected], queryFn: () => api.riskHistory(disease, selected!), enabled: !!selected })

  const selectedName = countries.data?.features.find((f) => f.id === selected)?.properties.name ?? selected
  const failed = diseases.isError || globalSeries.isError
  const changeDisease = (code: string) => {
    setDisease(code)
    setPickedWeek(null)
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Global Disease Surveillance</h1>
          <p>Weekly case reports, outbreak-risk predictions and real-time anomaly alerts</p>
        </div>
        <span className="status">
          <i className={`status-dot ${failed ? 'down' : diseases.data ? 'ok' : ''}`} />
          {failed ? 'API unreachable' : diseases.data ? 'API connected' : 'Connecting'}
        </span>
      </header>

      {failed && <p className="card empty">The API did not respond. Start the backend (see the README) and reload.</p>}

      <FilterBar
        diseases={diseases.data ?? []}
        disease={disease}
        onDisease={changeDisease}
        metric={metric}
        onMetric={setMetric}
        weeks={weeks}
        weekIndex={weekIndex}
        onWeekIndex={(index) => setPickedWeek(index === weeks.length - 1 ? null : index)}
      />

      <KpiRow week={series[weekIndex]} previous={series[weekIndex - 1]} riskRows={risk.data} alertsTotal={status.data?.alerts_total} />

      <div className="grid-main">
        <section className={`card${map.isPlaceholderData ? ' stale' : ''}`}>
          <div className="card-head">
            <div>
              <h2>{current?.name ?? 'Disease'} by country</h2>
              <p className="sub">
                {METRIC_LABELS[metric]}, week of {formatDate(week)}. Select a country for its trend.
              </p>
            </div>
          </div>
          {countries.data && map.data ? (
            <WorldMap countries={countries.data} rows={map.data.rows} metric={metric} selected={selected} onSelect={setSelected} />
          ) : (
            <p className="empty">Loading map…</p>
          )}
        </section>

        <section className={`card${risk.isPlaceholderData ? ' stale' : ''}`}>
          <div className="card-head">
            <div>
              <h2>Highest outbreak risk</h2>
              <p className="sub">Probability that cases at least double in the next 4 weeks</p>
            </div>
          </div>
          <RiskList rows={risk.data ?? []} selected={selected} onSelect={setSelected} />
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>
              {selected ? selectedName : 'Worldwide'} · {current?.name ?? ''}
            </h2>
            <p className="sub">{selected ? 'Country trend and model back-test' : 'All reporting countries combined'}</p>
          </div>
          {selected && (
            <button type="button" className="link" onClick={() => setSelected(null)}>
              Show worldwide
            </button>
          )}
        </div>
        {selected && country.isError ? (
          <p className="empty">
            {selectedName} has no {current?.name} reports in this dataset.
          </p>
        ) : (
          <SeriesPanel
            title={selected ? String(selectedName) : 'worldwide'}
            series={selected ? (country.data ?? []) : series}
            risk={selected ? history.data : undefined}
            week={week}
          />
        )}
      </section>

      <div className="grid-half">
        <section className="card">
          <div className="card-head">
            <div>
              <h2>Outbreak-risk model</h2>
              <p className="sub">{modelCard.data?.algorithm ?? 'XGBoost'}, validated on later data than it was trained on</p>
            </div>
          </div>
          {modelCard.data ? <ModelPanel card={modelCard.data} diseases={diseases.data ?? []} /> : <p className="empty">No trained model yet.</p>}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <h2>Real-time alerts</h2>
              <p className="sub">Apache Flink, weekly event-time windows over the Kafka stream</p>
            </div>
          </div>
          <LiveAlerts diseases={diseases.data ?? []} status={status.data} />
        </section>
      </div>

      <footer className="footer">
        <span>
          Sources:{' '}
          {(diseases.data ?? []).map((d, i) => (
            <span key={d.code}>
              {i > 0 && ' · '}
              <a href={d.source_url}>{d.source_name}</a> ({d.licence})
            </span>
          ))}
          {' · '}Natural Earth boundaries (public domain)
        </span>
        <span>Figures are as reported by national authorities; reporting completeness varies by country and week.</span>
      </footer>
    </div>
  )
}
