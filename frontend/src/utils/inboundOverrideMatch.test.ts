import { describe, expect, it } from 'vitest'

import { matchesInboundOverrideIdentity } from './inboundOverrideMatch'

describe('matchesInboundOverrideIdentity', () => {
  it('requires both inbound identifiers to match when both are available', () => {
    const identity = { oc_inbound_number: 'OC-A', seller_inbound_number: 'PO-1' }

    expect(matchesInboundOverrideIdentity({ oc_inbound_number: 'OC-A', seller_inbound_number: 'PO-1' }, identity)).toBe(true)
    expect(matchesInboundOverrideIdentity({ oc_inbound_number: 'OC-B', seller_inbound_number: 'PO-1' }, identity)).toBe(false)
    expect(matchesInboundOverrideIdentity({ oc_inbound_number: 'OC-A', seller_inbound_number: 'PO-2' }, identity)).toBe(false)
  })

  it('falls back to the single supplied identifier', () => {
    expect(matchesInboundOverrideIdentity({ oc_inbound_number: ' oc-a ', seller_inbound_number: 'PO-1' }, { oc_inbound_number: 'OC-A' })).toBe(true)
    expect(matchesInboundOverrideIdentity({ oc_inbound_number: null, seller_inbound_number: ' po-1 ' }, { seller_inbound_number: 'PO-1' })).toBe(true)
  })
})
