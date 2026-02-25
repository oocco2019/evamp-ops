# Behavior docs (do not break)

This project keeps **behavior docs** for features that have regressed before or have non-obvious pitfalls. When you or an AI agent change code in those areas:

1. **Read the doc first** and check the **Requirements** (or equivalent) section. Do not make edits that conflict with stated requirements without explicit agreement from the person who owns the product.
2. **Run any listed tests** after your change.

| Feature | Doc | What it protects |
|--------|-----|-------------------|
| Message attachments | [MESSAGE_ATTACHMENTS.md](MESSAGE_ATTACHMENTS.md) | Thread API media URLs, blob storage, full-size images, display and pitfalls |
| Voice instructions | [VOICE_INSTRUCTIONS.md](VOICE_INSTRUCTIONS.md) | Real-time transcript display; do not hide live transcript in textarea |

**Tests:** Voice instructions display logic is in `frontend/src/utils/voiceInstructionsDisplay.ts` and tested by `frontend/src/utils/voiceInstructionsDisplay.test.ts`. Run `npm run test` in `frontend/` before committing changes that touch the instructions textarea or voice recording.

**Why this file exists:** To reduce “we fixed this before and it broke again” by making the intended behavior and pitfalls explicit and by locking critical logic behind tests where possible.
