import { describe, expect, it } from 'vitest'
import { inboundIdentifiersMatch, shouldCancelEmptyOverrideBlur } from './inboundIdentity'

describe('inboundIdentifiersMatch', () => {
  it('requires both identifiers to match when both are supplied', () => {
    const row = { oc_inbound_number: 'OCI-1', seller_inbound_number: 'SELLER-1' }

    expect(inboundIdentifiersMatch(row, { oc_inbound_number: 'OCI-1', seller_inbound_number: 'SELLER-1' })).toBe(true)
    expect(inboundIdentifiersMatch(row, { oc_inbound_number: 'OCI-1', seller_inbound_number: 'SELLER-2' })).toBe(false)
    expect(inboundIdentifiersMatch(row, { oc_inbound_number: 'OCI-2', seller_inbound_number: 'SELLER-1' })).toBe(false)
  })

  it('falls back to a single identifier only when the other is absent', () => {
    const row = { oc_inbound_number: 'OCI-1', seller_inbound_number: 'SELLER-1' }

    expect(inboundIdentifiersMatch(row, { oc_inbound_number: 'OCI-1' })).toBe(true)
    expect(inboundIdentifiersMatch(row, { seller_inbound_number: 'SELLER-1' })).toBe(true)
    expect(inboundIdentifiersMatch(row, { seller_inbound_number: 'SELLER-2' })).toBe(false)
  })
})

describe('shouldCancelEmptyOverrideBlur', () => {
  it('cancels blur saves that would clear an existing custom override', () => {
    expect(shouldCancelEmptyOverrideBlur('', 'https://carrier.example/track')).toBe(true)
    expect(shouldCancelEmptyOverrideBlur('   ', 'TRACK123')).toBe(true)
  })

  it('does not cancel unchanged empty drafts or non-empty edits', () => {
    expect(shouldCancelEmptyOverrideBlur('', '')).toBe(false)
    expect(shouldCancelEmptyOverrideBlur('https://new.example/track', 'https://old.example/track')).toBe(false)
  })
})
