# Message attachments (display and send)

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
