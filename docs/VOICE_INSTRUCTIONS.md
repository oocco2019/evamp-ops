# Voice instructions (Messages)

On the Messages page, the "Voice instructions" button uses the Web Speech API (SpeechRecognition) to capture speech and append it to the AI prompt instructions textarea. This doc describes the behavior and pitfalls. **Before changing this feature, read the Requirements below; do not make edits that conflict with them.**

## Requirements (do not change without explicit agreement)

- **Editable while recording:** The instructions textarea must remain **editable** while voice recording is on. The user must be able to type, correct, or edit the text alongside the live transcript. Do not set the textarea to read-only during recording.
- **Live transcript visible:** While recording, the textarea must show existing instructions plus the live transcript (accumulated finals + interim) so the user sees speech in real time.

## Behavior

- **Start:** User clicks "Voice instructions". Recording starts; `liveTranscript` state holds the live transcript (accumulated final segments + current interim).
- **During recording:** The textarea shows **existing instructions + live transcript** and stays **editable**. If the user types, `onChange` updates `aiPromptInstructions` and clears `liveTranscript` / `transcriptChunksRef` so their edit is what they see. `liveTranscript` is updated in `recognition.onresult`: final results are pushed to `transcriptChunksRef`; among interim results in the same event we use the **longest** (most complete) one, so you see the full phrase so far when the engine sends multiple interims per event, without appending across events (no duplication). Display = `finalSoFar` + that interim.
- **Stop:** User clicks again. Current `liveTranscript` is appended to `aiPromptInstructions`, then cleared. Recognition stops; `onend` may also append (unless user explicitly stopped, in which case `skipAppendOnEndRef` avoids double-append).

## Pitfall (do not re-introduce)

The textarea value when `voiceRecording` is true must be:

```text
base instructions + "\n" + liveTranscript
```

**Do not** add "dedupe" logic that returns only `base` when `liveTranscript` (or a substring of it) appears inside `base`. That was tried (e.g. "if base contains live as a word, show only base") and caused the bug: the user saw only the existing instructions and no live transcript, or only a single word, until they stopped—then the full text appeared. Always show the full live transcript while recording.

**Implementation:** The textarea uses `getInstructionsDisplayValue(voiceRecording, base, live)` from `frontend/src/utils/voiceInstructionsDisplay.ts`. The textarea is **not** read-only during recording. In `onresult` we take the **longest** interim in the event (so the most complete phrase in that batch is shown) and do not append across events (avoids duplication). On change while recording, we set `aiPromptInstructions` to the new value and clear `liveTranscript` and `transcriptChunksRef`.

**Tests:** `frontend/src/utils/voiceInstructionsDisplay.test.ts` asserts that when recording, the displayed value is always `base + "\n" + live` (never hiding live). Run `npm run test` in `frontend/` before committing changes to this behavior.
