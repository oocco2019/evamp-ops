/**
 * Pure helper for the AI instructions textarea value when voice recording is active.
 * While recording we must always show: base instructions + newline + live transcript.
 * Do not add logic that hides the live transcript when it appears in base (e.g. "dedupe")—that breaks real-time display.
 * See docs/VOICE_INSTRUCTIONS.md.
 */
export function getInstructionsDisplayValue(
  voiceRecording: boolean,
  aiPromptInstructions: string,
  liveTranscript: string
): string {
  if (!voiceRecording) return aiPromptInstructions
  const base = (aiPromptInstructions ?? '').trim()
  const live = (liveTranscript ?? '').trim()
  if (!live) return base
  return base ? `${base}\n${live}` : live
}
