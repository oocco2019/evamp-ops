/**
 * Guards for Generate draft vs Send / thread-switch races.
 *
 * Generate draft uses `isDrafting`, not the shared `loading` flag, so thread
 * list refreshes do not disable the button. Send must still lock while a draft
 * is in flight, and a completed draft must not write into another thread's box
 * (or refill the box after a successful send).
 */

export function isReplySendLocked(loading: boolean, isDrafting: boolean): boolean {
  return loading || isDrafting
}

export function shouldApplyGeneratedDraft(args: {
  draftedThreadId: string
  currentThreadId: string | null | undefined
  requestId: number
  latestRequestId: number
}): boolean {
  if (args.requestId !== args.latestRequestId) return false
  if (!args.currentThreadId) return false
  return args.currentThreadId === args.draftedThreadId
}
