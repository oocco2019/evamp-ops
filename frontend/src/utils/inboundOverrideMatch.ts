type InboundOverrideIdentity = {
  oc_inbound_number?: string | null
  seller_inbound_number?: string | null
}

const norm = (value: string | null | undefined): string => (value ?? '').trim().toLowerCase()

export function matchesInboundOverrideIdentity(
  row: InboundOverrideIdentity,
  identity: InboundOverrideIdentity
): boolean {
  const oc = norm(identity.oc_inbound_number)
  const seller = norm(identity.seller_inbound_number)
  const rowOc = norm(row.oc_inbound_number)
  const rowSeller = norm(row.seller_inbound_number)

  if (oc && seller) return rowOc === oc && rowSeller === seller
  if (oc) return rowOc === oc
  if (seller) return rowSeller === seller
  return false
}
