# Messaging User Stories – Gap Analysis

This document maps the stated user stories to the current implementation and lists what is missing or partial. Use it to prioritize work.

**API choice:** Using eBay **REST Message API** (commerce/message) for all messaging operations (read, sync, send, update). No Trading API required.

---

## 1. eBay connection and sync

| Requirement | Current | Status |
|-------------|---------|--------|
| Connect to eBay Messaging API with valid OAuth token | Done: `commerce.message` scope, token from DB | **OK** |
| Subscribe to webhooks for new messages | Not done; using manual + scheduled sync | **Gap**: Add eBay Notification API subscription for messages (optional, can rely on polling) |
| Webhook POST: process message and update dashboard within 10s | No webhook handler | **Gap**: Add webhook endpoint if real-time needed |
| Scheduled task: sync every 60 min for missed messages | No scheduled job; only manual "Sync" | **Gap**: Add cron/scheduler calling sync every 60 min |
| Use eBay MessageID as primary key to prevent duplicates | Done: `messages.message_id` is PK | **OK** |
| Bi-directional Read/Unread: mark read in dashboard → update on eBay | Read stored locally only | **Gap**: Call `updateConversation` API when user marks read |
| Webhook failure: log, show dismissible notification, rely on next poll | No webhook | **Gap** (only if webhooks added) |
| Polling must respect API limits, skip if daily quota near exhaustion | No quota check | **Gap**: Track call count; skip sync if nearing limit |
| Store all messages, attachments, metadata locally (beyond 90-day policy) | Messages stored; attachments as placeholders only | **Gap**: Store attachment URLs; optionally download blobs |
| Archived messages must not be overwritten/deleted by sync | No "archived" flag | **Gap**: Add `is_archived` flag; sync skips archived threads |

---

## 2. Dashboard filters

| Requirement | Current | Status |
|-------------|---------|--------|
| Toggle/dropdown: Unread, Flagged, All | "Flagged only" checkbox | **Gap**: Add Unread / All; make dropdown |
| Filter by sender: Customer (Buyer) vs System (eBay) | No sender filter | **Gap**: Add sender_type filter |
| Combine filters (e.g. Unread + Customer) | Single filter only | **Gap**: Support multiple filters |
| Results update immediately, no full refresh | Refetch on change | **OK** |
| Icons/colour for source (Buyer / eBay / Seller) and read state | Partial styling | **Gap**: Add icons; clear read/unread distinction |
| "No messages found" when filter empty | Empty list shown | **Gap**: Show explicit message |

---

## 3. Thread view (conversation)

| Requirement | Current | Status |
|-------------|---------|--------|
| Group by eBay ThreadID, full conversation in one view | Done: thread detail with messages | **OK** |
| Thread title = buyer username (person evamp talks to) | Done: robust fallback, never shows seller | **OK** |
| SKU, Item Title, Order ID, Tracking at top of thread | SKU, item id, order id in model; no item **title** | **Gap**: Fetch item title; display header with links |
| Order ID = link to order details in new tab | Plain text | **Gap**: Build eBay URL; render as link |
| Item Title = link to listing in new tab | No item title | **Gap**: Add item title; build URL |
| Multiple items in thread: list all SKUs and Order IDs | Single per thread | **Gap**: Model or derive from messages |
| "No Order Linked" when general enquiry | No placeholder | **Gap**: Show when no order_id |

---

## 4. AI draft

| Requirement | Current | Status |
|-------------|---------|--------|
| "Draft with AI" button in reply box | "Draft reply" button | **OK** (rename if desired) |
| AI uses thread history, global + SKU instructions, Knowledge Base | History + instructions; no KB | **Gap**: Add KB (embeddings or search) |
| Draft in under 5 seconds | Depends on provider | Measure |
| "Redo" with text: save to KB, enable Send; Redo without text = regenerate | No Redo | **Gap**: Add Redo flow |
| AI prioritizes Knowledge Base | No KB | Same |
| Draft for first reply and follow-ups | Same endpoint | **OK** |

---

## 5. Editable draft and confirm

| Requirement | Current | Status |
|-------------|---------|--------|
| AI text in editable text area | Textarea | **OK** |
| No auto-send until user acts | Send is explicit | **OK** |
| Manual edits saved locally (survive refresh) | No persistence | **Gap**: Use localStorage or backend |
| "Original Draft" toggle to revert | No toggle | **Gap**: Store initial draft; add toggle |
| Real-time character count / 2000 limit | No count | **Gap**: Add count; enforce limit |

---

## 6. AI instructions (settings)

| Requirement | Current | Status |
|-------------|---------|--------|
| Dedicated "AI Instructions" tab | Backend has model; no UI | **Gap**: Add Settings tab |
| Global Instructions | AIInstruction type=global | Expose in UI |
| SKU-specific instructions | AIInstruction type=sku | Add CRUD UI |
| Add/edit/delete SKU entries | Backend supports | Add UI |
| AI pulls Global + SKU when drafting | Done | **OK** |

---

## 7. Language detection and "Translate Thread"

