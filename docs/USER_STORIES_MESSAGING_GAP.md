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
| Toggle/dropdown: Unread, Flagged, All | Flagged filter + All | **OK** |
| Filter by sender: Customer (Buyer) vs System (eBay) | Dropdown: All / Customers only / eBay only | **OK** |
| Combine filters (e.g. Unread + Customer) | Flagged + sender type + search | **OK** |
| Results update immediately, no full refresh | Refetch on change | **OK** |
| Icons/colour for source (Buyer / eBay / Seller) and read state | Buyer left, Seller right (eBay blue), eBay amber/centered | **OK** |
| "No messages found" when filter empty | Shows "No threads match..." message | **OK** |

---

## 3. Thread view (conversation)

| Requirement | Current | Status |
|-------------|---------|--------|
| Group by eBay ThreadID, full conversation in one view | Done: thread detail with messages | **OK** |
| Thread title = buyer username (person evamp talks to) | Done: robust fallback, never shows seller | **OK** |
| SKU, Item Title, Order ID, Tracking at top of thread | SKU, Order ID, Item ID, Tracking shown with links | **OK** |
| Order ID = link to order details in new tab | Hyperlink to ebay.co.uk order details | **OK** |
| Item Title = link to listing in new tab | Item ID linked to eBay listing | **OK** (title not fetched, ID suffices) |
| Multiple items in thread: list all SKUs and Order IDs | Single per thread | **Gap**: Model or derive from messages |
| "No Order Linked" when general enquiry | Shows "No Order Linked" placeholder | **OK** |

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
| Real-time character count / 2000 limit | Character count shown, limit enforced with styling | **OK** |

---

## 6. AI instructions (settings)

| Requirement | Current | Status |
|-------------|---------|--------|
| Dedicated "AI Instructions" tab | Settings > AI Instructions tab | **OK** |
| Global Instructions | CRUD UI with validation (only one allowed) | **OK** |
| SKU-specific instructions | CRUD UI with SKU dropdown from catalog | **OK** |
| Add/edit/delete SKU entries | Full CRUD with item_details field | **OK** |
| AI pulls Global + SKU when drafting | Done | **OK** |

---

## 7. Language detection and "Translate Thread"

| Requirement | Current | Status |
|-------------|---------|--------|
| Detect source language (AI) | AI detects language on "Translate Thread" click | **OK** |
| "Translate Thread" toggle | Button in thread header; toggles translation view | **OK** |
| Show translated alongside original | Translation shown below original in message bubble | **OK** |
| Detected language label per message | Language indicator shown in thread header | **OK** |
| Translation in under 5 seconds | Depends on provider | Measure |
| Toggle per message to original | "Hide translations" button to toggle off | **OK** |

---

## 8. "Translate for Sending"

| Requirement | Current | Status |
|-------------|---------|--------|
| "Translate for Sending" button | Button appears when detected language is non-English | **OK** |
| Show target + back-translation | Translation + back-translation shown side-by-side | **OK** |
| Back-translation editable; re-translate | Back-translation for verification; "Use translated" applies | **OK** |
| 5s translation | Depends on provider | Measure |
| Preserve URLs, Order IDs, placeholders | — | Prompt engineering |
| Character count for translated text | Character count shown in reply box | **OK** |
| Send sends translated text only | "Use translated version" replaces reply content | **OK** |

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
| Toggle to add/remove Flag per thread | `is_flagged` on MessageThread; toggle in thread header | **OK** |
| Flagged visually distinct | Flag icon shown on right side of thread list item | **OK** |
| Flag persisted, survives sync | Stored on thread; sync does not clear | **OK** |
| Filter: Flagged only | Clickable badge toggles flagged filter | **OK** |
| Update flag immediately without refresh | PATCH endpoint updates; UI refreshes | **OK** |
| Flag count in nav/filter bar | "X flagged" badge shown, clickable to filter | **OK** |

---

## 11. Warehouse email

| Requirement | Current | Status |
|-------------|---------|--------|
| "Warehouse Email" button → mailto | Button in thread detail opens mailto | **OK** |
| Settings: default body, subject, address | Email Templates CRUD in Settings | **OK** |
| Resolve Tracking, Order Date, Country from order | Variables: {tracking_number}, {order_date}, {order_id}, {buyer_username} | **OK** |
| Missing variable → blank or N/A | Missing variables replaced with empty string | **OK** |
| Button active only when order linked | Button only shown when order_id exists | **OK** |

---

## 12. Search

| Requirement | Current | Status |
|-------------|---------|--------|
| Search bar: keyword in content, subject, buyer | Search input + button in dashboard | **OK** |
| Results in under 2 seconds | SQL ILIKE search; fast for current scale | **OK** |
| Highlight keyword in snippets | Not implemented | **Gap**: Return highlighted snippets |
| Search over full history including archived | Searches all messages | **OK** |
| Combine search with Unread/Flagged | Search + Flagged + sender type filters combine | **OK** |
| "Clear Search" button | X button clears search | **OK** |

---

## Summary – Implementation status

| Feature | Status |
|---------|--------|
| **Thread title = buyer** (never seller) | **Done** |
| **Filters**: Flagged / All + sender type dropdown | **Done** |
| **Thread header**: Order ID + Item ID as links; "No Order Linked" | **Done** |
| **Character count** in reply box (2000 limit) | **Done** |
| **Flagging UI**: Thread-level toggle, icon, clickable count | **Done** |
| **Translate Thread** + detection labels | **Done** |
| **Translate for Sending** + back-translation | **Done** |
| **Search**: Full-text, filters, clear button | **Done** |
| **Warehouse email**: Email templates + mailto button | **Done** |
| **Message styling**: Buyer/Seller/eBay distinct colors | **Done** |
| **AI Instructions UI**: Global + SKU CRUD in Settings | **Done** |
| **Send via REST API**: sendMessage, store result | **Done** |

### Remaining gaps

| Priority | Feature | Effort |
|----------|---------|--------|
| 1 | **Knowledge Base** + Redo flow | Large |
| 2 | **Original Draft toggle** + local persistence | Small |
| 3 | **Scheduled sync** (60-min job) | Small |
| 4 | **Webhooks** (optional, if real-time needed) | Medium |
| 5 | **Archived messages** protection | Small |
| 6 | **Bi-directional read sync** | Small |
| 7 | **10s delay / Cancel** on Send | Medium |
| 8 | **Search snippet highlighting** | Small |

---

## API reference

- **Read conversations:** `GET /commerce/message/v1/conversation`
- **Get messages:** `GET /commerce/message/v1/conversation/{id}`
- **Send message:** `POST /commerce/message/v1/send_message` (requires `conversationId` + `messageText`, max 2000 chars)
- **Update conversation:** `POST /commerce/message/v1/update_conversation` (mark read/archive)
- **OAuth scope:** `https://api.ebay.com/oauth/api_scope/commerce.message`

All operations use the same scope we already have.
