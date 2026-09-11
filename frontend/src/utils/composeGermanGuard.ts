/**
 * Guards for DE translate vs Send / thread-switch races.
 *
 * DE uses `composingDe`, not the shared `loading` flag. Send must still lock
 * while translation is in flight, and a completed translation must not write
 * into another thread's box (or refill the box after a successful send).
 */

export function isReplySendLockedForGerman(loading: boolean, composingDe: boolean): boolean {
  return loading || composingDe
}

export function shouldApplyGermanTranslation(args: {
  sourceThreadId: string
  currentThreadId: string | null | undefined
  requestId: number
  latestRequestId: number
}): boolean {
  if (args.requestId !== args.latestRequestId) return false
  if (!args.currentThreadId) return false
  return args.currentThreadId === args.sourceThreadId
}
