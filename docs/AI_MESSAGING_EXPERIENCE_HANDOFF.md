# Brief: improve AI messaging draft experience (EvampOps)

Paste this whole file when discussing **options and architecture** for better AI reply drafting — not line-by-line implementation unless asked. Repo: **evamp-ops** (FastAPI + PostgreSQL + React). Product surface: **Messages** (`/messages`) + **AI Instructions** (`/ai-instructions`).

---

## Owner intent (why this exists)

The seller wants AI drafts that feel like **a real multi-turn support conversation**, not a one-shot FAQ dump. Typical human flow for product issues:

1. **Sympathise** with the buyer about the issue.
2. **Clarify** what’s going on / what’s causing it (questions, not assumptions).
3. Offer **short, generic troubleshooting** (one stage at a time).
4. If that fails → ask for **video proof**.
5. Only then arrange **replacement or refund**.

That flow spans **many messages**. Today the model often **crams steps 1–5 into a single wall of text** and expects the buyer to be fine with it. Separately, **Draft reply felt very slow**, and drafts still **miss following “Instructions for AI”** / policies sometimes.

**Discuss latency and conversation design as related but separable.** Latency was partially addressed already (see below). Conversation-stage behaviour is the main open design problem.

---

## What already exists (do not re-invent blindly)

### UI

| Piece | Where |
|-------|--------|
| Thread list + reply box + **Draft reply** | `frontend/src/pages/MessageDashboard.tsx` |
| Per-draft free text (“Instructions for AI”) | Same page; sent as `extra_instructions` on draft |
| Policies + playbook CRUD + Insights review | `frontend/src/pages/AIInstructions.tsx` (`/ai-instructions`) |
| Voice → instructions | See `docs/VOICE_INSTRUCTIONS.md` |

### Backend compose

| Piece | Where |
|-------|--------|
| `POST /api/messages/threads/{id}/draft` | `backend/app/api/messages.py` → `compose_draft_with_adherence` |
| Compose / policies / playbook / adherence | `backend/app/services/reply_compose.py` |
| LLM providers | `backend/app/services/ai_service.py`, `ai_providers/anthropic_provider.py`, `openai_provider.py` |
| Insights mining / weekly scan / seller style scan | `backend/app/services/reply_insights.py`, `reply_insights_scheduler.py` |

### Data model (relevant tables)

- **`reply_policies`** — how to write (tone, punctuation, liability). **Every enabled policy** is injected into **every** draft.
- **`reply_playbook_entries`** — symptom → resolution, scoped by SKU (`*`, exact, prefix, comma list). Retrieval is **SKU scope only** (keywords unused).
- **`ai_compositions`** — prompt snapshot, policy/playbook IDs, model output, optional adherence JSON.
- **`draft_feedback`** — draft vs final on send (learning hook; underused for stage logic today).
- **`reply_insights`** — pending suggestions from repeated prompts / style scan; **not** injected until Promote.

Canonical behaviour docs: [`AI_REPLY_POLICY.md`](AI_REPLY_POLICY.md), [`CUSTOMER_SERVICE.md`](CUSTOMER_SERVICE.md). Older gap list (partially stale): [`USER_STORIES_MESSAGING_GAP.md`](USER_STORIES_MESSAGING_GAP.md).

### Current draft pipeline (high level)

1. Load thread messages → chronological history (now truncated to last N).
2. Resolve product context (order / SKU titles).
3. Load all enabled policies + matching playbook rows.
4. Build system prompt (policies + playbook + product) + short user compose instruction + optional `extra_instructions`.
5. **One** LLM generate (default).
6. Optionally adherence + revise loops (default **off**).
7. Persist `ai_compositions`; may mine adherence insights if adherence ran.

Providers still say things like “concise but thorough” / “helpful”; playbook text is dumped in full when SKU matches — which **encourages walls of text**.

---

## Latency: what we already changed (July 2026)

**Root cause of slowness:** each Draft could run **up to ~6 LLM calls** (generate + adherence check + up to 2 revise cycles each with another check). Even a “clean” draft was often **2 calls**.

**Defaults now (config in `backend/app/core/config.py`, `.env.example`):**

| Setting | Default | Effect |
|---------|---------|--------|
| `REPLY_DRAFT_ADHERENCE_ENABLED` | `false` | Skip policy re-check loop |
| `REPLY_DRAFT_MAX_REVISES` | `0` | No auto-revise |
| `REPLY_DRAFT_MAX_THREAD_MESSAGES` | `24` | Cap history |
| `REPLY_DRAFT_MAX_TOKENS` | `700` | Cap draft length / generation |

Also: stop duplicating policies/playbook in the **user** prompt (system only); log timings as `reply_compose:` in backend logs.

**Trade-off:** faster drafts, weaker automatic enforcement of policies. Policies are still **in the prompt**; nothing second-passes them unless adherence is re-enabled.

---

## Pain points to solve next (owner language)

