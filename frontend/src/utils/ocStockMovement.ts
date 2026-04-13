/**
 * OrangeConnex GetStockMovement (ExternalMovementDTO): quantity is the change
 * within a given inventory bucket (AVL, INTRAN, …), not “global outbound”.
 *
 * Chart “outbound fulfilled” counts **OOF (Outbound Order Fulfiled)** only — not
 * OOS (submitted), inbound, freeze, or adjustments.
 *
 * @see https://ef-open-api.apifox.cn/api-116942647
 */

/** Leading reason code: "OOF=Outbound…" or "OOF Outbound…" */
export function parseOcMovementReasonCode(reason: string | null | undefined): string | null {
  const s = (reason ?? '').trim()
  if (!s) return null
  const eq = s.match(/^([A-Z]{3})\s*=/)
  if (eq) return eq[1]
  const lead = s.match(/^([A-Z]{3})(?=\s|$|[=_-])/)
  if (lead) return lead[1]
  return null
}

const INBOUND_REASON_CODES = new Set(['IOS', 'PAC'])

/** OC code for Outbound Order Fulfiled (API spelling). */
const OUTBOUND_ORDER_FULFILLED_CODE = 'OOF'

/**
 * Movement lines for “units fulfilled” chart: OOF only, negative quantity on that line.
 */
export function isOcOutboundOrderFulfilledMovement(
  reason: string | null | undefined,
  quantity: number,
): boolean {
  if (quantity >= 0) return false

  const code = parseOcMovementReasonCode(reason)
  if (code) {
    if (INBOUND_REASON_CODES.has(code)) return false
    if (code === OUTBOUND_ORDER_FULFILLED_CODE) return true
    return false
  }

  const low = (reason ?? '').toLowerCase()
  if (low.includes('inbound order') || low.includes('put away')) return false
  // OC API typo "Fulfiled"; also standard "Fulfilled". Do not match "Submitted" (OOS).
  if (low.includes('outbound order fulfilled') || low.includes('outbound order fulfiled')) {
    return true
  }
  return false
}
