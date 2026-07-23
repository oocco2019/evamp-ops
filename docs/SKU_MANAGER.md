# SKU Manager

Product catalog UI (`/sku-manager`, `frontend/src/pages/SKUManager.tsx`) for create / edit / delete SKUs.

## Fields

- **SKU code**, **title**
- **Landed cost** (USD) – COGS input for Sales Analytics / Order details / Stock Order
- **Postage price** (USD) – outbound postage baseline (eBay-oriented); Shopify adds a GBP surcharge in analytics — see [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md)
- **Profit per unit** (optional) – used as a **fallback** in Stock Order when a SKU has no sales in the profit lookback window (×0.8). **Not** used as “qty × profit_per_unit” for Sales Analytics totals — see [SALES_ANALYTICS.md](SALES_ANALYTICS.md) and [STOCK_PLANNING.md](STOCK_PLANNING.md)

## Notes

- Saving SKU costs invalidates analytics queries so Sales Analytics can refetch with updated COGS.
- UI copy on the page is minimal; behaviour and cost usage are documented in the linked files above.
