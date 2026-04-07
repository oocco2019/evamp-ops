import type { OCSkuInventoryRow, OCSkuMapping } from '../services/api'

/**
 * Map OC inventory (per seller SKU) to internal `sku_code` using mappings, then sum
 * available + in_transit per `sku_code` (multiple seller SKUs for one code sum together).
 */
export function stockUnitsFromOcInventory(
  mappings: OCSkuMapping[],
  inventory: OCSkuInventoryRow[]
): Record<string, number> {
  const sellerToSku = new Map<string, string>()
  for (const m of mappings) {
    const sk = (m.seller_skuid || '').trim()
    const sc = (m.sku_code || '').trim()
    if (!sk || !sc) continue
    if (!sellerToSku.has(sk)) sellerToSku.set(sk, sc)
  }

  const totals: Record<string, number> = {}
  for (const inv of inventory) {
    const sk = (inv.seller_skuid || '').trim()
    if (!sk) continue
    const skuCode = sellerToSku.get(sk)
    if (!skuCode) continue
    const key = skuCode.trim().toLowerCase()
    if (!key) continue
    const q = Math.max(0, (inv.available || 0) + (inv.in_transit || 0))
    totals[key] = (totals[key] ?? 0) + q
  }
  return totals
}
