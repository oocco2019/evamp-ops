/**
 * Stock chart: build a full daily series for [from, to] (local dates), forward-filling from the last
 * sample on or before end of each day (points from GET /inventory-history — movement-derived).
 */
function parseISODateLocal(value: string): Date | null {
  if (!value) return null
  const [y, m, d] = value.split('-').map((v) => Number(v))
  if (!y || !m || !d) return null
  return new Date(y, m - 1, d)
}

function formatLocalDateFromDate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function buildDailyStockLevelsFromHistory(
  rawPoints: Array<{ recorded_at: string; available: number; in_transit: number }>,
  fromIso: string,
  toIso: string,
  opening: { available?: number; in_transit?: number } = {},
): Array<{ period: string; available: number; in_transit: number }> {
  const start = parseISODateLocal(fromIso)
  const end = parseISODateLocal(toIso)
  if (!start || !end || start > end) return []

  const sorted = [...rawPoints]
    .filter((p) => (p.recorded_at || '').trim())
    .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime())

  const out: Array<{ period: string; available: number; in_transit: number }> = []
  const cur = new Date(start.getTime())
  const openingAvailable = opening.available ?? 0
  const openingInTransit = opening.in_transit ?? 0
  while (cur <= end) {
    const dayEnd = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate(), 23, 59, 59, 999).getTime()
    let lastA = openingAvailable
    let lastT = openingInTransit
    for (let i = 0; i < sorted.length; i++) {
      const t = new Date(sorted[i].recorded_at).getTime()
      if (t <= dayEnd) {
        lastA = sorted[i].available
        lastT = sorted[i].in_transit
      }
    }
    out.push({
      period: formatLocalDateFromDate(cur),
      available: lastA,
      in_transit: lastT,
    })
    cur.setDate(cur.getDate() + 1)
  }
  return out
}
