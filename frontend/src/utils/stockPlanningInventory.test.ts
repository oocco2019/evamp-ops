import { describe, it, expect } from 'vitest'
import { stockUnitsFromOcInventory } from './stockPlanningInventory'
import type { OCSkuInventoryRow, OCSkuMapping } from '../services/api'

function mapRow(p: Partial<OCSkuMapping> & Pick<OCSkuMapping, 'sku_code' | 'seller_skuid'>): OCSkuMapping {
  return {
    id: p.id ?? 1,
    sku_code: p.sku_code,
    seller_skuid: p.seller_skuid,
    reference_skuid: p.reference_skuid ?? '',
    mfskuid: p.mfskuid ?? 'OC1',
    service_region: p.service_region ?? 'UK',
    last_synced_at: p.last_synced_at ?? new Date().toISOString(),
  }
}

function invRow(p: Partial<OCSkuInventoryRow> & Pick<OCSkuInventoryRow, 'seller_skuid'>): OCSkuInventoryRow {
  return {
    id: p.id ?? 1,
    seller_skuid: p.seller_skuid,
    mfskuid: p.mfskuid ?? 'OC1',
    service_region: p.service_region ?? 'UK',
    available: p.available ?? 0,
    in_transit: p.in_transit ?? 0,
    received: p.received ?? 0,
    reserved_allocated: p.reserved_allocated ?? 0,
    reserved_hold: p.reserved_hold ?? 0,
    reserved_vas: p.reserved_vas ?? 0,
    suspend: p.suspend ?? 0,
    unfulfillable: p.unfulfillable ?? 0,
    sold_3m_units: p.sold_3m_units ?? 0,
    sold_1m_units: p.sold_1m_units ?? 0,
    synced_at: p.synced_at ?? new Date().toISOString(),
  }
}

describe('stockUnitsFromOcInventory', () => {
  it('sums available + in_transit per sku_code via seller_skuid', () => {
    const mappings = [mapRow({ sku_code: 'bee01', seller_skuid: 'BEE01' })]
    const inventory = [invRow({ seller_skuid: 'BEE01', available: 3, in_transit: 7 })]
    expect(stockUnitsFromOcInventory(mappings, inventory)).toEqual({ bee01: 10 }) // keyed lowercase
  })

  it('merges two seller SKUs onto same sku_code', () => {
    const mappings = [
      mapRow({ id: 1, sku_code: 'bee01', seller_skuid: 'A' }),
      mapRow({ id: 2, sku_code: 'bee01', seller_skuid: 'B' }),
    ]
    const inventory = [
      invRow({ id: 1, seller_skuid: 'A', available: 1, in_transit: 0 }),
      invRow({ id: 2, seller_skuid: 'B', available: 0, in_transit: 4 }),
    ]
    expect(stockUnitsFromOcInventory(mappings, inventory)).toEqual({ bee01: 5 })
  })

  it('ignores unmapped inventory rows', () => {
    const mappings = [mapRow({ sku_code: 'x', seller_skuid: 'ONLY' })]
    const inventory = [invRow({ seller_skuid: 'OTHER', available: 99, in_transit: 0 })]
    expect(stockUnitsFromOcInventory(mappings, inventory)).toEqual({})
  })
})
