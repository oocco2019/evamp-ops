# Video ID getter — feature doc

**Status: working.** Single feature: get video ID(s) from an eBay listing. Input is **listing URL or item number only** (no SKU). Uses Trading API GetItem with `DetailLevel=ReturnAll`; video IDs are read from `VideoDetails`/`VideoID`. Works for CSV-uploaded listings.

## Goal

Get video ID(s) from a listing so the user can reuse them. **Input:** listing URL (e.g. https://www.ebay.co.uk/itm/136528644539) or item number (136528644539). **Output:** video ID(s) and title. Use the returned ID with **exact character count** when sending to eBay elsewhere.

## If you get stuck

Write a short summary (what you tried, what failed, errors/screenshots) and ask Claude or another model. See technical details below.

---

## What's implemented

- **Backend:** `GET /api/listing-video/video-id?item_number=...`
  - **Input:** Listing URL or item number only. URL is parsed for `/itm/(\d{9,14})`; otherwise 9–14 digits are treated as item ID. If the value is not a valid item ID/URL, returns 400 with message to enter a listing URL or item number.
  - **Flow:** Trading API `GetItem(ItemID)` with `<DetailLevel>ReturnAll</DetailLevel>` and SiteID from `EBAY_MARKETPLACE_ID`. If response contains `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>`, those video IDs are returned immediately (covers CSV/legacy listings). Otherwise, if `<SKU>` is present or found via inventory search fallback, `getInventoryItem(sku)` → `product.videoIds`. No SKU-as-input path; only listing URL or item number.
  - **Response:** `{ item_number, video_ids: string[], title }`. Use video IDs with exact character count.

- **Frontend:** "Video ID getter" at `/listing-video`. Nav tab: "Video ID getter". Single form: one input (label "Listing URL or item number"), one "Get video ID" button. Result shows title and video ID(s) or "No video."

- **Config:** `EBAY_MARKETPLACE_ID` (e.g. EBAY_GB) drives Trading API `X-EBAY-API-SITEID`. Same user OAuth token as Sell API, sent as `X-EBAY-API-IAF-TOKEN` for GetItem.

---

## CSV / legacy listings

Listings created via Seller Hub CSV have no Inventory API record. Video for those listings is only in the **Trading API GetItem** response (`VideoDetails`/`VideoID`). The getter uses GetItem with ReturnAll and returns those IDs when present. No SKU input; only listing URL or item number.

---

## Technical details

- **Trading API GetItem:** POST to `https://api.ebay.com/ws/api.dll`. Headers: `X-EBAY-API-IAF-TOKEN`, `X-EBAY-API-CALL-NAME: GetItem`, `X-EBAY-API-SITEID` (from `EBAY_MARKETPLACE_ID`), `X-EBAY-API-COMPATIBILITY-LEVEL: 1085`. Request: `<GetItemRequest>` with `<DetailLevel>ReturnAll</DetailLevel>` and `<ItemID>...</ItemID>`. Response: `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>`, `<Item><SKU>`, `<Item><Title>`, or `Errors/Error`.

- **Relevant files:** `backend/app/api/listing_video.py` (get_video_id endpoint), `backend/app/services/ebay_client.py` (trading_get_item). Frontend: `frontend/src/pages/VideoManagement.tsx`, `frontend/src/services/api.ts` (listingVideoAPI.getVideoId).

- **Other docs:** `docs/LISTING_VIDEO_CSV_INVENTORY.md`, `docs/LISTING_VIDEO_EBAY_IDS.md`.

---

## Success criteria

- User pastes a listing URL or item number and gets back the video ID(s) for that listing (or "No video").
- Video ID is used with exact character count when passed to other eBay APIs.
