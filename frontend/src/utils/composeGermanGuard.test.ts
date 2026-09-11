import { describe, it, expect } from 'vitest'
import { isReplySendLockedForGerman, shouldApplyGermanTranslation } from './composeGermanGuard'

describe('isReplySendLockedForGerman', () => {
  it('locks Send while DE translate is in flight (not only while loading)', () => {
    expect(isReplySendLockedForGerman(false, true)).toBe(true)
  })

  it('locks Send while a send/thread load is in flight', () => {
    expect(isReplySendLockedForGerman(true, false)).toBe(true)
  })

  it('does not lock Send when idle', () => {
    expect(isReplySendLockedForGerman(false, false)).toBe(false)
  })
})

describe('shouldApplyGermanTranslation', () => {
  it('applies when the same thread is still open and this is the latest request', () => {
    expect(
      shouldApplyGermanTranslation({
        sourceThreadId: 'thread-a',
        currentThreadId: 'thread-a',
        requestId: 3,
        latestRequestId: 3,
      })
    ).toBe(true)
  })

  it('does not apply after the user opened a different thread', () => {
    expect(
      shouldApplyGermanTranslation({
        sourceThreadId: 'thread-a',
        currentThreadId: 'thread-b',
        requestId: 1,
        latestRequestId: 1,
      })
    ).toBe(false)
  })

  it('does not apply after send or thread switch abandoned the in-flight translation', () => {
    expect(
      shouldApplyGermanTranslation({
        sourceThreadId: 'thread-a',
        currentThreadId: 'thread-a',
        requestId: 1,
        latestRequestId: 2,
      })
    ).toBe(false)
  })

  it('does not apply when no thread is selected', () => {
    expect(
      shouldApplyGermanTranslation({
        sourceThreadId: 'thread-a',
        currentThreadId: null,
        requestId: 1,
        latestRequestId: 1,
      })
    ).toBe(false)
  })
})
