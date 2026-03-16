# Listing video & eBay identifiers (item ID, offer ID, SKU)

This doc clarifies how eBay identifiers work and how this project uses them, so we don’t mix up **item ID** (listing ID) with **offer ID**.

**CSV inventory:** All of this project's inventory is listed via CSV. Those listings have no Inventory API record. For listing video, use **Trading API only** (GetItem for read, ReviseFixedPriceItem for adding video). See `docs/LISTING_VIDEO_CSV_INVENTORY.md`.

## Terminology

| Term | Meaning | Where it appears |
|------|--------|-------------------|
| **Item number / Item ID / Listing ID** | The number in the listing URL: `ebay.com/itm/136528644539`. Same as **listingId** in Inventory API and **legacyItemId** in Fulfillment API. | User-facing “item number”; eBay Fulfillment `lineItems[].legacyItemId`; Inventory API `offer.listing.listingId`. |
| **Offer ID** | Internal identifier created when you create an offer (Inventory API). **Not** the same as the listing ID. Used only in `getOffer(offerId)`. | Inventory API: `getOffer(offerId)`, `getOffers` response `offers[].offerId`. |
| **SKU** | Seller-defined inventory identifier. Required when listing via Inventory API. | Inventory API: `getInventoryItem(sku)`, `getOffers(sku)`; Fulfillment: `lineItems[].sku`. |

**We do not use offer ID** when the user enters an “item number”. The item number is the **listing ID** (item ID). The Inventory API has no “get by listing ID” endpoint; we resolve listing ID → SKU by searching (see below).

## How we get video ID “by item number”

1. **Try SKU first**  
   Call `getInventoryItem(access_token, input)`. If it succeeds, the input is a SKU; we return that item’s `product.videoIds`.

2. **Cache lookup (fallback)**  
   Table `ebay_listing_sku_cache` maps `listing_id` to `sku`. Populated only when we find a listing via on-demand search (no sync). Optional fallback when GetItem returns no SKU.

3. **On-demand search (fallback)**  
   If cache miss: call `getInventoryItems` (offset = page number), then for each SKU `getOffers(sku)`, match `listing.listingId` to the input. Slow for large inventories; when we find a match we upsert into the cache for next time.

(On-demand search is step 3 above.)  
   Search your inventory for an offer whose `listing.listingId` equals the input:
   - Call `getInventoryItems` (paginated: **offset = page number** 0, 1, 2, …; **limit** = items per page).
   - For each inventory item (SKU), call `getOffers(sku)`.
   - In the offers, read `listing.listingId` (only present for published offers). Compare to the user’s item number (string comparison).
   - When we find a match, we have the SKU; then `getInventoryItem(sku)` gives `product.videoIds`.

We never call `getOffer(offerId)` for this flow, because that endpoint expects an **offer ID**, not a listing/item ID.

## Relation to the rest of the app

- **Sales analytics / order import**  
  Data comes from the **Fulfillment API** (orders, line items). Line items have `lineItemId`, `sku`, and **`legacyItemId`** (the listing item ID). We don’t currently store `legacyItemId` in our DB; if we did, we could map “item number” → SKU from order history.
- **Messages**  
  Threads can have `ebay_item_id` (listing reference), which is the same “item number” / listing ID.

## References

- [Fulfillment API LineItem](https://developer.ebay.com/api-docs/sell/fulfillment/types/sel:LineItem) – `legacyItemId`, `lineItemId`, `sku`.
- [Inventory API getOffer](https://developer.ebay.com/api-docs/sell/inventory/resources/offer/methods/getOffer) – takes **offerId** (path).
- [Inventory API getOffers](https://developer.ebay.com/api-docs/sell/inventory/resources/offer/methods/getOffers) – takes **sku** (query); response includes `offers[].listing.listingId`.
- [Inventory API getInventoryItems](https://developer.ebay.com/api-docs/sell/inventory/resources/inventory_item/methods/getInventoryItems) – **offset** is **page number** (0, 1, 2…), not record offset.
