import { describe, expect, it } from 'vitest'
import { formatCount, formatDate, formatDelta, formatGrowth, formatPercent, formatRate } from './format'

describe('formatters', () => {
  it('compacts large counts only', () => {
    expect(formatCount(1284)).toBe('1,284')
    expect(formatCount(12940)).toBe('12.9K')
    expect(formatCount(4_200_000)).toBe('4.2M')
    expect(formatCount(null)).toBe('–')
  })
  it('formats rates with sensible precision', () => {
    expect(formatRate(0.0123)).toBe('0.012')
    expect(formatRate(3.456)).toBe('3.46')
    expect(formatRate(45.67)).toBe('45.7')
  })
  it('formats deltas, growth and percentages', () => {
    expect(formatDelta(120, 100)).toBe('+20.0%')
    expect(formatDelta(80, 100)).toBe('−20.0%')
    expect(formatDelta(80, 0)).toBeNull()
    expect(formatGrowth(2.54)).toBe('×2.5')
    expect(formatPercent(0.8224, 1)).toBe('82.2%')
  })
  it('formats ISO dates in UTC', () => {
    expect(formatDate('2026-08-24')).toBe('24 Aug 2026')
  })
})
