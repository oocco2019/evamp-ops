# Message sync – logic and optimization

**Implemented:** Incremental sync (start_time + FROM_MEMBERS + FROM_OWNERS merge), full sync for manual button only, after-send single-thread refresh.

---

## High-level flow

1. **Stub cleanup** – Delete any `stub-*` threads/messages from DB.
2. **Token** – Get eBay access token.
3. **Member/owner sync** – Either **full** (manual button) or **incremental** (background/tab focus); then **FROM_EBAY sync** – unchanged.
4. **Metadata** – Update `messages_last_sync_at` and `messages_member_last_sync_at` (member uses sync start time to avoid gaps).

Only one sync runs at a time (lock); concurrent calls get 503.

**Full sync** (`full=true`, manual "Sync messages"): FROM_MEMBERS only, no start_time, paginate list and fetch all messages per page (same as before). Safety net / recovery.

**Incremental sync** (`full=false`, background poll, tab focus): Read `messages_member_last_sync_at` as start_time. Fetch FROM_MEMBERS and FROM_OWNERS conversation lists in parallel (both with start_time, paginate fully). If FROM_OWNERS fails (e.g. API unsupported), use FROM_MEMBERS only. Merge by conversation_id; fetch messages only for that deduplicated set (with correct conversation_type per source). Upsert threads/messages; commit. First run (no start_time): full FROM_MEMBERS list to establish baseline, then same message fetch.

**After send:** Frontend calls `POST /api/messages/threads/{thread_id}/refresh` instead of sync. Backend refetches that conversation’s messages (FROM_MEMBERS) and upserts. Single API call.

---

## FROM_MEMBERS (main source of slowness)

- **No incremental filter:** We always fetch **all** FROM_MEMBERS conversations (`start_time=None`). Reason: with `start_time`, eBay only returns threads with **buyer** activity since that time; threads where the **seller** replied last are excluded, so sent messages would never appear. So every sync is “full” for member threads.
- **Pagination:** One GET per page of conversations (`limit=50`, `offset`).
- **Per page:**
  1. **1 API call** – `GET /commerce/message/v1/conversation?conversation_type=FROM_MEMBERS&limit=50&offset=N`
  2. **Up to 50 API calls in parallel** – For each conversation on the page, `GET /commerce/message/v1/conversation/{conversation_id}` to fetch **all** messages in that conversation (ebay_client paginates internally until no `next`).
  3. **1 DB query** – Batch-load existing message IDs for that page’s messages.
  4. **In-memory processing** – Upsert threads/messages; no per-row commit.
- **Single commit** – One `db.commit()` after the entire FROM_MEMBERS loop (all pages).
- **Concurrency:** Up to 10 concurrent “fetch messages for conversation” requests per page (semaphore 10).

So for **T** total member conversations:

- Conversation list: **ceil(T / 50)** calls.
- Messages: **T** calls (each call may do multiple HTTP requests if a thread has >50 messages, because `fetch_all_conversation_messages` paginates).
- Total HTTP: **ceil(T/50) + T** (minimum), plus extra for any conversation with >50 messages.

Example: 1,227 threads → 25 list pages + 1,227 message fetches = **1,252+** HTTP calls before FROM_EBAY.

---

## FROM_EBAY

- **Progressive offset:** Stored in `SyncMetadata` key `ebay_messages_offset` so we can resume.
- **Pages per run:** 1 page (normal sync) or 5 pages (full_sync).
- **Per page:** Same pattern – 1 conversations page + N message fetches (up to 50 conversations per page), semaphore 10, batch DB lookup, upsert. Commit **per page** so progress survives timeout.
- When we reach the end of the list, offset is reset to 0 for future runs.

---

## What makes sync slow (current design)

| Factor | Current behaviour |
|--------|-------------------|
| **FROM_MEMBERS scope** | Always full list (no `start_time`), so every sync touches every member thread. |
| **Messages per conversation** | We fetch **all** messages per conversation (paginated in ebay_client); long threads = many HTTP calls per thread. |
| **No “only new” for messages** | We don’t ask eBay “messages since X”; we pull full thread every time. |
| **Single commit for FROM_MEMBERS** | Long run of work before first commit; no checkpoint if the request times out mid-way. |
| **FROM_EBAY after FROM_MEMBERS** | FROM_MEMBERS must finish before FROM_EBAY starts; no parallelisation of the two phases. |
| **Network** | 1,200+ conversations ⇒ 1,200+ message API calls; latency and rate limits dominate. |

---

## Existing safeguards

- **Semaphore 10** – Caps concurrent “get messages for conversation” requests per page.
- **Batch DB read** – One query per page for “existing message IDs” instead of per-message lookups.
- **FROM_EBAY** – 1 page per normal run, commit per page, offset saved for next run.

---

## Summary for Opus / recommendations

- **Current logic:** One lock; stub cleanup + token; then **full** FROM_MEMBERS (paginated conversations, then **all** messages per conversation, semaphore 10, one commit at the end); then FROM_EBAY (1 or 5 pages, commit per page, offset persisted). No incremental for member conversations; no “messages since” for individual threads.
- **Likely levers:** Incremental strategy for FROM_MEMBERS that still surfaces seller-replied threads (e.g. hybrid: periodic full + more frequent incremental?), skip or shorten message fetch when we already have the latest message, parallel FROM_MEMBERS vs FROM_EBAY, smaller pages or checkpoints with intermediate commits, or backend time limit + “sync in background” so the HTTP request returns early and sync continues in a worker.

If you get concrete recommendations from Opus (e.g. “add start_time and run a full member sync every N minutes”), we can map them onto this flow and implement.
