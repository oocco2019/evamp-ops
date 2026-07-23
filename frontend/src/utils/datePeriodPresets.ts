export type PeriodPreset = 'yesterday' | '7d' | '1m' | '3m' | '6m' | '1y' | 'custom'

export const PERIOD_DAYS: Record<Exclude<PeriodPreset, 'yesterday' | 'custom'>, number> = {
  '7d': 7,
  '1m': 30,
  '3m': 90,
  '6m': 180,
  '1y': 365,
}

export function formatLocalDate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function todayIso(): string {
  return formatLocalDate(new Date())
}

export function offsetDaysFromToday(daysAgo: number): string {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return formatLocalDate(d)
}

/** Last fully completed calendar day (yesterday in local time). */
export function latestCompleteDayIso(): string {
  return offsetDaysFromToday(1)
}

/**
 * n complete calendar days ending yesterday (not today).
 * e.g. on 12 Jul, 7d → 5 Jul–11 Jul.
 */
export function completeDaysRange(n: number): { from: string; to: string } {
  return {
    from: offsetDaysFromToday(n),
    to: latestCompleteDayIso(),
  }
}

export function periodPresetRange(preset: PeriodPreset): { from: string; to: string } | null {
  if (preset === 'custom') return null
  if (preset === 'yesterday') {
    const y = latestCompleteDayIso()
    return { from: y, to: y }
  }
  return completeDaysRange(PERIOD_DAYS[preset])
}

/** Default Sales Analytics / Order Details window: last 90 complete days. */
export function defaultAnalyticsRange(): { from: string; to: string } {
  return completeDaysRange(90)
}
