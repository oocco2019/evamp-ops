# Message attachments (display and send)

## Where attachments are stored

- **Metadata:** Always in your DB. `messages.media` is a JSON array of `{ mediaName, mediaType, mediaUrl }` (and is kept when syncing or sending).
- **File bytes (for retention after eBay purge):** The app **stores a copy of attachment bytes** in PostgreSQL so you still have the files when eBay deletes messages (e.g. after ~4 months). When we sync or send a message that has attachments, we fetch each `mediaUrl` and save the bytes in the **`message_media_blobs`** table (one row per attachment: `message_id`, `media_index`, `data` bytea, plus name/type/content-type). Thread detail and images are then served from our DB when a blob exists: the API returns our URL (e.g. `/api/messages/media/{message_id}/{index}`) so the frontend loads the stored copy. If no blob exists yet (e.g. old sync), the API still returns the eBay `mediaUrl`; once synced again or after send, blobs are filled in.
- **Upload/send flow:** When you attach an image and send, the file is uploaded to eBay (Commerce Media API) and we store the sent message’s media metadata. We then fetch that URL and save the bytes into `message_media_blobs` so we retain it after eBay removes the message.

### When blobs are stored (coverage)

All paths that persist a message with attachments also store the attachment bytes, so **all images from pulled messages are stored** (as long as the fetch of the media URL succeeds; failures are logged and skipped):

| Path | When | Storage |
|------|------|--------|
| **Refresh thread** | Single-thread message fetch (open thread / refresh) | After commit, each message with media → `_store_message_media_blobs` |
| **Send message** | User sends a reply with attachments | After commit, `sent_media` → `_store_message_media_blobs` |
| **FROM_MEMBERS full sync** | Full sync (no start_time) | After commit, collected `messages_with_media` → store each |
| **FROM_MEMBERS incremental** | Incremental sync (conversations since last sync) | After commit, `incr_messages_with_media` → store each |
| **FROM_EBAY sync** | eBay system messages (returns, cases, etc.) | After each page commit, `ebay_page_messages_with_media` → store each |

Existing blobs are skipped (no re-fetch). To verify storage, query the table (use your DB user, e.g. `evamp`):

```bash
docker compose exec postgres psql -U evamp -d evamp_ops -c "SELECT message_id, media_index, media_name, length(data) FROM message_media_blobs LIMIT 10;"
```

## Display (received messages)

Attachments are stored on each message as `media`: an array of `{ mediaName, mediaType, mediaUrl }`.

- **Stored in DB:** `messages.media` (JSON). Populated when syncing from eBay (FROM_MEMBERS, FROM_EBAY).
- **API:** Thread detail includes `messages[].media`. Frontend shows images inline and other types as links.
- **eBay types:** `IMAGE`, `DOC`, `PDF`, `TXT`. If eBay returns another type it is normalized to `FILE`.

**UI:** Images render as thumbnails in the bubble. Clicking an image opens the full-size version in a new tab (eBay CDN URLs are rewritten from `_1`/`_12` to `_57` per [eBay KB 2194](https://developer.ebay.com/support/kb-article?KBid=2194)). Non-image attachments show as links.

## Sending attachments

- **eBay:** `sendMessage` accepts optional `messageMedia` (max 5 items). Each has `mediaName`, `mediaType` (`IMAGE`, `DOC`, `PDF`, `TXT`), `mediaUrl` (HTTPS).
- **Backend:** `POST /api/messages/threads/{id}/send` accepts optional `message_media` array. All URLs must be HTTPS.
- **Image upload:** `POST /api/messages/upload-media` (multipart file). Uploads to eBay Commerce Media API and returns `{ mediaUrl, mediaName, mediaType: "IMAGE" }` for use in send. **Requires eBay OAuth scope `sell.inventory`.** If you get 403, add that scope in the eBay Developer Portal and re-authorize the app.

## Supported file types

| Context | Types |
|--------|--------|
| **Display (from eBay)** | Any type returned by eBay: IMAGE, DOC, PDF, TXT (and FILE as fallback). |
| **Send (messageMedia)** | IMAGE, DOC, PDF, TXT. URLs must be HTTPS. |
| **Upload (upload-media)** | Images only: **JPG, JPEG, GIF, PNG, BMP, TIFF, TIF, AVIF, HEIC, WEBP.** Same as [eBay createImageFromFile](https://developer.ebay.com/api-docs/commerce/media/resources/image/methods/createImageFromFile). |

To send a non-image file (DOC, PDF, TXT), you must host the file at an HTTPS URL and pass `message_media: [{ mediaName, mediaType, mediaUrl }]` in the send request. The app does not provide an upload endpoint for non-image types.

**UI:** In the reply area you can attach images via "Attach image" (file picker) or by dragging an image file onto the reply box. When dragging over the box, the border highlights to indicate drop; max 5 attachments per message. "Generate draft" sits next to the voice/instructions area; Send and Attach remain at the bottom.