| Requirement | Current | Status |
|-------------|---------|--------|
| Detect source language (AI) | `detected_language` field; not populated | **Gap**: Detect on sync or view |
| "Translate Thread" toggle | No toggle | **Gap**: Add toggle; translate all messages |
| Show translated alongside original | No translation UI | **Gap**: Layout side-by-side |
| Detected language label per message | Not shown | **Gap**: Display label |
| Translation in under 5 seconds | Depends on provider | Measure |
| Toggle per message to original | No per-message toggle | **Gap**: Add toggle |

---

## 8. "Translate for Sending"

| Requirement | Current | Status |
|-------------|---------|--------|
| "Translate for Sending" button | Not implemented | **Gap**: Add button |
| Show target + back-translation | No flow | **Gap**: Translate; back-translate; display both |
| Back-translation editable; re-translate | No flow | **Gap**: Implement |
| 5s translation | Depends on provider | Measure |
| Preserve URLs, Order IDs, placeholders | — | Prompt engineering |
| Character count for translated text | No count | **Gap**: Show count |
| Send sends translated text only | — | Ensure correct content |

---

## 9. Sending (REST Message API)

| Requirement | Current | Status |
|-------------|---------|--------|
| Use REST `sendMessage` to send to buyer | Endpoint returns 501 | **Gap**: Implement using `POST /commerce/message/v1/send_message` with `conversationId` + `messageText` |
| Send disabled until at least one character | Frontend check | **OK** |
| Send → 10s delay, button becomes "Cancel"; send after 10s even if window closed | No delay/cancel | **Gap**: Add delay; queue send; Cancel option |
| On success: save to DB, append to thread, use returned `messageId` | Not implemented | **Gap**: Same |
| Error notification (Invalid Token, Buyer Blocked, etc.) | 501 only | **Gap**: Map API errors |
| ParentMessageID / conversationId | API uses `conversationId` | Will use conversation_id |
| Enforce 2000-character limit | No limit | **Gap**: Validate length; block send |

---

## 10. Flagging

| Requirement | Current | Status |
|-------------|---------|--------|
| Toggle to add/remove Flag per thread | `is_flagged` on Message; no UI | **Gap**: Add toggle; consider thread-level flag |
| Flagged visually distinct | No styling | **Gap**: Icon or colour |
| Flag persisted, survives sync | In DB; sync may reset | **Gap**: Sync must not clear flag |
| Filter: Flagged only | Checkbox exists | **OK** |
| Update flag immediately without refresh | No toggle | **Gap**: PATCH endpoint + UI |
| Flag count in nav/filter bar | No count | **Gap**: Show count |

---

## 11. Warehouse email

| Requirement | Current | Status |
|-------------|---------|--------|
| "Warehouse Email" button → mailto | Not implemented | **Gap**: Add button |
| Settings: default body, subject, address | No settings | **Gap**: Add model + UI |
| Resolve Tracking, Order Date, Country from order | Order data in DB | Map placeholders |
| Missing variable → blank or N/A | — | Implement |
| Button active only when order linked | — | Enable only if order_id |

---

## 12. Search

| Requirement | Current | Status |
|-------------|---------|--------|
| Search bar: keyword in content, subject, buyer | No search | **Gap**: Add full-text search API + UI |
| Results in under 2 seconds | — | Index (PostgreSQL FTS) |
| Highlight keyword in snippets | — | Return highlighted snippets |
| Search over full history including archived | — | Include all |
| Combine search with Unread/Flagged | — | Support filters + search |
| "Clear Search" button | — | Add button |

---

## Summary – Implementation order (suggested)

| Priority | Feature | Effort |
|----------|---------|--------|
| 1 | **Thread title = buyer** (never seller) | **Done** |
| 2 | **Filters**: Unread / Flagged / All dropdown; "No messages found" | Small |
| 3 | **Thread header**: Order ID + Item ID as links; "No Order Linked" | Small |
| 4 | **Send via REST API**: Implement `sendMessage`, store result, 2000-char limit | Medium |
| 5 | **Character count** in reply box | Small |
| 6 | **Flagging UI**: Toggle, styling, count | Small |
| 7 | **AI Instructions UI**: Global + SKU CRUD in Settings | Medium |
| 8 | **Translate Thread** + detection labels | Medium |
| 9 | **Translate for Sending** + back-translation | Medium |
| 10 | **Scheduled sync** (60-min job) | Small |
| 11 | **Search**: Full-text, filters, snippets | Medium |
| 12 | **Warehouse email**: Settings + mailto button | Small |
| 13 | **Original Draft toggle** + local persistence | Small |
| 14 | **Redo** + Knowledge Base | Large |
| 15 | **Webhooks** (optional, if real-time needed) | Medium |
| 16 | **Archived messages** protection | Small |
| 17 | **Bi-directional read sync** | Small |
| 18 | **10s delay / Cancel** on Send | Medium |

---

## API reference

- **Read conversations:** `GET /commerce/message/v1/conversation`
- **Get messages:** `GET /commerce/message/v1/conversation/{id}`
- **Send message:** `POST /commerce/message/v1/send_message` (requires `conversationId` + `messageText`, max 2000 chars)
- **Update conversation:** `POST /commerce/message/v1/update_conversation` (mark read/archive)
- **OAuth scope:** `https://api.ebay.com/oauth/api_scope/commerce.message`

All operations use the same scope we already have.
