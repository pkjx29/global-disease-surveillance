// Typed client for the FastAPI backend.

const BASE: string = import.meta.env.VITE_API_BASE ?? '/api/v1'

type Params = Record<string, string | number | null | undefined>

async function get<T>(path: string, params: Params = {}): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.size ? `?${query}` : ''
  const response = await fetch(`${BASE}${path}${suffix}`)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${path}`)
  return (await response.json()) as T
}

export interface Disease {
  code: string
  name: string
  pathogen: string | null
  transmission: string | null
  source_name: string
  source_url: string
  licence: string | null
  first_week: string | null
  last_week: string | null
  countries: number
  total_cases: number
}

export interface GlobalWeek {
  week_start: string
  new_cases: number
  new_deaths: number
  countries_reporting: number
}

export interface MapRow {
  iso3: string
  country: string
  new_cases: number
  new_deaths: number
  cases_4w: number
  incidence_4w: number | null
  growth_4w: number | null
  risk_probability: number | null
  risk_level: RiskLevel | null
}

export interface MapResponse {
  disease: string
  week_start: string
  rows: MapRow[]
}

export interface SeriesPoint {
  week_start: string
  new_cases: number
  new_deaths: number
  incidence_per_100k: number | null
  reported: boolean
}

export type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Critical'

export interface Driver {
  feature: string
  label: string
  effect: 'raises' | 'lowers'
  shap: number
  value: number | null
}

export interface RiskRow {
  disease: string
  iso3: string
  country: string
  who_region: string | null
  week_start: string
  risk_probability: number
  risk_level: RiskLevel
  cases_4w: number
  incidence_4w: number | null
  growth_4w: number | null
  top_drivers: Driver[]
  outcome: number | null
}

export interface RiskHistoryPoint {
  week_start: string
  risk_probability: number
  risk_level: RiskLevel
  cases_4w: number
  outcome: number | null
}

export interface Metrics {
  n: number
  positives: number
  prevalence?: number
  roc_auc?: number
  pr_auc?: number
  capture_top_10pct?: number
  precision_at_high?: number | null
  recall_at_high?: number
}

export interface ModelCard {
  run_id: number
  trained_at: string
  algorithm: string
  horizon_weeks: number
  train_end: string
  params: Record<string, unknown>
  metrics: {
    definition: string
    train_rows: number
    test_rows: number
    test_period: [string, string]
    xgboost: Metrics
    by_disease: Record<string, Metrics>
    baseline_persistence: Metrics
    baseline_logistic_regression: Metrics
    rolling_origin: { test_year: number; train_rows: number; n: number; positives: number; roc_auc: number; pr_auc: number }[]
  }
  feature_importance: { feature: string; label: string; gain: number; mean_abs_shap: number }[]
}

export interface Alert {
  disease: string
  iso3: string
  country: string | null
  window_start: string
  window_end: string
  cases: number
  baseline_mean: number
  baseline_std: number
  z_score: number
  severity: 'elevated' | 'high' | 'critical'
  detected_at: string
}

export interface StreamStatus {
  windows_processed: number
  series_tracked: number
  latest_window_end: string | null
  alerts_total: number
  last_alert_at: string | null
}

export interface CountryFeature {
  type: 'Feature'
  id: string
  properties: { iso3: string; name: string; continent: string | null; who_region: string | null; population: number | null }
  geometry: GeoJSON.Geometry
}

export interface CountryCollection {
  type: 'FeatureCollection'
  features: CountryFeature[]
}

export const api = {
  diseases: () => get<Disease[]>('/diseases'),
  countries: () => get<CountryCollection>('/geo/countries'),
  globalSeries: (disease: string) => get<GlobalWeek[]>('/cases/global', { disease }),
  map: (disease: string, week: string) => get<MapResponse>('/cases/map', { disease, week }),
  timeseries: (disease: string, iso3: string) => get<SeriesPoint[]>('/cases/timeseries', { disease, iso3 }),
  riskScores: (disease: string, week: string) => get<RiskRow[]>('/risk/scores', { disease, week, limit: 300 }),
  riskHistory: (disease: string, iso3: string) => get<RiskHistoryPoint[]>('/risk/history', { disease, iso3 }),
  modelCard: () => get<ModelCard>('/risk/model'),
  alerts: (limit = 40) => get<Alert[]>('/alerts', { limit }),
  streamStatus: () => get<StreamStatus>('/stream/status'),
  alertStreamUrl: `${BASE}/alerts/stream`,
}
