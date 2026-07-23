import { linkifyParts } from './linkify'

describe('linkifyParts', () => {
  it('returns empty for empty string', () => {
    expect(linkifyParts('')).toEqual([])
  })

  it('keeps plain text', () => {
    expect(linkifyParts('hello world')).toEqual([{ type: 'text', value: 'hello world' }])
  })

  it('extracts http and https URLs', () => {
    expect(linkifyParts('see https://example.com/path and http://foo.test')).toEqual([
      { type: 'text', value: 'see ' },
      { type: 'url', value: 'https://example.com/path' },
      { type: 'text', value: ' and ' },
      { type: 'url', value: 'http://foo.test' },
    ])
  })

  it('leaves trailing punctuation outside the URL', () => {
    expect(linkifyParts('Go to https://example.com.')).toEqual([
      { type: 'text', value: 'Go to ' },
      { type: 'url', value: 'https://example.com' },
      { type: 'text', value: '.' },
    ])
  })
})
