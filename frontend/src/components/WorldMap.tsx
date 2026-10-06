import type { GeoJSON as LeafletGeoJSON, Layer, LeafletMouseEvent, Path, PathOptions } from 'leaflet'
import { useEffect, useMemo, useRef } from 'react'
import { GeoJSON, MapContainer } from 'react-leaflet'
import type { CountryCollection, MapRow, RiskLevel } from '../api'
import { formatCount, formatGrowth, formatPercent, formatRate } from '../format'
import { binIndex, binLabels, quantileBreaks } from '../scale'
import { RiskBadge } from './Badge'
import { DataTable } from './DataTable'
import { METRIC_LABELS, type Metric } from '../metrics'

const SEQUENTIAL = ['var(--seq-0)', 'var(--seq-1)', 'var(--seq-2)', 'var(--seq-3)', 'var(--seq-4)']
const RISK_COLOURS: Record<RiskLevel, string> = {
  Low: 'var(--risk-low)',
  Moderate: 'var(--warning)',
  High: 'var(--serious)',
  Critical: 'var(--critical)',
}
const RISK_ORDER: RiskLevel[] = ['Low', 'Moderate', 'High', 'Critical']

interface Props {
  countries: CountryCollection
  rows: MapRow[]
  metric: Metric
  selected: string | null
  onSelect: (iso3: string) => void
}

function metricValue(row: MapRow | undefined, metric: Metric): number | null {
  if (!row) return null
  return metric === 'cases_4w' ? row.cases_4w : metric === 'incidence_4w' ? row.incidence_4w : row.risk_probability
}

/** Tooltip built from DOM nodes (textContent), since country names arrive from the API. */
function tooltipNode(name: string, row: MapRow | undefined): HTMLElement {
  const root = document.createElement('div')
  const title = document.createElement('div')
  title.className = 'tip-title'
  title.textContent = name
  root.append(title)
  const lines: [string, string][] = row
    ? [
        ['Cases, last 4 weeks', formatCount(row.cases_4w)],
        ['Per 100k people', formatRate(row.incidence_4w)],
        ['Change vs previous 4 weeks', formatGrowth(row.growth_4w)],
        ['Outbreak risk', row.risk_probability === null ? 'not scored' : `${formatPercent(row.risk_probability)} (${row.risk_level})`],
      ]
    : [['No reported cases', '']]
  for (const [label, value] of lines) {
    const line = document.createElement('div')
    line.className = 'tip-row'
    const key = document.createElement('span')
    key.textContent = label
    const val = document.createElement('b')
    val.textContent = value
    line.append(key, val)
    root.append(line)
  }
  return root
}

/** World choropleth. Sequential single-hue ramp for magnitudes, status colours for risk level. */
export function WorldMap({ countries, rows, metric, selected, onSelect }: Props) {
  const byIso = useMemo(() => new Map(rows.map((r) => [r.iso3, r])), [rows])
  const breaks = useMemo(
    () => (metric === 'risk' ? [] : quantileBreaks(rows.map((r) => metricValue(r, metric) ?? 0))),
    [rows, metric],
  )
  const layerRef = useRef<LeafletGeoJSON | null>(null)

  const styleFor = (iso3: string): PathOptions => {
    const row = byIso.get(iso3)
    let fill = 'var(--no-data)'
    if (metric === 'risk') {
      if (row?.risk_level) fill = RISK_COLOURS[row.risk_level]
    } else {
      const bin = binIndex(metricValue(row, metric), breaks)
      if (bin >= 0) fill = SEQUENTIAL[Math.min(bin + (SEQUENTIAL.length - breaks.length - 1), SEQUENTIAL.length - 1)]
    }
    const isSelected = iso3 === selected
    return { fillColor: fill, fillOpacity: 1, color: isSelected ? 'var(--ink)' : 'var(--surface)', weight: isSelected ? 2 : 0.6 }
  }

  // Leaflet layers live outside React: keep the latest closures reachable from their event handlers.
  const live = useRef({ styleFor, byIso, onSelect })
  useEffect(() => {
    live.current = { styleFor, byIso, onSelect }
    layerRef.current?.setStyle((feature) => styleFor(String(feature?.id)))
  })

  const onEachFeature = (feature: GeoJSON.Feature, layer: Layer) => {
    const iso3 = String(feature.id)
    const name = String(feature.properties?.name ?? iso3)
    layer.bindTooltip(() => tooltipNode(name, live.current.byIso.get(iso3)), { sticky: true, className: 'map-tooltip', opacity: 1 })
    layer.on({
      click: () => live.current.onSelect(iso3),
      mouseover: (event: LeafletMouseEvent) => (event.target as Path).setStyle({ weight: 2, color: 'var(--ink)' }).bringToFront(),
      mouseout: (event: LeafletMouseEvent) => (event.target as Path).setStyle(live.current.styleFor(iso3)),
    })
  }

  const labels = binLabels(breaks, metric === 'cases_4w' ? formatCount : formatRate)
  const offset = SEQUENTIAL.length - labels.length
  const tableRows = [...rows].sort((a, b) => (metricValue(b, metric) ?? -1) - (metricValue(a, metric) ?? -1))

  return (
    <>
      <MapContainer
        className="map"
        center={[22, 12]}
        zoom={1.6}
        minZoom={1}
        maxZoom={6}
        zoomSnap={0.2}
        scrollWheelZoom={false}
        attributionControl={false}
        maxBounds={[[-62, -200], [86, 200]]}
      >
        <GeoJSON ref={layerRef} data={countries as GeoJSON.FeatureCollection} style={(f) => styleFor(String(f?.id))} onEachFeature={onEachFeature} />
      </MapContainer>
      <div className="legend" aria-label={`Legend: ${METRIC_LABELS[metric]}`}>
        {metric === 'risk'
          ? RISK_ORDER.map((level) => (
              <span key={level}>
                <i className="swatch" style={{ background: RISK_COLOURS[level] }} />
                {level}
              </span>
            ))
          : labels.map((label, i) => (
              <span key={label}>
                <i className="swatch" style={{ background: SEQUENTIAL[i + offset] }} />
                {label}
              </span>
            ))}
        <span>
          <i className="swatch" style={{ background: 'var(--no-data)', border: '1px solid var(--axis)' }} />
          {metric === 'risk' ? 'Not scored' : 'No reported cases'}
        </span>
      </div>
      <details>
        <summary>View as table</summary>
        <DataTable
          rows={tableRows}
          rowKey={(r) => r.iso3}
          columns={[
            { header: 'Country', cell: (r) => r.country },
            { header: 'Cases (4 wk)', cell: (r) => formatCount(r.cases_4w), numeric: true },
            { header: 'Per 100k', cell: (r) => formatRate(r.incidence_4w), numeric: true },
            { header: 'Change', cell: (r) => formatGrowth(r.growth_4w), numeric: true },
            { header: 'Risk', cell: (r) => (r.risk_probability === null ? '–' : formatPercent(r.risk_probability)), numeric: true },
            { header: 'Level', cell: (r) => <RiskBadge level={r.risk_level} /> },
          ]}
        />
      </details>
    </>
  )
}
