// What the map can show.
export type Metric = 'incidence_4w' | 'cases_4w' | 'risk'

export const METRIC_LABELS: Record<Metric, string> = {
  incidence_4w: 'Cases per 100k (last 4 weeks)',
  cases_4w: 'Cases (last 4 weeks)',
  risk: 'Outbreak risk (next 4 weeks)',
}
