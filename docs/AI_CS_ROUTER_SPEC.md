# EvampOps AI Customer Service — Router + Stage Drafter Spec

Status: proposal for review. Draft-only (no auto-send). Optimised for low latency.
Repo: evamp-ops. Supersedes the open design questions in `AI_MESSAGING_EXPERIENCE_HANDOFF.md`.
Grounded in analysis of ~419 real buyer threads across two 90-day windows (2026-01-28 → 2026-07-27).

---

## 1. Design principles (what the data forced)

1. **One LLM call per draft.** No per-draft classifier call, no adherence re-check loop, no
   embedding retrieval. The router is pure rule logic and runs before the model. The single
   model call gets a short, stage-scoped prompt. This is the whole latency budget.
2. **Route on intent + collapse signals, not on issue type.** The seller collapses the support
   arc based on *evidence obviousness* and *claim severity*, not on which product broke. The
   router encodes that, not a linear stage sequence.
3. **Draft advances exactly one stage.** Never dump the whole resolution arc in one message.
4. **Language is a hard routing key.** Free returns (US/UK) mean no push-back on English-language
   returns — the system just organises them. DE buyers are not covered, so DE returns still route
   to the seller for the reason/postage conversation.
5. **Known-issues register is a flat lookup, not a search system.** Substring/regex match on the
   buyer message. Sub-millisecond. It is the artifact that lets the drafter skip stages correctly.
6. **Everything drafts; nothing sends.** Seller approves every message.

---

## 2. Pipeline (per Draft request)

```
buyer message + thread history
        │
        ▼
[1] detect_language        (rule: charset/stopword heuristic → EN | DE | OTHER)
        │
        ▼
[2] classify_intent        (rule: keyword table → intent enum)
        │
        ▼
[3] match_known_issue      (rule: register lookup → issue_id | none)
        │
        ▼
[4] route                  (rule: tier + stage from the three inputs above)
        │
        ├── Tier 3  → NO resolutive draft. Emit thread summary + reason-for-escalation card.
        │
        └── Tier 1/2 → [5] build_stage_prompt   (stage instruction + matched action + recent msgs)
                             │
                             ▼
                       [6] ONE llm.generate()  → draft
                             │
                             ▼
                       [7] return draft to seller (draft-only) + log for learning
```

Steps 1–4 are synchronous rule logic (target < 5 ms total). Step 6 is the only network/model
call. No second model pass.

---

## 3. Router logic

### 3.1 Language (`detect_language`)
- Output: `EN | DE | OTHER`.
- Cheap heuristic (stopword/diacritic scan) is sufficient; no model call. Polish, French etc.
  fold into `OTHER` and are treated like `EN` for return handling (free-returns markets), except
  where a DE listing implies a DE buyer — use the buyer's message language, not the listing.

### 3.2 Intent (`classify_intent`)
Keyword-table classification on the latest buyer message. First match wins; ties resolve by the
priority order below (top = highest).

| intent              | trigger examples                                             |
|---------------------|-------------------------------------------------------------|
| `safety_claim`      | burnt, melted, fire, smoke, shock, sparks, tripped breaker  |
| `not_charging`      | won't charge, doesn't charge, not charging, stops charging, error, leakage |
| `physical_fault`    | front/cover/glass off, panel fell, cracked, broken, waterproof |
| `not_arrived`       | not arrived, still waiting, where is, not received, delay, noch nicht |
| `return_request`    | return, refund, send it back, wrong length, ordered wrong, change |
| `wrong_item`        | wrong one, received Xm, different cable, not what I ordered  |
| `cancel`            | cancel, bought by mistake, Klarna, wrong payment             |
| `wifi_app`          | wifi, app, pair, connect, WLAN, koppeln, timeout             |
| `fitment`           | compatible, will this fit, suitable, passt, reg [plate]      |
| `invoice`           | invoice, VAT, receipt, Rechnung                              |
| `other`             | (fallthrough)                                                |

### 3.3 Known-issue match (`match_known_issue`)
Register is a flat table (schema in §4). Match latest buyer message text + attached-image flag
against each row's `symptom_pattern`. Return `issue_id` or `none`.

### 3.4 Tier + stage assignment (`route`)