1. **Single-exchange dumps** — AI tries to do the whole support process in one message.
2. **Doesn’t follow conversation stage** — ignores what was already asked/answered; re-offers troubleshooting + video + refund together.
3. **Misses Instructions for AI / policies** — free-text prompt on the draft or durable policies not reliably reflected.
4. **Playbook is knowledge, not a script** — flat symptom→resolution list gives no “only do step N now”.
5. **Speed vs quality** — adherence loops helped policy compliance but hurt UX; need a better compromise if we reintroduce checks.
6. **Model / max_tokens / temperature** — configured in Misc → AI Models UI; may still be a heavy Sonnet-class model with high `max_tokens` on the setting row (compose overrides draft max_tokens via context).

---

## Design options (discuss trade-offs; pick a path)

Present **pros / cons / complexity / latency impact**. Prefer options that fit existing tables unless a new concept is clearly better.

### A. Prompt-only “conversation stage” rules

Add durable system / policy text: one short reply; advance one stage; don’t ask for video until troubleshooting was offered and buyer said it failed; don’t offer refund/replacement until video (or explicit owner instruction); never paste the whole playbook.

- **Pros:** Fast to ship; no schema.
- **Cons:** Soft; models still leak multi-step dumps; hard to verify.

### B. Explicit stage machine (recommended discussion focus)

Detect or store **thread stage** (e.g. `empathy_clarify` → `troubleshoot` → `await_video` → `resolution`). Inject **only** the playbook / instructions for the current stage. Advance on buyer reply signals or seller send.

- **Pros:** Matches owner mental model; shorter prompts; better adherence to process.
- **Cons:** Need stage taxonomy, detection rules or classifier call, edge cases (returns, “where is my order”, non-defect).

Variants: rule-based heuristics on last N messages vs small LLM classifier (extra latency) vs operator-picked stage chip in UI.

### C. Structured playbook (steps), not flat resolutions

Change playbook entries (or add linked steps) to ordered steps with “exit criteria” (buyer confirms fail → next).

- **Pros:** Author once in AI Instructions; compose becomes “render current step”.
- **Cons:** Migration / UI work; authors must write steps well.

### D. Slim retrieval

Today: all matching SKU playbook rows + all policies every time. Options: keyword / embedding retrieval; rank top-k; separate “always-on” vs “issue” policies; don’t inject large playbook until stage needs it.

- **Pros:** Less distraction → better following of `extra_instructions`.
- **Cons:** Retrieval quality risk; miss rare cases.

### E. Adherence lite (latency compromise)

Re-enable adherence only for **hard** policies (liability, no inventing refunds), or run check **async after** draft returns (user sees draft immediately; UI warns if fail). Or single combined “generate + self-check” prompt (1 call, weaker).

### F. Model routing

Fast/cheap model for draft; optional strong model for “Redo carefully” or adherence. Cap UI model `max_tokens` for CS drafts independently of other features (translate/DE).

### G. UX changes (non-model)

- Stage chips or “Next step only” / “Full advice” toggle.
- Show which playbook/policies were injected (debug trust).
- Streaming draft (TTFB feel, not total compute).
- Better empty-state guidance for Instructions for AI (“only what to do *this* turn”).

### H. Learning from edits

Use `draft_feedback` + Insights more aggressively to learn “don’t dump refund early” — already partially built; weekly distill exists. May not fix staging alone.

---

## Constraints

- **eBay message limit ~2000 chars** (UI/enforced on send) — walls of text are also operationally bad.
- **Data retention:** keep compositions / feedback; don’t prune source message history.
- Owner prefers **plan → options → align → implement**; don’t silently rewrite product process.
- Keep Messages UX familiar unless a small control clearly helps (e.g. stage chip).
- Insights must stay **review-before-promote** (no silent policy injection from mining).

---

## Success criteria (propose / refine with owner)

Examples to debate:

- Median Draft reply **&lt; ~5–8s** on typical threads (measure via `reply_compose:` logs).
- Typical draft **≤ ~800–1200 chars**, one ask or one action.
- On issue threads: **no** refund/replacement offer before video/troubleshooting stage unless Instructions for AI say so.
- `extra_instructions` for this turn visibly reflected in draft (spot-check).
- Seller edit rate / “wipe and rewrite” frequency drops (optional: quantify via `draft_feedback.was_edited`).

---

## Key files to open

```
docs/AI_REPLY_POLICY.md
docs/CUSTOMER_SERVICE.md
docs/AI_MESSAGING_EXPERIENCE_HANDOFF.md   ← this brief
backend/app/services/reply_compose.py
backend/app/api/messages.py               # draft_reply
backend/app/services/ai_providers/anthropic_provider.py
backend/app/core/config.py                # REPLY_DRAFT_* 
frontend/src/pages/MessageDashboard.tsx
frontend/src/pages/AIInstructions.tsx
```

---

## What to return from the discussion

1. **Recommended primary approach** (e.g. B+C, or A then B) with rationale.
2. **MVP slice** (1–2 weeks of focused work) vs later phases.
3. Explicit **non-goals** for MVP.
4. Any **schema / UI** changes required.
5. How to **measure** improvement without relying only on vibes.
6. Interaction with **Insights / adherence / model choice**.

Do **not** implement in the discussion pass unless the owner asks for a concrete first PR.
