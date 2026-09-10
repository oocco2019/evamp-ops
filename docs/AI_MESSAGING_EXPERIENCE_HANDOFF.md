# Brief: improve AI messaging draft experience (EvampOps)

Paste this whole file when discussing **options and architecture** for better AI reply drafting — not line-by-line implementation unless asked. Repo: **evamp-ops** (FastAPI + PostgreSQL + React). Product surface: **Messages** (`/messages`) + **AI Instructions** (`/ai-instructions`).

**Reviewed Sep 2026.** Experimental **Messages-Test / CS rule router** was removed; only the legacy compose path below remains.

---

## Owner intent (why this exists)

The seller wants AI drafts that feel like **a real multi-turn support conversation**, not a one-shot FAQ dump. Typical human flow for product issues:

1. **Sympathise** with the buyer about the issue.
2. **Clarify** what’s going on / what’s causing it (questions, not assumptions).
3. Offer **short, generic troubleshooting** (one stage at a time).
4. If that fails → ask for **video proof**.
5. Only then arrange **replacement or refund**.

That flow spans **many messages**. Today the model often **crams steps 1–5 into a single wall of text** and expects the buyer to be fine with it. Separately, drafts still **miss following “Instructions for AI”** / policies sometimes. Latency was partially fixed (one LLM call by default).

**Discuss latency and conversation design as related but separable.** Conversation-stage behaviour is the main open design problem.

---

## Exact current compose pipeline (code truth)

### Trigger

- UI: Messages → upper **Instructions for AI** box (optional) → **Generate draft**.
- API: `POST /api/messages/threads/{thread_id}/draft` with `{ extra_instructions?: string }` (max 2000).
- Handler: `backend/app/api/messages.py` → `compose_draft_with_adherence` in `reply_compose.py`.
- LLM: default AI model via `AIService.generate_message` → Anthropic or OpenAI provider.

### Steps (always)

1. Load all thread messages chronologically; each history item = `subject + "\n" + content`, role = `sender_type`.
2. Resolve order ID (thread, else buyer→order heuristic).
3. **Truncate** history: last `REPLY_DRAFT_MAX_THREAD_MESSAGES` (default **24**), also cap ~12k chars from newest backward.
4. **Product context:** order line SKUs → `skus.title`; else `thread.sku`. Text block: order id + `SKU: code — title`.
5. Load **all enabled** `reply_policies` (sorted).
6. Load **all enabled** playbook rows whose `sku_scope` matches any product SKU (`*`, exact, prefix `dee*`, comma list). **Keywords are not used** for retrieval (`thread_text` discarded).
7. Detect **seller greeted today** (UTC calendar day + greeting regex) → optional hard “do not re-greet” line in user prompt.
8. Build:
   - **System prompt** (provider): fixed CS persona + empathy/punctuation hard rules + full policy bodies + **all** matching playbook symptom→resolution lines + product context. Optional DB `system_prompt_override` on the AI model **replaces the entire** system builder (policies/playbook would be dropped — footgun).
   - **User prompt** (compose): short “one short message for this stage… English only” + optional greeting rule + `Additional instructions: {extra_instructions}`.
   - Provider wraps user content with formatted thread history + “Draft a response… no preamble”.
9. **One** `generate_message` call; `max_tokens` from `REPLY_DRAFT_MAX_TOKENS` (default **700**), not the model-setting max_tokens alone.
10. Post-process: strip em/en dashes, `, and`, tidy spaces (`sanitize_messaging_punctuation`).
11. **Adherence** (default **off**): if `REPLY_DRAFT_ADHERENCE_ENABLED`, second LLM scores each policy; up to `REPLY_DRAFT_MAX_REVISES` revise loops.
12. Persist `ai_compositions` (snapshot, policy/playbook IDs, output, adherence JSON); store `last_composition:{thread_id}` in sync metadata; may mine insights after compose.

### Config defaults (`backend/app/core/config.py`)

| Setting | Default | Effect |
|---------|---------|--------|
| `REPLY_DRAFT_ADHERENCE_ENABLED` | `false` | Skip policy re-check |
| `REPLY_DRAFT_MAX_REVISES` | `0` | No auto-revise |
| `REPLY_DRAFT_MAX_THREAD_MESSAGES` | `24` | Cap history |
| `REPLY_DRAFT_MAX_TOKENS` | `700` | Cap generation |

### What is *not* in the draft path

- No conversation **stage** detection or storage.
- No CS **router** / known-issues / stage templates (removed).
- Legacy global/SKU `AIInstruction` blobs: not injected.
- Style profile / procedure tables: exist, not injected.
- Playbook keywords: stored historically, **unused** for matching.
- Insights: **not** auto-injected until Promote to policy/playbook.

### Structural tension (root of wall-of-text)

- User prompt says “one short message for this stage”.
- System prompt says “concise but thorough” and dumps **every** matching playbook resolution in full.
- No mechanism limits *which* playbook step applies *now*.
- `extra_instructions` are a single appended paragraph with no priority weighting over playbook dump.

