# Get video ID — feature doc and handoff

**Status: working.** CSV/legacy listings (e.g. created via Seller Hub CSV) are supported via Trading API GetItem with `DetailLevel=ReturnAll`; video IDs are read from `VideoDetails`/`VideoID` and returned without using the Inventory API.

## Goal

Single capability: **get video ID(s) from an eBay listing** so the user can reuse them. Input: listing URL (e.g. https://www.ebay.co.uk/itm/136528644539), item number (136528644539), or SKU. Output: video ID(s) for that listing.

---

## If you get stuck

**Write a short summary** (what you tried, what failed, error messages or screenshots) and **ask Claude** (or another capable model). Handoff-style summaries plus the technical details in this doc are enough to unblock. Do not spend hours guessing—summarise and get a second pass.

---

## What's implemented

- **Backend:** `GET /api/listing-video/video-id?item_number=...`
  - **Input:** Item number, listing URL, or SKU. URL is parsed for `/itm/(\d{9,14})`; otherwise if input is 9–14 digits it's treated as item ID; otherwise it's treated as SKU.
  - **Flow:**
    1. **If input is item ID or URL:** Trading API `GetItem(ItemID)` with `<DetailLevel>ReturnAll</DetailLevel>` and SiteID from `EBAY_MARKETPLACE_ID`. Response may include `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>` (only when caller is the seller). If **video_ids** are present in the GetItem response, they are returned immediately (covers CSV/legacy listings that have no Inventory API record). Otherwise: if `<SKU>` is present, or found via inventory search fallback, then `getInventoryItem(access_token, sku)` → `product.videoIds`.
    2. **If input is SKU:** Direct `getInventoryItem(access_token, input)` → `product.videoIds`.
  - **Response:** `{ item_number, video_ids: string[], title }`. Each `video_ids` entry is the full ID from eBay; **use exact character count** when passing to eBay APIs (e.g. when adding video to another listing)—do not truncate or pad.

- **Add video to SKU:** `POST /api/listing-video/add-video-to-sku` with body `{ "video_id": "...", "sku": "..." }`. Gets the inventory item for the SKU, merges the video_id into `product.videoIds` (no duplicate), then `createOrReplaceInventoryItem`. All listings that use this SKU share the same inventory item, so the video appears on all of them (~10 SKUs across 2k+ listings).

- **Frontend:** "Video management" page at `/listing-video`. Section 1: Get video ID (listing URL/item number/SKU). Section 2: Add video to SKU (video ID + SKU inputs, "Add video to SKU" button).

- **Config:** `EBAY_MARKETPLACE_ID` (e.g. EBAY_GB) drives Trading API `X-EBAY-API-SITEID`. Same user OAuth token as Sell API, sent as `X-EBAY-API-IAF-TOKEN` for GetItem.

---

## Past issues (resolved)

- **CSV/legacy listings:** No Inventory API record, so `getInventoryItem(sku)` 404 and inventory search never found them. **Fix:** GetItem with `DetailLevel=ReturnAll` returns `VideoDetails`/`VideoID` when the caller is the seller; we return those immediately and skip Inventory API.
- **Video ID format:** Use the returned ID with **exact character count** when sending to eBay (no truncation or padding).
- **SKU vs item number:** For CSV-created listings, use item number or listing URL; SKU lookup only works for listings that exist in the Inventory API.

---

## Technical details for debugging

- **Trading API GetItem:**
  - Endpoint: `POST https://api.ebay.com/ws/api.dll`
  - Headers: `X-EBAY-API-IAF-TOKEN` (user access token), `X-EBAY-API-CALL-NAME: GetItem`, `X-EBAY-API-SITEID` (from `EBAY_MARKETPLACE_ID`), `X-EBAY-API-COMPATIBILITY-LEVEL: 1085`
  - Request body: XML `GetItemRequest` with `<DetailLevel>ReturnAll</DetailLevel>` and `<ItemID>...</ItemID>`. ReturnAll is required so eBay returns `VideoDetails`/`VideoID` for listings that have video (e.g. CSV-uploaded listings).
  - Response: XML with `<Item><SKU>`, `<Item><Title>`, `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>`, or `Errors/Error`. VideoDetails is only returned when the caller is the item's seller. We parse and return `video_ids` from VideoDetails; if any are present we skip Inventory API.

- **Inventory API:**
  - `getInventoryItem(sku)` — one inventory item per SKU; `product.videoIds` is the list of video IDs.
  - `getInventoryItems(limit, offset)` — **offset is page number** (0, 1, 2…), not record offset.
  - `getOffers(sku)` — returns offers for that SKU; each offer can have `listing.listingId` (listing/item ID).

- **Relevant files:**
  - Backend: `backend/app/api/listing_video.py` (single endpoint, URL/item-id/SKU handling, GetItem + inventory fallback), `backend/app/services/ebay_client.py` (`trading_get_item`, `get_inventory_item`, `get_inventory_items`, `get_offers`).
  - Frontend: `frontend/src/pages/VideoManagement.tsx`, `frontend/src/services/api.ts` (`listingVideoAPI.getVideoId`).
  - Config: `EBAY_MARKETPLACE_ID` in `backend/app/core/config.py`; Trading site ID map in `ebay_client.py` (`_EBAY_MARKETPLACE_TO_SITE_ID`).

- **Docs in repo:**
  - `docs/LISTING_VIDEO_GET_BY_ITEM_ID_MECHANICS.md` (GetItem vs Inventory API), `docs/LISTING_VIDEO_EBAY_IDS.md` (item ID vs offer ID vs SKU).

---

## CSV / legacy listings (listings created via CSV upload)

Listings created via Seller Hub CSV or legacy Trading API have **no Inventory API record**. So `getInventoryItem(sku)` returns 404 and the inventory search (getInventoryItems + getOffers) never finds them. For those listings, video (if any) is only exposed by the **Trading API GetItem** response: eBay returns `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>` when the caller is the seller. The code now requests `<DetailLevel>ReturnAll</DetailLevel>`, parses `VideoDetails`/`VideoID`, and returns those `video_ids` immediately when present—so item-number/URL lookup can succeed for CSV listings without touching the Inventory API.

## What to fix / investigate (if still failing)

1. **GetItem still no VideoDetails:** Verify the listing actually has a video and the token is for the seller. Optionally log the raw GetItem response body (or a sanitized slice) to confirm whether eBay returns VideoDetails for this item.
2. **Why inventory search doesn't find** the listing: only relevant for non-CSV listings; token/account, marketplace, or pagination. Confirm getInventoryItems returns items and getOffers(sku) returns `listing.listingId` for the right item.
3. **SKU "uke03" 404:** For CSV-created listings there is no Inventory record; use item number/URL path instead. If the listing is in Inventory API under a different SKU, use that exact SKU.
4. **Optional:** If video is managed via Commerce Media API instead of Trading API, a separate integration may be needed; GetItem is the documented path for video on the listing for the seller.

---

## Success criteria

- User can paste https://www.ebay.co.uk/itm/136528644539 (or 136528644539) and get back the video ID(s) for that listing.
- **Video ID:** When using the returned video ID elsewhere (e.g. adding to another listing via API), use the full string with **exact character count**—no truncation or padding.
- Or user can paste the exact SKU as stored in eBay's API and get back that inventory item's video IDs.
- No sync, no "add video to SKUs" required for this handoff; just "get video ID" from one listing/URL or SKU.
