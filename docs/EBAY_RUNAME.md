# Where to Find Your RuName (eBay OAuth)

eBay requires **RuName** in `EBAY_REDIRECT_URI`, not the full URL. Using the full URL causes `400 invalid_request`.

## Production vs Sandbox (important)

Our app uses **Production** (`auth.ebay.com`). You must use the **Production** RuName:

- In eBay Developer Portal, go to **"Your branded eBay Production Sign In (OAuth)"** (not Sandbox).
- Create or edit the redirect URL there and set **Your auth accepted URL¹** to your https callback (e.g. ngrok URL).
- The **RuName** shown for that Production config is what you put in `.env` as `EBAY_REDIRECT_URI`.

If you use the **Sandbox** RuName with Production, you get `400 invalid_request`.

## Where eBay Shows the RuName

1. Go to **eBay Developer Program** → **Your Account** → **Application Keys**.
2. Find your app and click **User Tokens** (next to your Client ID).
3. Open **"Get a Token from eBay via Your Application"** (dropdown or section).
4. You should see either:
   - A **list of Redirect URLs** – each row has a short **RuName** value (e.g. `YourApp-YourApp-PRD-xxxxxxxx`) and the URLs you configured.
   - Or a **single RuName** shown after you created/saved your Auth Accepted URL.

The RuName is a **short string** (often like `Something-Something-PRD-xxxxx` or similar). It is **not** the long `https://...` URL.

## What to Put in .env

```bash
EBAY_REDIRECT_URI=YourActualRuNameFromEbay
```

Example (use your real value):

```bash
EBAY_REDIRECT_URI=ooccolim-evampapp-PRD-xxxxxxxx
```

No `https://`, no path – just the RuName string.

## If You Still Don't See RuName

- Try **saving** the OAuth form again (Auth Accepted URL, etc.) and then reopening **User Tokens** / **Get a Token**.
- Look for a **"Redirect URL name"** or **"RuName"** label, or a short code next to your configured URL.
- In some layouts it appears in a **table** of redirect URLs: one column is the RuName, another is the URL.

---

## Still getting 400 invalid_request?

1. **Production vs Sandbox**  
   This app uses **Production** (`auth.ebay.com`). You must use the **Production** RuName. eBay gives two RuNames per app (Sandbox and Production). If you copied the RuName from the Sandbox section, get the one from **Your branded eBay Production Sign In (OAuth)** and put that in `EBAY_REDIRECT_URI`.

2. **Exact string**  
   The value must match the RuName in the Developer Portal **exactly** (character for character). Copy-paste the RuName from eBay; do not type it. Check for extra spaces, wrong hyphen/underscore, or wrong suffix (e.g. `-PRD-xxx` for Production).

3. **No quotes in .env**  
   Use:
   ```bash
   EBAY_REDIRECT_URI=YourRuName-Here
   ```
   not `EBAY_REDIRECT_URI="YourRuName-Here"` (quotes can be sent to eBay and cause a mismatch). The app strips surrounding quotes; if you still see errors, remove quotes from `.env`.

4. **Verify what we send**  
   Set `DEBUG=true` in `.env`, restart the backend, then open:
   ```
   GET /api/stock/ebay/debug
   ```
   (e.g. `http://localhost:8000/api/stock/ebay/debug`). Check that `EBAY_REDIRECT_URI_value` and `EBAY_AUTH_URL` match your Production RuName and Production auth URL. If you see `auth.sandbox.ebay.com` anywhere, you are in Sandbox; we use Production only.

5. **Auth Accepted URL in eBay**  
   For that RuName, the **Auth Accepted URL** in the Developer Portal must be the URL that reaches your backend callback, e.g. `https://your-domain.com/api/stock/ebay/callback` or your ngrok URL. Mismatch here can cause redirect or token-exchange errors.
