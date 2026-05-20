import { describe, it, expect } from 'vitest'
import {
  buildDailyStockLevelsFromHistory,
  parseInventoryHistoryTimestampMs,
} from './inventoryHistoryFormat'

describe('buildDailyStockLevelsFromHistory', () => {
  it('outputs one row per calendar day across the range', () => {
    const pts = [
      { recorded_at: '2026-04-10T12:00:00.000Z', available: 10, in_transit: 2 },
      { recorded_at: '2026-04-12T12:00:00.000Z', available: 5, in_transit: 3 },
    ]
    const rows = buildDailyStockLevelsFromHistory(pts, '2026-04-10', '2026-04-12')
    expect(rows.length).toBe(3)
    expect(rows[0].period).toBe('2026-04-10')
    expect(rows[1].period).toBe('2026-04-11')
    expect(rows[2].period).toBe('2026-04-12')
  })

  it('forward-fills from last sample on or before each day end', () => {
    const pts = [{ recorded_at: '2026-04-11T08:00:00.000Z', available: 7, in_transit: 1 }]
    const rows = buildDailyStockLevelsFromHistory(pts, '2026-04-10', '2026-04-12')
    expect(rows[0].available).toBe(0)
    expect(rows[1].available).toBe(7)
    expect(rows[2].available).toBe(7)
  })

  it('treats backend timestamps without an offset as UTC', () => {
    expect(parseInventoryHistoryTimestampMs('2026-04-10T23:30:00')).toBe(
      Date.parse('2026-04-10T23:30:00Z')
    )
    expect(parseInventoryHistoryTimestampMs('2026-04-10T23:30:00+0200')).toBe(
      Date.parse('2026-04-10T23:30:00+0200')
    )
  })
})
