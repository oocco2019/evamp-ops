import { describe, it, expect } from 'vitest'
import { getInstructionsDisplayValue } from './voiceInstructionsDisplay'

describe('getInstructionsDisplayValue', () => {
  it('when not recording, returns aiPromptInstructions as-is', () => {
    expect(getInstructionsDisplayValue(false, 'hello', 'world')).toBe('hello')
    expect(getInstructionsDisplayValue(false, '', 'live')).toBe('')
  })

  it('when recording and no live transcript, returns trimmed base only', () => {
    expect(getInstructionsDisplayValue(true, '  base  ', '')).toBe('base')
    expect(getInstructionsDisplayValue(true, '', '')).toBe('')
  })

  it('when recording with live transcript, always returns base + newline + live (never hides live)', () => {
    expect(getInstructionsDisplayValue(true, '', 'hello')).toBe('hello')
    expect(getInstructionsDisplayValue(true, 'base', 'hello')).toBe('base\nhello')
    expect(getInstructionsDisplayValue(true, 'base', 'hello world')).toBe('base\nhello world')
  })

  it('when recording, does not dedupe or hide live when live appears in base', () => {
    const base = 'please ask the customer'
    const live = 'the'
    expect(getInstructionsDisplayValue(true, base, live)).toBe('please ask the customer\nthe')
  })

  it('when recording, does not hide live when live equals base', () => {
    const text = 'same text'
    expect(getInstructionsDisplayValue(true, text, text)).toBe('same text\nsame text')
  })
})
