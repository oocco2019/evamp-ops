# Message sync — handoff for review (Opus / follow-up)

This document summarizes how eBay message sync works in **evamp-ops**, what the product owner finds painful, what already works, and what UX goal we are optimizing for. The **appendix** contains verbatim code extracted from the repo so you can suggest concrete improvements without re-reading the whole codebase.

**Repo paths (main implementation):**

- `backend/app/api/messages.py` — global lock, `POST /api/messages/sync`, incremental vs full member sync, FROM_EBAY pagination, metadata
- `backend/app/services/ebay_client.py` — Commerce Message API HTTP calls
- `frontend/src/pages/MessageDashboard.tsx` — when sync runs from the UI (important: the primary button behavior)
- `frontend/src/services/api.ts` — axios timeout for sync

---

## Product goal (UX)

When someone opens the **message center** because a buyer just messaged, they need to see that thread **quickly**. Today, the owner reports:

- **Incremental sync** often does not surface new messages when they need them.
- They **cannot interrupt** a sync already in progress to run a **full** sync.
- **Full sync** can **time out** (client-side 90s limit + long server work).
- Net effect: minutes spent retrying sync instead of replying; replying on eBay directly would have been faster.

**Desired state:** Opening the message center (or selecting a thread) should have **minimal friction** for urgent replies—ideally comparable to “always fresh enough” without fighting the sync system.

---

## What works well (per owner)

- **“Cron” behavior** — In practice this is **not** a server cron job. The **frontend** (`MessageDashboard`):
  - Runs an **incremental** sync (`full=false`) on a **~90s timer** after load.
  - Runs **incremental** sync again when the tab becomes **visible** (`visibilitychange`).
  - That periodic behavior is reliable enough that the owner considers it “what works.”

**Note:** `MESSAGE_SYNC_INTERVAL_MINUTES` exists in `backend/app/core/config.py` but is **not referenced** elsewhere in the backend; the live interval is **frontend-controlled** (`SYNC_POLL_INTERVAL_MS = 90_000`).

---

## Pain points (per owner) + technical causes

### 1. Full sync times out

- **Frontend:** `messagesAPI.sync(90000, full)` — **90 second** axios timeout (`frontend/src/services/api.ts`).
- **Backend:** `POST /api/messages/sync` with `full=true` runs `_sync_from_members_full`, which:
  - Pages **all** `FROM_MEMBERS` conversations (50 per page) and, for **each page**, fetches **all messages** for **every** conversation in parallel (semaphore 10).
  - Commits the DB **once at the end** of the entire full member pass (`await db.commit()` after the `while True` loop), then downloads media blobs.
  - So a large inbox = **many** HTTP calls + **one** long transaction before commit. Any **proxy/gateway timeout** or **client timeout** kills the whole request; partial progress for that path is **not** committed mid-flight (unlike FROM_EBAY, which commits per page).

### 2. Cannot interrupt in-flight sync to run full sync

- **Single global lock:** `asyncio.Lock()` on `_sync_lock`. If a sync is running, another `POST /sync` (including from the UI) gets **503** with `"Sync already in progress."`
- There is **no** queue, priority, or cancellation—only wait until the lock is free.

### 3. Incremental sync often “not useful”

- eBay **getConversations** with `start_time` + `FROM_MEMBERS` only returns conversations with **activity** since that time. The code **explicitly** documents a known limitation:
  - **Seller-only replies** may **not** move the conversation into the incremental set the way buyers expect.
- So **incremental** can miss threads where the **last** activity was **seller**-side only, until a **full** member sync or a **per-thread refresh** runs.

### 4. “Sync messages” button is always `full=true` (not incremental)

- The main **Sync messages** button calls `handleSync(true)` — **full** sync every time.
- The **automatic** 90s timer uses `handleSync()` default → **`full=false`** (incremental).
- So manual “sync” is the **heavy** path; background polling is the **light** path—opposite of what many “refresh now” buttons do.

---

## Architecture cheat sheet

| Mechanism | Behavior |
|-----------|----------|
| `POST /api/messages/sync?full=` | `full=false`: incremental **FROM_MEMBERS** using `messages_member_last_sync_at` as `start_time`; may chain **periodic full** if last full sync > 10 min old. `full=true`: **only** `_sync_from_members_full` (no `start_time`). |
| After member sync | Always runs **FROM_EBAY** (system messages) for **up to** `max_pages` (5 if `full_sync`, else **1** page per run), with offset stored in `ebay_messages_offset` to survive timeouts. |
| Metadata keys | `messages_last_sync_at`, `messages_member_last_sync_at`, `messages_last_full_sync_at`, `ebay_messages_offset` |
| Per-thread | `POST /api/messages/threads/{thread_id}/refresh` — **one** conversation, **no** global lock; best for “I have this thread id and need latest messages now.” |

---

## Suggested directions for Opus (non-prescriptive)

- **Prioritize “open thread” vs “global sync”:** e.g. auto-refresh **selected** thread on open, or lightweight **recent unread** query, without waiting for full inbox sync.
- **Decouple or prioritize syncs:** separate lock for “full” vs “incremental” vs “single thread”, or allow **cancel/replace** (careful with eBay rate limits).
- **Chunked full sync with commits:** commit **per page** (or per batch) in `_sync_from_members_full` so timeouts still save progress (similar to FROM_EBAY).
- **Raise or remove the 90s client timeout** for full sync; align with **server/proxy** timeouts.
- **Revisit button semantics:** e.g. “Quick sync” = incremental, “Full backfill” = full, or “Refresh this thread” prominent.
- **Align incremental with eBay semantics:** if `start_time` excludes seller-only activity, compensate (e.g. periodic full, or refresh **unread** threads by id list).

