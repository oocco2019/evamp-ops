# Commentary: Opus AI CS Router + Stage Drafter Spec

**Source:** `/Users/marius/Downloads/AI_CS_ROUTER_SPEC.md` (Opus proposal)  
**Related:** [`AI_MESSAGING_EXPERIENCE_HANDOFF.md`](AI_MESSAGING_EXPERIENCE_HANDOFF.md), [`AI_REPLY_POLICY.md`](AI_REPLY_POLICY.md)  
**Status:** planning only — **do not implement until owner confirms**  
**Roles:** Opus + Composer align on plan; **Composer executes** after confirmation.

---

## Verdict (Composer)

**Strong direction. Worth building as MVP.** It matches the real pain (wall-of-text, slow multi-call compose) better than “prompt harder” or “re-enable adherence.”

Agree with the core bet:

1. **One LLM call per draft** (we already moved defaults that way).
2. **Rule router before the model** (latency + determinism).
3. **Stage-scoped prompt** (one ask / one action).
4. **Known-issues register** as the thing that correctly *skips* stages when evidence is obvious.
5. **Tier 3 = no resolutive draft** for safety / DE returns / messy cases.
6. **Draft-only** forever for MVP.

Main pushback: the spec underspecifies how this **coexists with today’s policies / playbook / Instructions-for-AI**, and a few routing edges will mis-fire unless we harden them in MVP. Those are fixable; they are not reasons to reject the design.

---

## What Opus got right (keep)

| Claim | Why it holds |
|-------|----------------|
| Route on intent + collapse signals, not product taxonomy | Matches how Marius actually collapses arcs (evidence / severity). |
| Known-issue register ≠ embedding search | Fits EvampOps ops: few recurring faults, seller-maintained. |
| Linear stage machine alone is too rigid | Real threads jump (returns, wrong length, safety). Intent + known-issue + thread signals is richer. |
| EN free-returns vs DE returns as hard language key | Product/ops reality; encoding it in the router beats hoping the LLM remembers. |
| Follow-up surface separate from drafting | High ROI, no model cost on list view; don’t block MVP draft path on it. |
| Learning deferred | Correct — Insights/promote already exist; don’t invent silent injection. |

This is essentially **handoff option B (stage) + D (slim retrieval) + part of G (UX for Tier 3)**, with a concrete product schema Opus derived from the exports.

---

## Friction with the current codebase

Today (`reply_compose.py` + AI Instructions):

- **Every enabled `reply_policies` row** is dumped into every draft.
- **Matching `reply_playbook_entries`** (SKU scope) are dumped in full.
- **`extra_instructions`** from Messages (“Instructions for AI”) is appended.
- Adherence loop is **off** by default; one LLM call already.

Opus §5 says: **no policy dump, no full playbook** — only stage instruction + known-issue + last N msgs.

**Composer position:** that is correct for *content* control, but we must not throw away:

1. **Style / liability policies** (dashes, tone, “don’t invent refunds”) — keep a **small always-on style pack** (hard-coded stage preamble + optional short “style policies” subset, or migrate critical ones into stage templates).
2. **Per-draft `extra_instructions`** — **must override** stage defaults for that turn (seller intent). Spec is silent; treat as MVP requirement.
3. **Existing playbook** — either (a) evolve into known-issues + stage actions, or (b) keep playbook for Tier-1 factual hints (wifi guide, fitment boilerplate) while known-issues owns collapse. Prefer **(b) short term**, **(a) medium term**, avoid two competing truth sources long-term.

---

## Risks and pushbacks (must address in joint plan)

### R1 — Keyword intent is brittle

- `"error"` under `not_charging` will steal many unrelated messages.
- Order matters: `return_request` vs `wrong_item` vs `cancel` overlap.
- Short DE messages may miss EN keyword tables; DE table must be first-class (spec has some DE tokens — expand systematically).

**Plan:** ship keyword router with **logged intent + confidence**; UI shows “Routed as: …” so seller can override (optional chip) in phase 1.5 if misroutes hurt. MVP can be display-only (no override) if schedule is tight.

