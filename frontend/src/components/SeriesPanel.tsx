import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { RiskHistoryPoint } from '../api'
import { formatCount, formatDate, formatMonth, formatPercent } from '../format'
import { DataTable } from './DataTable'

export interface WeekPoint {
  week_start: string
  new_cases: number
  new_deaths: number
}

interface TipProps {
  active?: boolean
  label?: string | number
  payload?: ReadonlyArray<{ value?: number | string; name?: string | number; color?: string }>
  format: (value: number) => string
}

/** One tooltip listing every series at the hovered week: value first, series name second. */
function ChartTip({ active, label, payload, format }: TipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tip">
      <div className="when">Week of {formatDate(String(label))}</div>
      {payload.map((item) => (
        <div className="line" key={String(item.name)}>
          <i className="key" style={{ background: item.color }} />
          <b>{format(Number(item.value))}</b>
          <span>{item.name}</span>
        </div>
      ))}
    </div>
  )
}

const AXIS = { stroke: 'var(--axis)' }
const MARGIN = { top: 6, right: 12, bottom: 0, left: 0 }

function WeeklyArea({ data, dataKey, name, colour, week }: { data: WeekPoint[]; dataKey: keyof WeekPoint; name: string; colour: string; week: string | undefined }) {
  return (
    <div className="chart" style={{ height: 190 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={MARGIN}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="week_start" tickFormatter={formatMonth} minTickGap={56} tickLine={false} axisLine={AXIS} />
          <YAxis tickFormatter={formatCount} width={48} tickLine={false} axisLine={false} />
          <Tooltip content={<ChartTip format={formatCount} />} cursor={{ stroke: 'var(--ink-2)', strokeWidth: 1 }} isAnimationActive={false} />
          {week && <ReferenceLine x={week} stroke="var(--ink-2)" strokeWidth={1} />}
          <Area type="monotone" dataKey={dataKey} name={name} stroke={colour} strokeWidth={2} fill={colour} fillOpacity={0.1} dot={false} activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

interface DotProps {
  cx?: number
  cy?: number
  index?: number
  payload?: RiskHistoryPoint
}

/** Marks the weeks that were in fact followed by an outbreak. */
function OutcomeDot({ cx, cy, index, payload }: DotProps) {
  if (payload?.outcome !== 1 || cx === undefined || cy === undefined) return <g key={index} />
  return <circle key={index} cx={cx} cy={cy} r={4} fill="var(--series-2)" stroke="var(--surface)" strokeWidth={2} />
}

interface Props {
  title: string
  series: WeekPoint[]
  risk: RiskHistoryPoint[] | undefined
  week: string | undefined
}

/** Weekly cases and deaths as two small charts on separate axes, plus the model's risk history. */
export function SeriesPanel({ title, series, risk, week }: Props) {
  const hasDeaths = series.some((p) => p.new_deaths > 0)
  return (
    <>
      <div className="chart-title">Weekly new cases</div>
      <WeeklyArea data={series} dataKey="new_cases" name="cases" colour="var(--series-1)" week={week} />
      {hasDeaths ? (
        <>
          <div className="chart-title">Weekly new deaths</div>
          <WeeklyArea data={series} dataKey="new_deaths" name="deaths" colour="var(--series-2)" week={week} />
        </>
      ) : (
        <p className="note">This source does not report deaths.</p>
      )}
      {risk && risk.length > 0 && (
        <>
          <div className="chart-title">Predicted outbreak probability (next 4 weeks)</div>
          <div className="chart" style={{ height: 170 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={risk} margin={MARGIN}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="week_start" tickFormatter={formatMonth} minTickGap={56} tickLine={false} axisLine={AXIS} />
                <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={(v: number) => formatPercent(v)} width={48} tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTip format={(v) => formatPercent(v)} />} cursor={{ stroke: 'var(--ink-2)', strokeWidth: 1 }} isAnimationActive={false} />
                {week && <ReferenceLine x={week} stroke="var(--ink-2)" strokeWidth={1} />}
                <Line type="monotone" dataKey="risk_probability" name="probability" stroke="var(--series-1)" strokeWidth={2} dot={OutcomeDot} activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="legend">
            <span>
              <i className="swatch" style={{ background: 'var(--series-1)', height: 2, borderRadius: 1 }} />
              Predicted probability
            </span>
            <span>
              <i className="swatch" style={{ background: 'var(--series-2)', borderRadius: '50%', width: 9, height: 9 }} />
              An outbreak did follow
            </span>
          </div>
        </>
      )}
      <details>
        <summary>View as table</summary>
        <DataTable
          rows={[...series].reverse().slice(0, 104)}
          rowKey={(r) => r.week_start}
          columns={[
            { header: `Week (${title})`, cell: (r) => formatDate(r.week_start) },
            { header: 'New cases', cell: (r) => formatCount(r.new_cases), numeric: true },
            { header: 'New deaths', cell: (r) => formatCount(r.new_deaths), numeric: true },
          ]}
        />
      </details>
    </>
  )
}
