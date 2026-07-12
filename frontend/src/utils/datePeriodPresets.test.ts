import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  completeDaysRange,
  latestCompleteDayIso,
  periodPresetRange,
  todayIso,
} from './datePeriodPresets'

describe('datePeriodPresets', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('latestCompleteDayIso is yesterday', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 12, 9, 0, 0))
    expect(todayIso()).toBe('2026-07-12')
    expect(latestCompleteDayIso()).toBe('2026-07-11')
  })

  it('completeDaysRange excludes today', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 12, 9, 0, 0))
    expect(completeDaysRange(7)).toEqual({ from: '2026-07-05', to: '2026-07-11' })
    expect(completeDaysRange(90)).toEqual({ from: '2026-04-13', to: '2026-07-11' })
  })

  it('today preset includes today only', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 12, 9, 0, 0))
    expect(periodPresetRange('today')).toEqual({ from: '2026-07-12', to: '2026-07-12' })
  })

  it('rolling presets end yesterday', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 12, 9, 0, 0))
    expect(periodPresetRange('7d')).toEqual({ from: '2026-07-05', to: '2026-07-11' })
    expect(periodPresetRange('3m')).toEqual({ from: '2026-04-13', to: '2026-07-11' })
  })
})
