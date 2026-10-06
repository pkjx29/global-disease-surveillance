// Class breaks for the choropleth: quantiles of the positive values, so the map
// stays readable whether a disease has ten cases or ten million.

export const BIN_COUNT = 5

/** Thresholds t1..t4 splitting the positive values into five roughly equal groups. */
export function quantileBreaks(values: number[], bins = BIN_COUNT): number[] {
  const positive = values.filter((v) => v > 0).sort((a, b) => a - b)
  if (positive.length === 0) return []
  const breaks: number[] = []
  for (let i = 1; i < bins; i++) {
    const value = positive[Math.min(positive.length - 1, Math.floor((i / bins) * positive.length))]
    if (breaks.length === 0 || value > breaks[breaks.length - 1]) breaks.push(value)
  }
  return breaks
}

/** Bin index (0-based) of a value; -1 for zero / missing. */
export function binIndex(value: number | null | undefined, breaks: number[]): number {
  if (value === null || value === undefined || !(value > 0)) return -1
  let index = 0
  while (index < breaks.length && value >= breaks[index]) index++
  return index
}

/** Human-readable range of each bin, e.g. ["< 1.2", "1.2 – 5", "≥ 5"]. */
export function binLabels(breaks: number[], format: (v: number) => string): string[] {
  if (breaks.length === 0) return []
  const labels = [`< ${format(breaks[0])}`]
  for (let i = 1; i < breaks.length; i++) labels.push(`${format(breaks[i - 1])} – ${format(breaks[i])}`)
  labels.push(`≥ ${format(breaks[breaks.length - 1])}`)
  return labels
}
