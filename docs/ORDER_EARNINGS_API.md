# Order earnings (eBay UI and APIs)

eBay’s order page shows **Order earnings** with the tooltip:

> Your order earnings after applying fees and other selling costs.

That value (e.g. £109.82) is what we store as `total_due_seller` and use for profit calculations.

## Where we get it

We use two eBay APIs; both expose the same “order earnings” concept.

### 1. Sell Fulfillment API – `getOrder`

- **Endpoint:** `GET /sell/fulfillment/v1/order/{orderId}`
- **Field:** `paymentSummary.totalDueSeller`
- **Shape:** `{ "value": "109.82", "currency": "GBP" }` or, for non‑GBP orders, `value`/`currency` in order currency plus `convertedFromValue`/`convertedFromCurrency` (e.g. GBP).
- **Our code:** `_parse_total_due_seller()` in `backend/app/services/ebay_client.py` — prefers GBP when present so we match the eBay order details figure.
- **Used for:** Initial order import (batch `getOrders` includes `paymentSummary` when we request it), single-order refresh fallback when Finances is unavailable, and debug endpoint `GET /api/stock/orders/{ebay_order_id}/ebay-raw`.

### 2. Sell Finances API – `getTransactions`

- **Endpoint:** `GET /sell/finances/v1/transaction?filter=orderId:{orderId}`
- **Logic:** From the transactions list we take the **SALE** transaction, use its `amount` (gross), subtract `totalFeeAmount` and any **NON_SALE_CHARGE** (e.g. ad fees) for that order. The result is the net “order earnings” and matches the eBay UI.
- **Our code:** `parse_net_order_earnings_from_transactions()` in `backend/app/services/ebay_client.py`.
- **Used for:** Backfill (`POST /api/stock/orders/backfill-order-earnings`) and single-order refresh when we want the most accurate net (after ad fees). Falls back to Fulfillment `totalDueSeller` when Finances returns 204/403 (e.g. EU/UK without Digital Signatures).

## Summary

| Source              | API / field                               | When we use it                          |
|---------------------|-------------------------------------------|-----------------------------------------|
| Fulfillment         | `getOrder` → `paymentSummary.totalDueSeller` | Import, refresh fallback, debug         |
| Finances            | `getTransactions` → SALE − fees − NON_SALE_CHARGE | Backfill, refresh (preferred when available) |

So the “Order earnings” value you see on the eBay order page is the same as:

- **Fulfillment:** `paymentSummary.totalDueSeller` (parsed with GBP preferred).
- **Finances:** Net from SALE transaction after fees and ad charges.

---

## Note (user observation)

User observed that on the eBay webpage, **Order earnings** (the figure in the order details) is *less* than the API's **Total Due Seller (Order Earnings)**. In other words:

- **API `totalDueSeller`** ≈ Order earnings (eBay webpage) **+ Ad fee** (or other selling costs shown separately on the page).

We are not changing the implementation for now; the above mapping and our use of Fulfillment vs Finances remain as documented. This note is here so the distinction is not lost if we revisit order-earnings vs ad-fees handling later.
