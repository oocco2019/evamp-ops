import { describe, it, expect } from 'vitest'
import { isReplySendLocked, shouldApplyGeneratedDraft } from './draftReplyGuard'

describe('isReplySendLocked', () => {
  it('locks Send while Generate draft is in flight (not only while loading)', () => {
    expect(isReplySendLocked(false, true)).toBe(true)
  })

  it('locks Send while a send/thread load is in flight', () => {
    expect(isReplySendLocked(true, false)).toBe(true)
  })

  it('does not lock Send when idle', () => {
    expect(isReplySendLocked(false, false)).toBe(false)
  })
})

describe('shouldApplyGeneratedDraft', () => {
  it('applies when the same thread is still open and this is the latest request', () => {
    expect(
      shouldApplyGeneratedDraft({
        draftedThreadId: 'thread-a',
        currentThreadId: 'thread-a',
        requestId: 3,
        latestRequestId: 3,
      })
    ).toBe(true)
  })

  it('does not apply after the user opened a different thread', () => {
    expect(
      shouldApplyGeneratedDraft({
        draftedThreadId: 'thread-a',
        currentThreadId: 'thread-b',
        requestId: 1,
        latestRequestId: 1,
      })
    ).toBe(false)
  })

  it('does not apply after send or thread switch abandoned the in-flight draft', () => {
    expect(
      shouldApplyGeneratedDraft({
        draftedThreadId: 'thread-a',
        currentThreadId: 'thread-a',
        requestId: 1,
        latestRequestId: 2,
      })
    ).toBe(false)
  })

  it('does not apply when no thread is selected', () => {
    expect(
      shouldApplyGeneratedDraft({
        draftedThreadId: 'thread-a',
        currentThreadId: null,
        requestId: 1,
        latestRequestId: 1,
      })
    ).toBe(false)
  })
})