---

## Appendix A — Frontend (sync entry points)

**File:** `frontend/src/services/api.ts`

```typescript
  sync: (timeoutMs = 90000, full = false) =>
    api.post<{ message: string; synced: number }>('/api/messages/sync', {}, { timeout: timeoutMs, params: { full: full ? 'true' : undefined } }),
```

**File:** `frontend/src/pages/MessageDashboard.tsx` (excerpts)

```tsx
  const handleSync = useCallback(async (full = false) => {
    if (syncingRef.current) return
    syncingRef.current = true
    setSyncing(true)
    setError(null)
    setSyncStatus('syncing')
    setSyncMessage(full ? 'Full sync: fetching all threads from eBay...' : 'Syncing with eBay... this may take up to a minute.')
    try {
      const res = await messagesAPI.sync(90000, full)
      // ...
    } catch (e: unknown) {
      // timeout: 'Sync failed: Request timed out (90s)...'
      // 503: 'Sync already in progress.'
    } finally {
      syncingRef.current = false
      setSyncing(false)
    }
  }, [loadThreads, loadFlaggedCount])

  const SYNC_POLL_INTERVAL_MS = 90_000

  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    const scheduleNext = () => {
      timeoutId = setTimeout(() => {
        handleSync().finally(scheduleNext)
      }, SYNC_POLL_INTERVAL_MS)
    }
    const syncOnVisible = () => {
      if (document.visibilityState === 'visible') {
        loadThreads()
        loadFlaggedCount()
        handleSync()
      }
    }
    const initialTimer = setTimeout(() => {
      handleSync().finally(scheduleNext)
    }, 500)
    document.addEventListener('visibilitychange', syncOnVisible)
    return () => { /* cleanup */ }
  }, [handleSync, loadThreads, loadFlaggedCount])

        <button
          type="button"
          onClick={() => handleSync(true)}
          disabled={syncing}
          title="Full sync: fetches all threads from eBay (including where you were last to reply)"
        >
          {syncing ? 'Syncing...' : 'Sync messages'}
        </button>
```

---

## Appendix B — eBay client (Commerce Message API)

**File:** `backend/app/services/ebay_client.py` (excerpts)

```python
async def fetch_message_conversations_page(
    access_token: str,
    conversation_type: str = "FROM_MEMBERS",
    conversation_status: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "conversation_type": conversation_type,
        "limit": min(limit, 50),
        "offset": offset,
    }
    if conversation_status:
        params["conversation_status"] = conversation_status
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.EBAY_API_URL}{MESSAGE_API_BASE}/conversation",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
        )
        r.raise_for_status()
        return r.json()


async def fetch_all_conversations(
    access_token: str,
    conversation_type: str,
    start_time: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all conversations for a type (paginating), optionally filtered by start_time."""
    all_conversations: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = await fetch_message_conversations_page(
            access_token,
            conversation_type=conversation_type,
            start_time=start_time,
            limit=limit,
            offset=offset,
        )
        conversations = data.get("conversations") or []
        all_conversations.extend(conversations)
        total = data.get("total") or 0
        if not conversations or offset + len(conversations) >= total or not data.get("next"):
            break
        offset += limit
    return all_conversations


async def fetch_all_conversation_messages(
    access_token: str,
    conversation_id: str,
    conversation_type: str = "FROM_MEMBERS",
    page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all messages in a conversation, paginating as needed."""
    all_messages: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = await fetch_conversation_messages_page(
            access_token,
            conversation_id,
            conversation_type=conversation_type,
            limit=page_size,
            offset=offset,
        )
        messages = data.get("messages") or []
        all_messages.extend(messages)
        if not data.get("next") or offset + len(messages) >= (data.get("total") or 0):
            break
        offset += page_size
    return all_messages
```

---

## Appendix C — Backend: lock, sync route, full member sync, main orchestrator

**File:** `backend/app/api/messages.py`

**Lines 11–12 (module scope):**

```python
_sync_lock = asyncio.Lock()
_sync_in_progress = False
```

- **Lines 1254–1907:** `sync_messages`, `_sync_from_members_full`, `_do_sync_messages`

**Verbatim extract:** [`MESSAGE_SYNC_EXTRACT_messages_py_1254_1907.py`](./MESSAGE_SYNC_EXTRACT_messages_py_1254_1907.py) (includes a short header; body is `messages.py` lines 1254–1907)

Regenerate after edits:

```bash
sed -n '1254,1907p' backend/app/api/messages.py > docs/MESSAGE_SYNC_EXTRACT_messages_py_1254_1907.py
```

---

## Appendix D — Single-thread refresh (fast path)

**File:** `backend/app/api/messages.py` — `POST /threads/{thread_id}/refresh` — **does not** use `_sync_lock`; refetches one conversation and upserts. Use this when the UI knows a thread id or after send.

---

*Generated for internal review. Update line numbers if you change `messages.py`.*