### R2 — Undefined flags

Spec routes on `out_of_warranty_flag` and `ebay_case_flag` without detection rules.

**Plan:** MVP either omit those branches or define cheap detectors (order age from DB; subject/body keywords for “eBay case” / “INR” / “Money Back Guarantee”). Don’t leave dead code paths.

### R3 — `melted_plug` vs Tier 3 safety

§3.4 sends `safety_claim` → Tier 3; register says `request_photo`. Footnote clarifies register does not auto-resolve — good, but the **seller-facing Tier 3 card** should still surface the known-issue hint (“likely melted plug — ask photo”) so Marius isn’t starting from blank.

### R4 — Language heuristic quality

We already have LLM / local detect paths; heuristic is faster but wrong on short English from DE buyers and vice versa.

**Plan:** heuristic first; if `OTHER` or low confidence, fall back to listing marketplace / previous buyer language in thread / existing `detected_language` on messages. Still **no extra LLM call** if we reuse stored detection.

### R5 — Hardcoded WhatsApp / PayPal / copy

Stage prompts embed phone and process detail. Those belong in **settings or stage template table**, not buried in Python only — else every copy tweak is a deploy.

### R6 — `batch_safe` operational hazard

Wrong flip → wrong replace-vs-refund. Needs UI + audit (“flipped by whom, when”) and default **safe = false** (prefer refund / ask seller) until confirmed.

### R7 — Tier 3 UX underspecified

“Summary + escalation card” needs concrete Messages UI: where it appears, what fields, whether Draft button is disabled or switches to “Show escalation notes”.

### R8 — Volume estimates

75/20/5 is a hypothesis. Instrument `tier`/`intent`/`stage` on every composition from day 1.

---

## Agreement with Opus open decisions (§11)

| # | Question | Composer recommendation |
|---|----------|-------------------------|
| 1 | `batch_safe` | Default **false**. Seller flips in AI Instructions / Inventory note when new-batch stock is confirmed. Log changes. Until true, `white_glue_cover` → **refund** (or Tier 3 ask) not replace. |
| 2 | Follow-up N days | Start **3** for courier/update promises; **5** for general stalled “last message seller”. Configurable. |
| 3 | `melted_plug` | Always **Tier 3** for draft resolution; card suggests photo ask. Never auto `resolve_*`. |
| 4 | Phase-2 order | **Learning loop** first (uses existing Insights), then **invoice hook**, then **fitment DB** (heaviest). |

Owner should confirm or override these before build.

---

## Proposed joint architecture (align here)

```
Draft click
  → load thread (last N msgs) + product/order context
  → detect_language (heuristic + stored/thread fallback)
  → classify_intent (keyword table, priority order)
  → match_known_issue (register + SKU scope)
  → route → { tier, stage, known_issue?, reasons[] }
  → if Tier 3: return escalation payload (no resolutive LLM draft)
  → else build prompt:
        always-on style block (short)
        + stage instruction (from templates)
        + known-issue diagnosis/action if any
        + product context (compact)
        + extra_instructions if any (highest priority)
        + last N messages
  → ONE llm.generate (max_tokens ~700)
  → persist ai_compositions with router snapshot
  → return draft + router debug (tier/intent/stage) to UI
```

**Feature flag:** `REPLY_ROUTER_ENABLED` (default off until soak) so we can flip back to current compose.

**Follow-up surface:** separate endpoint + Messages sidebar/section; independent PR after or parallel to router if capacity allows.

---

## MVP work breakdown (execution order after confirm)

### Phase 0 — Confirm (owner)

- [ ] Accept / amend open decisions above.
- [ ] Confirm WhatsApp number / PayPal copy live in settings vs templates.
- [ ] Confirm feature-flag rollout (off → internal only → on).

### Phase 1 — Data + router core (backend)

