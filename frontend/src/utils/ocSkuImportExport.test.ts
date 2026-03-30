import { describe, expect, it } from 'vitest'
import { normalizeOcSkuid, skuGroupKeyFromSkuCode, chunkQuantity } from './ocSkuImportExport'

describe('skuGroupKeyFromSkuCode', () => {
  it('extracts leading letters before digits', () => {
    expect(skuGroupKeyFromSkuCode('uke01')).toBe('uke')
    expect(skuGroupKeyFromSkuCode('USE03')).toBe('use')
    expect(skuGroupKeyFromSkuCode('dee05')).toBe('dee')
    expect(skuGroupKeyFromSkuCode('bee02')).toBe('bee')
    expect(skuGroupKeyFromSkuCode('xxx01')).toBe('xxx')
  })

  it('returns null when it cannot parse', () => {
    expect(skuGroupKeyFromSkuCode('01')).toBeNull()
    expect(skuGroupKeyFromSkuCode('---')).toBeNull()
    expect(skuGroupKeyFromSkuCode('sku')).toBeNull()
  })
})

describe('normalizeOcSkuid', () => {
  it('adds OC prefix when missing', () => {
    expect(normalizeOcSkuid('0000031876013')).toBe('OC0000031876013')
  })
  it('keeps existing OC prefix', () => {
    expect(normalizeOcSkuid('OC0000031876013')).toBe('OC0000031876013')
  })
})

describe('chunkQuantity', () => {
  it('splits into fixed-size cartons', () => {
    expect(chunkQuantity(12, 4)).toEqual([4, 4, 4])
  })

  it('handles remainder on the last carton', () => {
    expect(chunkQuantity(10, 4)).toEqual([4, 4, 2])
  })

  it('uses cap floor and min 1', () => {
    expect(chunkQuantity(3, 1)).toEqual([1, 1, 1])
    expect(chunkQuantity(3, 0)).toEqual([1, 1, 1])
  })
})