```
if intent in {safety_claim, out_of_warranty_flag, ebay_case_flag}      → TIER 3
elif intent == return_request and language == DE                       → TIER 3   # DE not free-returns
elif intent in {fitment, invoice, wifi_app, cancel}                    → TIER 1
elif intent in {return_request, wrong_item} and language != DE         → TIER 2 (stage: arrange_return)
elif intent in {not_charging, physical_fault, not_arrived}             → TIER 2
else                                                                    → TIER 1 (stage: clarify) or TIER 3 if unclear
```

Then within Tier 2, pick the stage:

```
if known_issue.match and known_issue.confidence == high
        → stage = known_issue.skip_to_action        # e.g. resolve_replace / resolve_refund
elif intent == not_arrived
        → stage = courier_chase
elif no prior troubleshooting in thread
        → stage = clarify_or_troubleshoot            # ONE step, not the whole arc
elif buyer confirms troubleshooting failed
        → stage = request_video                      # unless known_issue skipped it
elif video received OR evidence obvious
        → stage = resolve                            # replace or refund
else
        → stage = arrange_logistics
```

"Prior troubleshooting", "buyer confirms failed", "video received" are detected by cheap rule
checks over thread history (seller previously asked X; buyer message contains fail-signal
phrases: "still", "same problem", "didn't work", "tried that"). No model call.

---

## 4. Known-issues register (the linchpin)

Flat table. Seller-maintained via AI Instructions UI. Seeded from the analysed threads.

```
known_issue:
  issue_id:           string
  symptom_pattern:    regex | keyword list   # matched against buyer msg (+ has_image flag)
  applies_to_sku:     "*" | prefix | list
  diagnosis:          string                 # short, for the draft to reference
  confidence:         high | medium          # high → skip straight to action
  skip_to_action:     resolve_replace | resolve_refund | request_photo | none
  evidence_required:  none | photo | video
  disposal_note:      bool                   # tell buyer to dispose, don't return
  active:             bool
```

### Seed rows (from the data)

| issue_id            | symptom                                        | confidence | skip_to_action    | evidence | disposal |
|---------------------|------------------------------------------------|------------|-------------------|----------|----------|
| `white_glue_cover`  | front/cover/glass off, panel lifted, exposed board | high    | resolve_replace*  | photo    | yes      |
| `melted_plug`       | burnt/melted plug or socket, overheated        | medium**   | request_photo     | photo    | no       |
| `pp_resistor_nocharge` | won't charge, OEM works, multiple points tried | medium   | request_video     | video    | yes (on refund) |
| `wifi_timeout`      | app timeout, can't pair, WLAN                  | high       | none (send guide) | none     | no       |

\* `white_glue_cover` is `resolve_replace` **only if** current stock is confirmed new-batch;
otherwise `resolve_refund` (repeated old-batch replacements caused Threads 27, 395 to escalate).
The register must carry a `batch_safe` flag the seller flips when stock is known-good.

\*\* `melted_plug` stays `medium` / `request_photo` because it routes to **Tier 3 safety_claim**
first — the register informs the draft the seller eventually approves, it does not auto-resolve a
safety report.

---

## 5. Stage prompts (what the single LLM call gets)

Each stage has a short, fixed instruction. The prompt = stage instruction + matched known-issue
diagnosis/action (if any) + last N thread messages (N=8, already the existing cap). **No policy
dump, no full playbook.** Keep `max_tokens` low (existing 700 is ample; most drafts are shorter).

Stage instruction examples (abbreviated — full text lives in `reply_compose.py`):

- `clarify_or_troubleshoot`: "Acknowledge the issue in one sentence. Ask ONE clarifying question
  OR offer ONE troubleshooting step — not both, not a list. Do not mention video, replacement, or
  refund yet."
- `request_video`: "Troubleshooting has failed. Ask for a short video (WhatsApp +447480850668)
  showing the fault with the evamp logo visible. One short paragraph. Do not offer refund yet."
- `resolve_replace`: "Confirm a replacement is being sent. If disposal_note, tell them to dispose
  of the faulty unit. Ask for delivery name/address only if not already known. One short message."
- `resolve_refund`: "Confirm the refund. If order age > 90 days, note it will go via PayPal and
  ask for the PayPal address as a screenshot. One short message."