- [ ] Migration: `known_issues` table (+ `batch_safe` global or per-issue).
- [ ] Seed 4 rows from spec (adjusted for safety/`batch_safe` defaults).
- [ ] Module `reply_router.py`: language, intent, known-issue, route, thread signal helpers.
- [ ] Stage template map in code or DB (`reply_stage_templates`).
- [ ] Wire into `compose_draft_with_adherence` **or** replace path behind flag.
- [ ] Persist router fields on `ai_compositions` (JSON snapshot).
- [ ] Unit tests: intent priority, DE return → Tier 3, known-issue skip, no wall-of-text stage text.

### Phase 2 — AI Instructions UI

- [ ] CRUD for known-issues (pattern, SKU scope, confidence, skip_to_action, evidence, disposal, active, batch_safe).
- [ ] Clarify relationship copy: playbook vs known-issues (what each is for).

### Phase 3 — Messages UI

- [ ] Show route chip: tier / intent / stage (debug trust).
- [ ] Tier 3: escalation card instead of (or above) empty draft; optional “draft photo-ask only” later.
- [ ] Keep Instructions-for-AI; document that it overrides stage.

### Phase 4 — Follow-up surface

- [ ] Query stalled threads + promised updates.
- [ ] One-tap “draft nudge” using `follow_up` / `courier_chase` stage.

### Phase 5 — Measure

- [ ] Log latency (`reply_compose:` already) + tier distribution.
- [ ] Spot-check: no refund before evidence unless high known-issue.
- [ ] Edit rate via `draft_feedback` (baseline vs after).

### Explicitly out of first execution pass

- Auto-send  
- Fitment DB  
- Invoice automation  
- Embedding retrieval / LLM classifier / adherence loop  
- Learning distill (phase 2+)

---

## What Composer needs from Opus before coding

1. Full stage instruction text (not abbreviated) for each stage — or agreement that Composer drafts them from §5 and Opus reviews.
2. Final keyword tables EN+DE with priority order and **removed overly broad tokens** (`error`?).
3. Precise detectors for `prior troubleshooting` / `video received` / `evidence obvious` (phrase lists).
4. Tier 3 card schema (fields).
5. Whether playbook stays injected for Tier 1 only, or is frozen during MVP.

---

## What Opus should challenge Composer on

- Whether always-on style policies reintroduce wall-of-text (keep them ≤ ~5 short lines).
- Whether UI route override is MVP or not.
- Whether follow-up should ship in the same MVP or wait (Composer leans: same release if small, else immediately after).

---

## Owner confirmation checklist

Reply with decisions (edit this block):

```
[ ] Build router MVP as sketched (yes / no / changes: …)
[ ] batch_safe default false → refund until flipped (yes / no)
[ ] melted_plug always Tier 3 (yes / no)
[ ] follow-up N = 3/5 days (or: …)
[ ] Feature flag first (yes / no)
[ ] Playbook during MVP: Tier1 only / freeze / replace with known-issues
[ ] Follow-up in MVP vs next PR
[ ] extra_instructions override stage (confirm yes)
[ ] Proceed to implement after this confirm (yes / wait for Opus reply first)
```

---

## File map (when implementing)

| New / touch | Purpose |
|-------------|---------|
| `backend/app/services/reply_router.py` | Rule router |
| `backend/app/services/reply_compose.py` | Stage prompt + flag |
| `backend/app/models/messages.py` + Alembic | `known_issues` |
| `backend/app/api/messages.py` | Draft response shape (router meta, Tier 3) |
| `frontend/.../AIInstructions.tsx` | Known-issues CRUD |
| `frontend/.../MessageDashboard.tsx` | Route chip + Tier 3 card + follow-up |
| `docs/AI_REPLY_POLICY.md` | Document new compose path |
| Copy Opus spec into `docs/AI_CS_ROUTER_SPEC.md` (optional, after confirm) |

---

## Bottom line

Opus’s spec is the right product architecture for EvampOps CS drafts: **fast, staged, evidence-aware, draft-only**. Composer will execute it behind a flag once you confirm the checklist (and preferably after Opus fills the keyword/stage-text gaps above). Until then: **plan only, no implementation.**
