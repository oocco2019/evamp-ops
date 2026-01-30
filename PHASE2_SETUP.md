# Phase 2 Setup: eBay + SKU Manager

## What Was Added

- **eBay OAuth**: Connect with eBay in Settings → eBay tab; refresh token stored encrypted.
- **Order import**: Full (last 2 years by month) or incremental (since last import).
- **SKU Manager**: Full CRUD, search, inline edit (SM03).

## eBay OAuth: RuName (Redirect URI)

eBay requires a **RuName** (Redirect URL) that points to your app’s callback. You must create it in the eBay Developer Portal and set it in `.env`.

### 1. Create RuName in eBay Developer Portal

1. Go to [eBay Developer Portal](https://developer.ebay.com/) → Your app → **User Tokens** (or **OAuth** / **Keys**).
2. Find **Redirect URL** / **RuName** and add a new one:
   - **Accept URL**: `http://localhost:5173/settings` (or your frontend URL).
   - **Sign-in URL**: `http://localhost:8000/api/stock/ebay/callback` (your backend callback).

   eBay may show a single “Redirect URL” field: use the **backend** callback URL, e.g.:

   - Local: `http://localhost:8000/api/stock/ebay/callback`
   - Production: `https://your-domain.com/api/stock/ebay/callback`

3. Copy the **RuName** value eBay gives you (it might look like `YourApp-YourApp-PRD-xxxxx` or a full URL).

### 2. Set in .env

```bash
EBAY_REDIRECT_URI=<paste the RuName or exact redirect URL here>
```

Example for local:

```bash
EBAY_REDIRECT_URI=http://localhost:8000/api/stock/ebay/callback
```

(Use the exact value eBay shows for your app’s redirect URL.)

### 3. Optional: Frontend URL for redirects

If your frontend is not on `http://localhost:5173`, set:

```bash
FRONTEND_URL=http://localhost:3000
```

(So after OAuth you’re sent back to the right place.)

## How to Use

1. **Connect eBay**: Settings → eBay → “Connect with eBay”. Sign in and approve; you’re redirected back and the app stores the refresh token.
2. **Import orders**: Settings → eBay → “Full import” or “Incremental import”. Results show orders/line items added or updated.
3. **SKUs**: SKU Manager → Add SKU, search, Edit, Delete. Optional: run an import first so orders with SKUs exist; you can still add SKUs manually.

## API Endpoints (Phase 2)

- `GET /api/stock/ebay/auth-url` – OAuth consent URL
- `GET /api/stock/ebay/callback` – OAuth callback (eBay redirects here)
- `GET /api/stock/ebay/status` – Connected or not
- `POST /api/stock/import` – Body: `{ "mode": "full" | "incremental" }`
- `GET /api/stock/skus` – List SKUs (optional `?search=`)
- `POST /api/stock/skus` – Create SKU
- `GET /api/stock/skus/{sku_code}` – Get one
- `PUT /api/stock/skus/{sku_code}` – Update
- `DELETE /api/stock/skus/{sku_code}` – Delete

## Troubleshooting

- **“eBay not connected”**: Run “Connect with eBay” and complete sign-in; check that RuName in the portal matches `EBAY_REDIRECT_URI` in `.env`.
- **Redirect mismatch**: `EBAY_REDIRECT_URI` must match the URL configured in the eBay Developer Portal (and must be the **backend** callback URL).
- **Import fails**: Ensure eBay app has **Sell Fulfillment (read)** scope; reconnect if you changed scopes.
