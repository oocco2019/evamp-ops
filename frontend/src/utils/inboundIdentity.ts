export interface InboundIdentifiers {
  oc_inbound_number?: string | null
  seller_inbound_number?: string | null
}

function normIdentifier(value: string | null | undefined): string {
  return (value ?? '').trim()
}

export function inboundIdentifiersMatch(row: InboundIdentifiers, target: InboundIdentifiers): boolean {
  const rowOc = normIdentifier(row.oc_inbound_number)
  const rowSeller = normIdentifier(row.seller_inbound_number)
  const targetOc = normIdentifier(target.oc_inbound_number)
  const targetSeller = normIdentifier(target.seller_inbound_number)

  if (targetOc && targetSeller) {
    return rowOc === targetOc && rowSeller === targetSeller
  }
  if (targetOc) return rowOc === targetOc
  if (targetSeller) return rowSeller === targetSeller
  return false
}

export function shouldCancelEmptyOverrideBlur(draft: string, initial: string): boolean {
  return draft.trim() === '' && initial.trim() !== ''
}
