import { describe, it, expect } from 'vitest'
import { isOcOutboundOrderFulfilledMovement, parseOcMovementReasonCode } from './ocStockMovement'

describe('parseOcMovementReasonCode', () => {
  it('parses CODE=description', () => {
    expect(parseOcMovementReasonCode('OOF=Outbound Order Fulfiled')).toBe('OOF')
    expect(parseOcMovementReasonCode('PAC=Put Away Completed')).toBe('PAC')
  })

  it('returns null for human-only descriptions', () => {
    expect(parseOcMovementReasonCode('OC Black Inventory Freeze')).toBeNull()
  })
})

describe('isOcOutboundOrderFulfilledMovement', () => {
  it('includes OOF with negative quantity only', () => {
    expect(isOcOutboundOrderFulfilledMovement('OOF=Outbound Order Fulfiled', -3)).toBe(true)
  })

  it('excludes OOS (submitted)', () => {
    expect(isOcOutboundOrderFulfilledMovement('OOS=Outbound Order Submitted', -1)).toBe(false)
  })

  it('excludes inbound codes even when quantity is negative (per-bucket movement)', () => {
    expect(isOcOutboundOrderFulfilledMovement('PAC=Put Away Completed', -10)).toBe(false)
    expect(isOcOutboundOrderFulfilledMovement('IOS=Inbound Order Submitted', -5)).toBe(false)
  })

  it('excludes freeze / adjustment codes', () => {
    expect(isOcOutboundOrderFulfilledMovement('OEH=OCFrozen', -20)).toBe(false)
    expect(isOcOutboundOrderFulfilledMovement('IAA=Inventory Adjustement Applied', -2)).toBe(false)
  })

  it('matches English descriptions without a code prefix (fulfilled only)', () => {
    expect(isOcOutboundOrderFulfilledMovement('Outbound Order Fulfiled', -1)).toBe(true)
    expect(isOcOutboundOrderFulfilledMovement('Outbound Order Fulfilled', -1)).toBe(true)
    expect(isOcOutboundOrderFulfilledMovement('Outbound Order Submitted', -1)).toBe(false)
    expect(isOcOutboundOrderFulfilledMovement('Put Away Completed', -5)).toBe(false)
  })

  it('ignores non-decreases', () => {
    expect(isOcOutboundOrderFulfilledMovement('OOF=Outbound Order Fulfiled', 3)).toBe(false)
  })
})
