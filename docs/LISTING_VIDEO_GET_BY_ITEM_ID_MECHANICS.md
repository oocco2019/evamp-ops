# Get listing / video by item ID — mechanics

Goal: given the **item number** (e.g. `136528644539` from `ebay.com/itm/136528644539`), get that **specific listing’s** SKU and then its video IDs. (Many listings can share one SKU; looking up by item ID identifies the exact listing.)

**Implemented:** Trading API GetItem(ItemID) is called first when the input is numeric (9–14 digits). Response SKU is used with getInventoryItem(sku) for video IDs. Fallbacks: input as SKU, cache, on-demand search.

---

## What we have today

- **Inventory API** (REST): `getInventoryItem(sku)`, `getOffers(sku)`, `getInventoryItems()`.  
  No endpoint accepts **item ID / listing ID**. So we either:
  - Scan: `getInventoryItems` + `getOffers(sku)` for every SKU until we find `listing.listingId == item_id` (slow; we added a cache/sync to avoid doing this every time), or
  - Use another API that *does* accept item ID.

---

## Option A: Trading API GetItem(ItemID)

**Idea:** Call Trading API **GetItem** with the item ID. Response can include **SKU** for the listing. Then call Inventory API `getInventoryItem(sku)` to get `product.videoIds`.

**Mechanics:**

1. **Request**
   - **Endpoint:** `POST https://api.ebay.com/ws/api.dll` (production).
   - **Headers:**
     - `X-EBAY-API-IAF-TOKEN: <user_access_token>` (same token we use for Sell API; Trading API uses this for OAuth).
     - `X-EBAY-API-CALL-NAME: GetItem`
     - `X-EBAY-API-SITEID: 0` (US) or `3` (UK) — match marketplace.
     - `X-EBAY-API-COMPATIBILITY-LEVEL: 1085` (or current).
   - **Body:** XML, e.g.:
     ```xml
     <?xml version="1.0" encoding="utf-8"?>
     <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
       <ItemID>136528644539</ItemID>
     </GetItemRequest>
     ```
   - No `RequesterCredentials` when using IAF token.

2. **Response**
   - XML with `<Item>...</Item>`.
   - **SKU:** `<SKU>...</SKU>` is present when the listing is tracked by SKU (e.g. listed via Inventory API or with `InventoryTrackingMethod=SKU`). Many modern listings have this.
   - If SKU is present: use it and call `getInventoryItem(access_token, sku)` → `product.videoIds`.
   - If SKU is absent: listing may be legacy (no SKU). Then we still need a fallback (e.g. cache or one-time search).

3. **Auth**
   - Same **user** OAuth access token we already get for Sell API.
   - Trading API docs say to use that token in `X-EBAY-API-IAF-TOKEN`; no separate scope is documented for GetItem. If the token works, we don’t need a sync for “get by item ID” when the listing has a SKU.

4. **Caveats**
   - Trading API is **XML** (request and response). We need a small XML builder and parser (or a few string templates + regex/parser for `<SKU>` and errors).
   - **SiteId** must match the listing’s marketplace (e.g. UK vs US).
   - Listings created without SKU won’t return SKU; fallback (cache or search) still needed for those.

---

## Option B: Browse API getItemByLegacyId

- **Endpoint:** `GET https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=136528644539`.
- **Purpose:** Buyer-facing item details by legacy item ID.
- **SKU:** Not returned (buyer API; SKU is seller-only). So we **cannot** get SKU from this for “get video by item ID” without another step. Not a direct solution.

---

## Option C: Keep cache/sync (current)

- Sync job builds a DB table `listing_id → sku` from `getInventoryItems` + `getOffers`.
- “Get video by item number” does: cache lookup → then `getInventoryItem(sku)`.
- Works at scale but you have to run and wait for sync; you said you don’t like this.

---

## Recommended path

1. **Try Option A (GetItem by item ID)**  
   - Add one Trading API call: `GetItem(ItemID)` with IAF token, parse XML for `<SKU>`.  
   - If SKU present: use it with `getInventoryItem(sku)` and return video IDs. No sync, no scan.  
   - If SKU absent or GetItem fails (e.g. wrong marketplace/token): fall back to existing behaviour (cache if populated, then on-demand search as last resort).

2. **Keep cache/sync as fallback only**  
   - For listings that don’t expose SKU in GetItem (or if we don’t call Trading API), we still have cache or search. We can make sync optional (e.g. only for large accounts that hit “not found” often).

3. **Decide after a quick test**  
   - Call GetItem for item ID `136528644539` with our current token and see if the response contains `<SKU>`. If yes, we can rely on “pull by item ID” for most listings and only use cache/search for the rest.

If you want to proceed with Option A, next step is: implement a minimal GetItem(ItemID) call (XML request/response) and confirm we get SKU back for your test item; then wire that into “get video by item number” and only fall back to cache/search when GetItem doesn’t return a SKU.
