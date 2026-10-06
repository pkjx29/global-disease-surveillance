import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type Alert, type Disease, type StreamStatus } from '../api'
import { formatCount, formatDate } from '../format'
import { SeverityBadge } from './Badge'

const MAX_ALERTS = 60
const alertKey = (a: Alert) => `${a.disease}|${a.iso3}|${a.window_start}`

/** Alerts from the Flink job: loaded once, then pushed over Server-Sent Events as they are raised. */
export function LiveAlerts({ diseases, status }: { diseases: Disease[]; status: StreamStatus | undefined }) {
  const initial = useQuery({ queryKey: ['alerts'], queryFn: () => api.alerts(MAX_ALERTS) })
  const [pushed, setPushed] = useState<Alert[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const source = new EventSource(api.alertStreamUrl)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.addEventListener('alert', (event) => {
      const alert = JSON.parse((event as MessageEvent<string>).data) as Alert
      setPushed((current) => [alert, ...current.filter((a) => alertKey(a) !== alertKey(alert))].slice(0, MAX_ALERTS))
    })
    return () => source.close()
  }, [])

  const names = new Map(diseases.map((d) => [d.code, d.name]))
  const fresh = new Set(pushed.map(alertKey))
  const alerts = [...pushed, ...(initial.data ?? []).filter((a) => !fresh.has(alertKey(a)))].slice(0, MAX_ALERTS)

  return (
    <>
      <div className="stats">
        <div className="stat">
          <div className="label">Weekly windows processed</div>
          <div className="value">{formatCount(status?.windows_processed)}</div>
        </div>
        <div className="stat">
          <div className="label">Country series tracked</div>
          <div className="value">{formatCount(status?.series_tracked)}</div>
        </div>
        <div className="stat">
          <div className="label">Stream position</div>
          <div className="value" style={{ fontSize: 17, paddingTop: 5 }}>{formatDate(status?.latest_window_end)}</div>
        </div>
        <div className="stat">
          <div className="label">Push connection</div>
          <div className="value" style={{ fontSize: 17, paddingTop: 5 }}>
            <span className="status">
              <i className={`status-dot ${connected ? 'ok' : 'down'}`} />
              {connected ? 'Live' : 'Reconnecting'}
            </span>
          </div>
        </div>
      </div>
      {alerts.length === 0 ? (
        <p className="empty">No alerts yet. Start the stream (Kafka producer and Flink job) to see them arrive here.</p>
      ) : (
        <ul className="alerts" aria-live="polite">
          {alerts.map((alert) => (
            <li key={alertKey(alert)} className={`alert${fresh.has(alertKey(alert)) ? ' fresh' : ''}`}>
              <SeverityBadge severity={alert.severity} />
              <div className="what">
                <b>{alert.country ?? alert.iso3}</b> · {names.get(alert.disease) ?? alert.disease}
                <div>
                  {formatCount(alert.cases)} cases in the week of {formatDate(alert.window_start)}, against a usual {formatCount(alert.baseline_mean)}
                </div>
              </div>
              <div className="z">z = {alert.z_score.toFixed(1)}</div>
            </li>
          ))}
        </ul>
      )}
      <p className="note">
        The stream replays historical reports at accelerated speed, standing in for a live feed. Flink flags a week when cases exceed the
        previous eight weeks by three or more standard deviations.
      </p>
    </>
  )
}
