import { describe, expect, it } from 'vitest'
import { binIndex, binLabels, quantileBreaks } from './scale'

describe('quantileBreaks', () => {
  it('splits positive values into equal-sized groups', () => {
    const values = Array.from({ length: 100 }, (_, i) => i + 1)
    expect(quantileBreaks(values)).toEqual([21, 41, 61, 81])
  })

  it('ignores zeros and collapses duplicate thresholds', () => {
    expect(quantileBreaks([0, 0, 5, 5, 5, 5, 5])).toEqual([5])
    expect(quantileBreaks([0, 0])).toEqual([])
  })
})

describe('binIndex', () => {
  const breaks = [10, 20, 30, 40]
  it('places values in the right class', () => {
    expect(binIndex(5, breaks)).toBe(0)
    expect(binIndex(10, breaks)).toBe(1)
    expect(binIndex(39.9, breaks)).toBe(3)
    expect(binIndex(1000, breaks)).toBe(4)
  })
  it('returns -1 for zero or missing', () => {
    expect(binIndex(0, breaks)).toBe(-1)
    expect(binIndex(null, breaks)).toBe(-1)
  })
})

describe('binLabels', () => {
  it('describes each class', () => {
    expect(binLabels([10, 20], String)).toEqual(['< 10', '10 – 20', '≥ 20'])
  })
})
