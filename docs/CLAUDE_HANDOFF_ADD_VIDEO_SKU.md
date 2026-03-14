# Handoff for Claude: Add video to SKU (archived — UI removed)

**Note:** The "Add video to SKU" UI was removed. The app now only has the **Video ID getter** (listing URL or item number → get video IDs). The content below is kept for context if add-video-by-SKU is revisited later.

---

# Add video to SKU — GetSellerList returns no listings (original handoff)

## Goal

**Video management** page, section **2. Add video to all listings for a SKU**: user enters **Video ID**, **SKU**, and **Site** (eBay US, UK, etc.). The app should find all listings for that SKU on that site and add the video to each via Trading API ReviseFixedPriceItem.

## What works

- **Section 1 (Get video ID):** Works. User pastes listing URL or item number; we call Trading API GetItem with `DetailLevel=ReturnAll`, parse `VideoDetails`/`VideoID`, return video ID(s). Works for CSV-uploaded listings.
- **Section 2 UI:** Video ID + SKU inputs, **Site** dropdown (eBay US, UK, Canada, Australia, DE, FR, IT, ES, AT). Green button "Add video to SKU".
- **Backend flow (intended):** `POST /api/listing-video/add-video-to-sku` with `video_id`, `sku`, `marketplace_id` (e.g. EBAY_US). Uses Trading API only: (1) GetSellerList with SKUArray filter and EndTimeFrom/EndTimeTo to get item IDs for that SKU on that site; (2) for each item ID, ReviseFixedPriceItem with the video ID. Streams NDJSON progress.

## What’s failing

- User enters **Video ID** (e.g. `e8835dc819c0a49f652575e8fffff7a1`), **SKU** `use01`, **Site** = **eBay US**. Clicks "Add video to SKU".
- Progress: "Finding listings for SKU use01…"
- Error: **"No listings found for SKU 'use01'. Check the SKU and that you have active listings with that SKU on this site."**
- So **GetSellerList** (with SKUArray containing `use01`, SiteID 0 for US) is returning **no items** (empty ItemArray or no ItemArray).

## Context

- **All inventory is CSV-uploaded.** No Inventory API records; we do not use getInventoryItem or createOrReplaceInventoryItem for this flow. See `docs/LISTING_VIDEO_CSV_INVENTORY.md`.
- **Listings are GTC (Good Till Cancelled).** We use EndTimeFrom = now − 1 hour (clock skew), EndTimeTo = now + 120 days so active and GTC listings are included.
- **Site/marketplace:** Backend passes `marketplace_id` (e.g. EBAY_US) to GetSellerList and ReviseFixedPriceItem so Trading API SiteID is correct (0 = US, 3 = UK, etc.).

## What to investigate

1. **GetSellerList response when 0 items:** Backend logs a warning when the first page has no ItemArray: `GetSellerList sku=use01 site_id=0 returned no ItemArray; response snippet: ...`. Check backend logs for that snippet to see whether eBay returns an error, a different XML structure, or a valid empty result.
2. **SKUArray + CSV/GTC:** Confirm whether GetSellerList’s SKUArray filter returns CSV-uploaded and/or GTC listings. If eBay only associates SKU with Inventory API listings, we may need a different approach (e.g. GetSellerList without SKU filter, then filter by SKU in the response if each Item includes SKU).
3. **Exact SKU:** In Seller Hub (eBay US), confirm the SKU is exactly `use01` (case, no extra spaces) for the listings in question.
4. **Alternative:** If GetSellerList cannot return items by SKU for this account, consider letting the user paste a list of item IDs (or upload a file) and call ReviseFixedPriceItem for each. Endpoint `POST /api/listing-video/add-video-to-listings` already exists (body: `video_id` + `item_ids`); the UI was changed to Video ID + SKU + Site, but that endpoint could be used from a separate “paste item IDs” option.

## Repo / code

- **Backend:** `backend/app/api/listing_video.py` — `add_video_to_sku` (streams NDJSON), `_add_video_to_sku_stream` calls `trading_get_seller_list_by_sku(access_token, sku, marketplace_id)` then `trading_revise_fixed_price_item(access_token, item_id, video_id, marketplace_id)` per item.
- **eBay client:** `backend/app/services/ebay_client.py` — `trading_get_seller_list_by_sku` (GetSellerList with SKUArray, EndTimeFrom/To, pagination), `trading_revise_fixed_price_item` (ReviseFixedPriceItem with ItemID + VideoDetails/VideoID), `_EBAY_MARKETPLACE_TO_SITE_ID`.
- **Frontend:** `frontend/src/pages/VideoManagement.tsx` — section 2: Video ID, SKU, Site dropdown (`SITE_OPTIONS`), `addVideoToSkuStream(vid, sku, onEvent, siteForAdd)`.
- **API:** `frontend/src/services/api.ts` — `addVideoToSkuStream(videoId, sku, onEvent, marketplaceId?)`; request body includes `marketplace_id`.

## Docs

- `docs/GET_VIDEO_ID_HANDOFF.md` — feature overview, GetItem/Revise flow, CSV note.
- `docs/LISTING_VIDEO_CSV_INVENTORY.md` — CSV = Trading API only; no Inventory API for these listings.
- `docs/LISTING_VIDEO_EBAY_IDS.md` — item ID vs offer ID vs SKU.

## Video ID

Use full string; exact character count. Example full ID: `e8835dc819c0a49f652575e8fffff7a1`.