---

## What already exists (do not re-invent blindly)

### UI

| Piece | Where |
|-------|--------|
| Thread list + reply box + **Generate draft** | `frontend/src/pages/MessageDashboard.tsx` |
| Per-draft free text (“Instructions for AI”) + voice | Same page → `extra_instructions` |
| Premade messages (paste into reply, not into AI prompt) | Dropdown + `/premade-messages` |
| Policies + playbook CRUD + Insights | `frontend/src/pages/AIInstructions.tsx` |

Generate draft uses a dedicated `isDrafting` flag so a silent thread-list refresh does not disable the button. **Send must stay disabled while `isDrafting`.** A completed draft must not write the reply box if the user switched threads or the send already succeeded (`frontend/src/utils/draftReplyGuard.ts`).

### Data model

- **`reply_policies`** — how to write; every enabled row every draft.
- **`reply_playbook_entries`** — flat symptom→resolution; SKU-scoped retrieval.
- **`ai_compositions`** — audit trail of what was injected + output.
- **`draft_feedback`** — draft vs sent on send (underused for staging).
- **`reply_insights`** — pending suggestions; review-before-promote.

Canonical docs: [`AI_REPLY_POLICY.md`](AI_REPLY_POLICY.md), [`CUSTOMER_SERVICE.md`](CUSTOMER_SERVICE.md).

---

## Pain points (owner language)

1. **Single-exchange dumps** — whole support process in one message.
2. **Ignores conversation stage** — re-offers troubleshooting + video + refund together.
3. **Misses Instructions for AI / policies** — soft prompt priority vs large playbook dump.
4. **Playbook is knowledge, not a script** — no “only do step N now”.
5. **Speed vs quality** — adherence helped compliance but hurt UX (kept off).
6. **Model / tokens** — Misc → AI Models; compose caps draft tokens via context.

---

## Design options (discuss trade-offs; pick a path)

Present **pros / cons / complexity / latency impact**. Prefer options that fit existing tables unless a new concept is clearly better.

### A. Prompt-only “conversation stage” rules

Durable system/policy text: one short reply; one stage; don’t ask video until troubleshooting failed; don’t offer refund until video (or owner instruction); don’t paste whole playbook.

- **Pros:** Fast; no schema. **Cons:** Soft; hard to verify.

### B. Explicit stage machine (recommended discussion focus)

Detect/store thread stage (`empathy_clarify` → `troubleshoot` → `await_video` → `resolution`). Inject **only** playbook/instructions for current stage.

- **Pros:** Matches owner mental model. **Cons:** Taxonomy, detection, edge cases (WISMO, returns, non-defect).
- Variants: heuristics vs small classifier vs UI stage chip.

### C. Structured playbook (ordered steps)

Playbook entries become steps with exit criteria.

- **Pros:** Author once; compose “renders current step”. **Cons:** Migration + UI; authoring quality.

### D. Slim retrieval

Top-k / keyword / embeddings; “always-on” vs “issue” policies; don’t inject large playbook until stage needs it.

### E. Adherence lite

Hard policies only; async after draft; or single “generate + self-check” call.

### F. Model routing

Fast draft model; strong model for Redo / adherence; separate CS token caps.

### G. UX

Stage chips; “Next step only” / “Full advice”; show injected playbook/policies; streaming.

### H. Learning from edits

`draft_feedback` + Insights — partial; won’t fix staging alone.

---

## Constraints

- eBay message limit ~2000 chars.
- Data retention: keep compositions/feedback; don’t prune message history.
- Owner: **plan → options → align → implement**.
- Insights: review-before-promote only.
- Prefer keeping Messages UX familiar.

---

## Success criteria (propose / refine)

- Median draft **&lt; ~5–8s** (`reply_compose:` logs).
- Typical draft **≤ ~800–1200 chars**, one ask or one action.
- No refund/replacement before video/troubleshooting unless Instructions say so.
- `extra_instructions` visibly reflected (spot-check).
- Seller wipe-and-rewrite rate drops (`draft_feedback.was_edited` optional).

---

## Key files

```
docs/AI_REPLY_POLICY.md
docs/CUSTOMER_SERVICE.md
docs/AI_MESSAGING_EXPERIENCE_HANDOFF.md
backend/app/services/reply_compose.py
backend/app/api/messages.py
backend/app/services/ai_providers/anthropic_provider.py
backend/app/services/ai_providers/openai_provider.py
backend/app/core/config.py
frontend/src/pages/MessageDashboard.tsx
frontend/src/pages/AIInstructions.tsx
```

---

## What to return from the discussion

1. **Recommended primary approach** with rationale.
2. **MVP slice** vs later phases.
3. Explicit **non-goals** for MVP.
4. **Schema / UI** changes required.
5. How to **measure** improvement.
6. Interaction with Insights / adherence / model choice.

Do **not** implement in the discussion pass unless the owner asks for a concrete first PR.
