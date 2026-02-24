# Message attachments (display and send)

This doc describes how message images and other attachments work end-to-end, and what to do if images don’t show.

**Are images saved in the DB?** Yes. Attachment **metadata** (name, type, URL) is stored in `messages.media` (JSON). The actual **file bytes** are stored in the `message_media_blobs` table so we retain attachments after eBay deletes messages (e.g. after ~4 months). On sync, refresh thread, or send, we fetch each `mediaUrl` and store the bytes; the API then returns our blob URL when one exists so the frontend loads from our DB.

---

## Full-size image when clicking (eBay CDN rule)

eBay CDN image URLs use `$_1.` or `$_12.` for thumbnails and `$_57.` for full-size (see [eBay KB 2194](https://developer.ebay.com/support/kb-2194)).

- **Frontend:** The link "open in new tab" uses `ebayImageFullSizeUrl(att.mediaUrl)` (in `MessageDashboard.tsx`): it rewrites `$_1.` / `$_12.` to `$_57.` when the URL contains `ebayimg.com`. So for **eBay URLs** the user gets full-size in the new tab.
- **Backend (our blob):** When we store attachment bytes in `_store_message_media_blobs`, we **fetch the full-size eBay URL** for eBay CDN images: before `httpx.get(url)` we call `_ebay_image_full_size_url(url)` so we store full-size bytes. Then when the user clicks, the API returns our blob URL and we serve that blob (full-size). So "open in new tab" shows full-size for both eBay URLs and our stored blobs.
- **Existing blobs:** Blobs stored before the full-size logic were thumbnails. On the next thread load/sync we **re-fetch and overwrite** existing eBay image blobs with the full-size URL, so no manual delete is needed; one refresh fixes "open in new tab" for that message.

**Code locations:** Frontend: `MessageDashboard.tsx` — `ebayImageFullSizeUrl()`, and `<a href={ebayImageFullSizeUrl(att.mediaUrl)}>`. Backend: `messages.py` — `_ebay_image_full_size_url()`, and in `_store_message_media_blobs` the rewrite is applied to the fetch URL for IMAGE items with `ebayimg.com` in the URL.

---

## How it works (end-to-end)

### 1. Where attachment data lives

| What | Where | When it’s set |
|------|--------|----------------|
| **Metadata** (name, type, URL) | `messages.media` (JSON column) | Sync from eBay, or when you send a message with attachments |
| **File bytes** (for retention after eBay purge) | `message_media_blobs` table | After sync or send: we fetch each `mediaUrl` and store the bytes |

Each message can have `media`: a JSON array of `{ mediaName, mediaType, mediaUrl }`. Types are `IMAGE`, `DOC`, `PDF`, `TXT` (or `FILE` as fallback).

### 2. How display gets the image URL

When you open a thread, the API returns each message’s `media` array. For each attachment:

- **If we have a stored blob** (`message_media_blobs`): the API returns **our** URL, e.g. `https://your-api.com/api/messages/media/{message_id}/{index}`. The frontend loads the image from that URL (same API the app uses).
- **If we don’t have a blob yet**: the API returns the **eBay** `mediaUrl` from `messages.media` (eBay CDN). The frontend loads from eBay.

So for images to show you need **at least one** of:

- `messages.media` to contain an item with a non-empty `mediaUrl` (from eBay), **or**
- A row in `message_media_blobs` for that message/index (then we serve our copy and return our URL).

### 3. When blobs and metadata are written

| Action | What happens |
|--------|----------------|
| **Sync** (full or incremental, FROM_MEMBERS or FROM_EBAY) | Messages from eBay are upserted; `messageMedia` is normalized into `messages.media`. After commit, we call `_store_message_media_blobs` for every message that has media: we fetch each URL and store bytes in `message_media_blobs`. |
| **Refresh thread** | Same as above, but only for that one thread (e.g. after opening the thread or after send). |
| **Send message with attachments** | Sent message is stored with media from the send response; then we store the bytes for those attachments in `message_media_blobs`. |

Existing blobs are skipped (no re-fetch) except for **eBay image** items: for those we re-fetch the full-size URL and overwrite the existing row so "open in new tab" eventually serves full-size (see [Upgrading existing thumbnail blobs](#upgrading-existing-thumbnail-blobs)). Failures to fetch a URL are logged and that attachment is skipped; the rest still run.

#### Upgrading existing thumbnail blobs

Blobs stored before the full-size fetch logic contained thumbnail bytes. The backend does not skip existing rows when the attachment is an eBay image (`mediaType === "IMAGE"` and URL contains `ebayimg.com`): on the next thread load or sync it re-fetches the full-size URL and overwrites the blob row. So after opening the thread again (or refreshing), the media URL for that message/index serves full-size; no manual delete or re-sync is required.

### 4. Frontend

- Thread API response includes `messages[].media` with `mediaName`, `mediaType`, `mediaUrl`.
- **Images** (`mediaType === 'IMAGE'` and `mediaUrl` set): rendered inline in the message bubble; clicking opens full-size (eBay CDN URLs are rewritten from `_1` / `_12` to `_57` via `ebayImageFullSizeUrl` in `MessageDashboard.tsx`).
- **Other types**: shown as links.
- If the API returns a **relative** media URL (e.g. `/api/messages/media/...`), the frontend prepends `VITE_API_URL` so the request goes to the correct host.

---

## What you need to do (setup)

1. **Run sync so messages have media**  
   Message metadata and blobs are filled when we **sync** (or refresh a thread). If threads were loaded before attachments were implemented or before a sync that included media, run a **full sync** (Messages page → Sync → use “Full sync” if available) so we re-fetch messages from eBay and populate `messages.media` and, where possible, `message_media_blobs`.

2. **Optional: public API URL when behind a proxy**  
   If the backend runs behind a reverse proxy and the browser cannot reach `request.base_url` (e.g. internal host/port), set in `.env`:
   ```env
   API_PUBLIC_BASE_URL=https://your-api-domain.com
   ```
   (no trailing slash). Attachment URLs in API responses will use this base so images load in the browser.

3. **Frontend API base**  
   The frontend must call the same API that serves the app (e.g. `VITE_API_URL`). Relative media URLs are resolved against that base so images load from the correct origin.

---

## If images still don’t show (troubleshooting)

**Do this first:** Run a **full sync** from the Messages page (Sync → Full sync if available), then open the thread again. Media metadata and blobs are populated during sync; older data may have been synced before media was stored or when eBay didn’t return attachment URLs.

Then, if images still don’t show:

### 1. Confirm messages have media in the DB

Check that the thread’s messages have non-null `media` with at least one entry and a URL:

```bash
docker compose exec postgres psql -U evamp -d evamp_ops -c "
  SELECT thread_id, message_id, jsonb_pretty(media::jsonb) AS media
  FROM messages
  WHERE media IS NOT NULL AND media != '[]'::jsonb
  LIMIT 3;
"
```

- If `media` is always `null` or `[]`, eBay may not be returning `messageMedia` for those messages, or sync may not have run after that data was available. Run a full sync and/or refresh that thread.
- If `media` has entries but `mediaUrl` (or `mediaURL`) is missing or empty, the eBay response for that conversation may use different field names or omit URLs; we already support both `mediaUrl` and `mediaURL` when reading.

### 2. Confirm blobs (optional but useful for retention)

Check that we’re storing bytes for some attachments:

```bash
docker compose exec postgres psql -U evamp -d evamp_ops -c "
  SELECT message_id, media_index, media_name, length(data) AS bytes
  FROM message_media_blobs
  LIMIT 10;
"
```

- If there are no rows, sync/refresh may not have run, or every fetch may have failed (check backend logs for “Failed to fetch message media for storage”).
- If blobs exist but images still don’t show, the issue is likely the URL we return (see next step).

### 3. Check the URL the frontend receives

- Open DevTools → Network, open a thread that should show an image, and look at the thread response. Find a message with `media` and see what `mediaUrl` is.
  - If it’s an eBay URL (e.g. `https://i.ebayimg.com/...`), the frontend should load it directly (and we don’t need a blob for display).
  - If it’s our URL (e.g. `https://your-api.com/api/messages/media/...` or `http://localhost:8000/...`), the browser must be able to GET that URL; if the app is behind a proxy, set `API_PUBLIC_BASE_URL` as above.
- If `mediaUrl` is null or empty for an attachment, that slot didn’t get a URL from the DB (see step 1).

### 4. CORS / backend reachable

- The page that shows messages must be allowed to load the API (CORS). Backend uses `CORS_ORIGINS` for that.
- For **our** media URLs, the browser will send a GET request to your API; the backend must be reachable at that URL (same origin or allowed CORS and correct host).

---

## Sending attachments

- **eBay:** `sendMessage` accepts optional `messageMedia` (max 5 items). Each has `mediaName`, `mediaType` (`IMAGE`, `DOC`, `PDF`, `TXT`), `mediaUrl` (HTTPS).
- **Backend:** `POST /api/messages/threads/{id}/send` accepts optional `message_media` array. All URLs must be HTTPS.
- **Image upload:** `POST /api/messages/upload-media` (multipart file). Uploads to eBay Commerce Media API and returns `{ mediaUrl, mediaName, mediaType: "IMAGE" }` for use in send. **Requires eBay OAuth scope `sell.inventory`.** If you get 403, add that scope in the eBay Developer Portal and re-authorize the app.

To send a non-image file (DOC, PDF, TXT), host the file at an HTTPS URL and pass `message_media: [{ mediaName, mediaType, mediaUrl }]` in the send request. The app does not provide an upload endpoint for non-image types.

**UI:** In the reply area you can attach images via “Attach image” or by dragging an image onto the reply box (max 5). Generate draft / Send / Attach are in the same area.

---

## Supported file types

| Context | Types |
|--------|--------|
| **Display (from eBay)** | IMAGE, DOC, PDF, TXT (and FILE as fallback). |
| **Send (messageMedia)** | IMAGE, DOC, PDF, TXT. URLs must be HTTPS. |
| **Upload (upload-media)** | Images only: JPG, JPEG, GIF, PNG, BMP, TIFF, TIF, AVIF, HEIC, WEBP (per eBay createImageFromFile). |

---

## Implementation details and pitfalls (do not break)

**File:** `backend/app/api/messages.py`. Keep this behavior when editing.

1. **GET thread — media URL base**  
   `_media_url_for_response()` builds the URL for our blob endpoint. **`request.base_url` is a Starlette `URL` object, not a string.** Use `str(request.base_url).rstrip("/")` (or `API_PUBLIC_BASE_URL` when set). Using `.rstrip()` directly on `request.base_url` raises `AttributeError: 'URL' object has no attribute 'rstrip'`.

2. **GET thread — sorting messages**  
   `msgs = sorted(thread.messages, key=lambda m: m.ebay_created_at)` can raise if any `m.ebay_created_at` is `None`. Use a fallback in the key, e.g. `key=lambda m: m.ebay_created_at or datetime.min.replace(tzinfo=None)`.

3. **GET thread — build_media_items**  
   - Reads from `m.media` (JSON list). Support both `mediaUrl` and `mediaURL` when reading (e.g. `x.get("mediaUrl") or x.get("mediaURL")`).  
   - When `(m.message_id, i) in stored_set`, set `url` to our blob URL via `_media_url_for_response()`.  
   - Only append when `isinstance(x, dict)`. Do not wrap the loop in a try/except that swallows exceptions and returns/drops media; that hides attachments when one item fails.

4. **GET thread — optional hardening**  
   `to_message_response(m)` can wrap `MessageResponse(...)` in try/except and return a fallback message for that row if construction fails (e.g. null date). The fallback must still pass through `media=build_media_items(m)` so attachments are not cleared. Any exception *outside* the per-message builder (e.g. in sort or in `ThreadDetail`) will 500 unless the handler has a top-level try/except that logs and re-raises with a clear detail.

5. **Storing blobs — full-size**  
   In `_store_message_media_blobs`, for each item with `mediaType == "IMAGE"` and a URL containing `ebayimg.com`, rewrite the URL with `_ebay_image_full_size_url(url)` before fetching, so the stored bytes are full-size and "open in new tab" shows full-size. If a blob row already exists for that message/index, we still re-fetch and overwrite it when the item is an eBay image (upgrade path for blobs stored before this logic).
