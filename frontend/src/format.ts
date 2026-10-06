// Number and date formatting shared by every component.

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
const plain = new Intl.NumberFormat('en')
const dayMonthYear = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const monthYear = new Intl.DateTimeFormat('en-GB', { month: 'short', year: '2-digit', timeZone: 'UTC' })

/** 1284 -> "1,284", 12940 -> "12.9K", 4200000 -> "4.2M" */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  return Math.abs(value) < 10_000 ? plain.format(Math.round(value)) : compact.format(value)
}

export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  if (value === 0) return '0'
  if (value < 0.1) return value.toFixed(3)
  return value < 10 ? value.toFixed(2) : value < 100 ? value.toFixed(1) : formatCount(value)
}

export function formatPercent(fraction: number | null | undefined, digits = 0): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return '–'
  return `${(fraction * 100).toFixed(digits)}%`
}

/** Signed week-on-week change: 0.195 -> "+19.5%" */
export function formatDelta(current: number, previous: number): string | null {
  if (!previous) return null
  const change = (current - previous) / previous
  return `${change >= 0 ? '+' : '−'}${Math.abs(change * 100).toFixed(1)}%`
}

/** Growth ratio as a multiplier: 2.5 -> "×2.5" */
export function formatGrowth(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '–'
  return `×${ratio >= 10 ? ratio.toFixed(0) : ratio.toFixed(1)}`
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? dayMonthYear.format(new Date(iso)) : '–'
}

export function formatMonth(iso: string): string {
  return monthYear.format(new Date(iso))
}
