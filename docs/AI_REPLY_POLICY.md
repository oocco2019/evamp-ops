# AI reply policy and playbook

Management UI: `/ai-instructions` (linked from Messages). Messages dashboard draft UX is unchanged; compose improvements run in the backend on `POST /api/messages/threads/{id}/draft`.

## Messages-Test (CS router)

Experimental surface: **`/messages-test`** (nav **Messages-Test**). Same Messages UI (including **voice instructions**); drafts use the CS router. Does **not** change legacy Messages compose.

- Rule router: language → intent → known-issue → tier/stage (`backend/app/services/reply_router.py`).
- One LLM stage draft (`POST /api/messages-test/threads/{id}/draft`); playbook frozen on this path. **Drafts are always English** (buyer language is for routing only; use DE to translate before send).
- Tier 3: escalation card, no resolutive draft (safety / DE return / OOW / eBay case / melted_plug / **seller already decided with no new buyer material**).
- Known issues + stage templates in DB (migration `035`); `white_glue_cover.batch_safe` defaults **false** → refund until flipped via `PATCH /api/messages-test/known-issues/{id}`.
- Spec: [`AI_CS_ROUTER_SPEC.md`](AI_CS_ROUTER_SPEC.md).

For a **handoff brief** on making drafts faster and more conversational (stage-based support flow, options/trade-offs), see [AI_MESSAGING_EXPERIENCE_HANDOFF.md](AI_MESSAGING_EXPERIENCE_HANDOFF.md).

## Two stores

### Policies (`reply_policies`)

Durable rules about **how** replies are written (tone, liability), not product facts. Free-text rows with enable toggles. Every **enabled** policy is injected into every draft.

Starter seeds:

- Do not use a comma before “and” or before a dash in ways people do not usually use when messaging.
- Maintain a friendly, conversational, and helpful tone.

### Playbook (`reply_playbook_entries`)

Symptom → resolution knowledge scoped by SKU and optional keywords.

| Field | Role |
|-------|------|
| `symptom` | What the buyer issue looks like |
| `resolution` | What the assistant should suggest |
| `sku_scope` | `*` (all), exact SKU, prefix `dee*`, or comma list `dee01, dee02, uke01` |
| `enabled` | Toggle |

Keywords are not part of retrieval (SKU scope only).

Starter seed: suggest printing labels on A4 paper (`sku_scope=*`).

## Compose flow

1. Resolve product: thread `ebay_order_id` (or buyer→order fallback) → order line SKUs → `skus.title`; fall back to `thread.sku`.
2. Load enabled policies.
3. Retrieve matching playbook entries (SKU scope; `*` = all).
4. Build prompt: policies + playbook + product context + full chronological thread + compose instruction (+ Messages “Instructions for AI” if set).
5. Generate draft.
6. **Adherence (optional):** when `REPLY_DRAFT_ADHERENCE_ENABLED=true`, a second LLM pass scores each active policy; up to `REPLY_DRAFT_MAX_REVISES` automatic revisions on failure. **Default is off** for faster drafts (one LLM call).
7. Persist `ai_compositions` (prompt snapshot, policy/playbook IDs, output, adherence). On send, `draft_feedback.composition_id` links when available.

Draft speed defaults (override in `.env`): `REPLY_DRAFT_ADHERENCE_ENABLED=false`, `REPLY_DRAFT_MAX_REVISES=0`, `REPLY_DRAFT_MAX_THREAD_MESSAGES=24`, `REPLY_DRAFT_MAX_TOKENS=700`. Backend logs `reply_compose:` timings when diagnosing slow drafts.

Legacy global/SKU `AIInstruction` blobs and **Generate global from history** are retired (rows cleared; endpoints removed). Style profile / procedure tables remain but are no longer injected into draft.

## Insights (pending review)

Table `reply_insights`. A **weekly Sunday scan** (Europe/Vilnius 09:00, with catch-up if the
machine was off) reads recent **Instructions-for-AI** prompts from compositions. Themes that
appear in **≥3** submissions (exact or same intent) are distilled by the LLM into a **short
rule** (e.g. “Do not use dashes in customer replies”) — not the full case transcript.

The same **≥3** threshold applies to repeated adherence-failure reasons after compose.

**On-demand seller style scan:** From AI Instructions, **Scan seller messages (2 months)**
loads your outbound seller messages from the last two months and asks the LLM for short
writing-style policy suggestions (tone, punctuation habits, greetings, etc.). Those appear
as pending insights with source `seller_style_scan`.

Insights are **not** injected into drafts until you **Promote** them to a policy or playbook
(or **Dismiss**). Messages shows a **+** badge on AI Instructions when any are pending.

After **Promote** or **Dismiss**, that fingerprint (and near-duplicate wording) is not suggested again.

## Playbook SKU scope

- `*` — all SKUs  
- exact code — one SKU  
- `dee*` — prefix match  
- `dee01, dee02, uke01` — comma-separated list (any listed token may also be a prefix like `dee*`)
