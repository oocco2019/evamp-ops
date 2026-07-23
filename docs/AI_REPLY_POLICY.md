# AI reply policy and playbook

Management UI: `/ai-instructions` (linked from Messages). Messages dashboard draft UX is unchanged; compose improvements run in the backend on `POST /api/messages/threads/{id}/draft`.

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
6. **Adherence:** second LLM pass scores each active policy; up to **2** automatic revisions on failure; then return the draft (Messages UI unchanged).
7. Persist `ai_compositions` (prompt snapshot, policy/playbook IDs, output, adherence). On send, `draft_feedback.composition_id` links when available.

Legacy global/SKU `AIInstruction` blobs and **Generate global from history** are retired (rows cleared; endpoints removed). Style profile / procedure tables remain but are no longer injected into draft.

## Insights (pending review)

Table `reply_insights`. When the same **Instructions-for-AI** text is used on ≥2 drafts (whatever you submitted in that box when you hit Generate draft — typed or already transcribed voice) — or the same adherence failure reason repeats — a **pending** insight is created. Insights are **not** injected into drafts until you **Promote** them to a policy or playbook (or **Dismiss**).

Messages shows a small **+** badge on the AI Instructions button when any insights are pending.

After you **Promote** or **Dismiss** an insight, that fingerprint (and near-duplicate wording) is not suggested again.

## Playbook SKU scope

- `*` — all SKUs  
- exact code — one SKU  
- `dee*` — prefix match  
- `dee01, dee02, uke01` — comma-separated list (any listed token may also be a prefix like `dee*`)