- `arrange_return` (EN/OTHER): "Organise the return yourself (free-returns market). Confirm
  you're sending the label, keep it warm and brief. Do NOT ask the buyer to arrange postage."
- `arrange_return_DE` → this never reaches the drafter; it's Tier 3.
- `courier_chase`: "Acknowledge the delay, state you've raised it with courier + warehouse, give
  next update timing. Offer replacement or refund only if the thread shows the parcel is lost."
- `fitment`: "Confirm compatibility in one line and thank them for checking prior. If the reg/
  model isn't in the compatibility data, say you'll confirm rather than guessing."
- `invoice`: "Confirm the invoice has been sent. One line." (Pairs with an invoice-send hook.)

---

## 6. Tiers summary

| Tier | Volume (est.) | Behaviour                                             | Seller action |
|------|---------------|------------------------------------------------------|---------------|
| 1    | ~75%          | One-line draft. Fitment / invoice / wifi / cancel.   | One-tap approve |
| 2    | ~20%          | Single-stage draft. Faulty / delivery / EN returns.  | Approve/edit  |
| 3    | ~5%           | NO resolutive draft. Summary + escalation card.      | Seller handles |

Tier 3 = `safety_claim`, out-of-warranty goodwill, eBay case disputes, **DE returns**. Everything
that free returns used to make contentious for EN/OTHER buyers now drafts in Tier 2.

---

## 7. Follow-up surface (separate from drafting)

A date-diff query, no latency cost, no model call:

- List threads where the last message is from the seller (or eBay) and > N days old with no buyer
  reply, OR where the seller promised an update (regex: "keep you updated", "let you know",
  "I'll check") and hasn't followed up.
- For each, offer a one-tap "draft a nudge" that runs the normal pipeline at `courier_chase` /
  `follow_up` stage.

Build independently of the router; it reads the same `messages` table.

---

## 8. Learning loop (deferred, not MVP)

Log per draft: `{tier, intent, known_issue_id, stage, draft_text, sent_text, was_edited}`
(the existing `draft_feedback` hook). Weekly distill: where sent ≠ draft within a
(tier, intent, known_issue) bucket, surface as a **review-before-promote** suggestion — e.g.
"on `white_glue_cover`, seller consistently removes the troubleshooting line." No silent policy
injection. This is the "learns from me" mechanism; it does not run in MVP.

---

## 9. MVP scope

**In:**
- Rule router (language + intent + known-issue match + tier/stage assignment).
- Known-issues register table + the 4 seed rows + AI Instructions CRUD + `batch_safe` flag.
- Single-stage drafter (one LLM call, stage-scoped prompt, existing provider).
- Follow-up surface (date-diff list + one-tap nudge).
- Tier 3 = route-to-seller with a thread summary. No clever handling.

**Out (non-goals for MVP):**
- Auto-send (explicitly deferred by seller).
- Fitment lookup DB (car/reg → SKU). High value, heavier build — phase 2.
- Invoice-send automation hook — phase 2 (draft-only for now: "invoice sent" is approved manually).
- LLM stage classifier, embedding retrieval, adherence re-check loop — rejected on latency grounds.
- Learning-loop distillation — phase 2.

---

## 10. Success criteria

- Draft latency: single model call, short prompt → target well under the current multi-call time.
- Typical draft: one ask or one action, ≤ ~800 chars, never the whole arc.
- No refund/replacement offered before evidence stage unless a `high`-confidence known-issue match
  says so.
- EN/OTHER returns: draft organises the return; never asks the buyer to arrange postage.
- DE returns and safety claims: never auto-drafted to resolution; always Tier 3.
- Follow-up surface catches stalled threads the seller would otherwise forget.

---

## 11. Open decisions for the seller

1. `batch_safe` flag: who flips it and how is "known-good stock" confirmed? (Blocks correct
   `white_glue_cover` routing between replace and refund.)
2. Follow-up threshold N (days) before a thread surfaces as stalled.
3. Whether `melted_plug` should ever draft past `request_photo` or always sit in Tier 3.
4. Phase-2 ordering: fitment lookup DB vs. invoice-send hook vs. learning loop — which first.
