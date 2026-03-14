# Listing video: CSV inventory = Trading API only

**Important:** All of this project's eBay inventory is listed via **CSV upload** (Seller Hub bulk / legacy flow). Those listings do **not** create **Inventory API** records. Therefore:

- **Reading** (get video ID from a listing): use **Trading API GetItem** with `DetailLevel=ReturnAll`; video is in `<Item><VideoDetails><VideoID>...</VideoID></VideoDetails>`. Implemented.
- **Writing** (add video to listings): use **Trading API ReviseFixedPriceItem** (or equivalent Revise call), passing `<ItemID>` and the video in the same XML path as GetItem returns it (e.g. `Item.VideoDetails.VideoID`). Do **not** use Inventory API (`getInventoryItem`, `createOrReplaceInventoryItem`) for CSV-listed inventory — those calls 404 for SKUs that only exist in the Trading API / Seller Hub context.

## Why this matters

- **Inventory API** is a separate abstraction. `getInventoryItem(sku)` and `createOrReplaceInventoryItem` only work when the listing was created through the Inventory API flow. CSV-uploaded listings have no Inventory API entity; `getInventoryItem("use01")` (or any CSV SKU) returns 404.
- **Trading API** is where CSV listings live. GetItem already returns video for these listings; adding video must be done with ReviseFixedPriceItem (or the appropriate Revise call) so that CSV and non-CSV behavior stay consistent and discoverable in one place.

## For future implementation (add video to CSV listings)

1. Use **Trading API** only for this inventory.
2. **ReviseFixedPriceItem:** POST to `https://api.ebay.com/ws/api.dll`, call name `ReviseFixedPriceItem`, with `<ItemID>` and the video ID in the XML. The element that carries video in the GetItem response (e.g. `Item.VideoDetails.VideoID`) is the same to set in the Revise request.
3. To add video to "all listings for a SKU": you need a list of item IDs for that SKU (e.g. from Seller Hub Reports or your own data). Then iterate and call ReviseFixedPriceItem for each item ID with the video ID.

## Current app behaviour

The app exposes a **Video ID getter** only (nav: "Video ID getter", route `/listing-video`). User enters a listing URL or item number; the app returns video ID(s) via Trading API GetItem. No "add video to SKU" or SKU input in the UI. Backend add-video endpoints may still exist for API use but are not part of the current UI.

## References

- GetItem / video: `docs/GET_VIDEO_ID_HANDOFF.md`
- eBay IDs (item ID vs offer ID vs SKU): `docs/LISTING_VIDEO_EBAY_IDS.md`
