# Stable Callback URL for eBay OAuth

eBay's "Auth Accepted URL" must match the URL that receives the OAuth callback. You want a **stable** URL so you set it once in eBay. eBay’s “Auth Accepted URL” must match the URL that receives the OAuth callback.
**Recommended:** Use **[localhost.run](LOCALHOST_RUN_SETUP.md)** (free; sign up at admin.localhost.run and add your SSH key for a stable URL). Run `make tunnel`, set the URL once in eBay, and never update again.

Other options:

---

## Option 1: Cloudflare Tunnel (free, stable subdomain)

- **Cloudflare Tunnel** (e.g. `cloudflared`) can give you a **fixed** `*.trycloudflare.com` URL for a tunnel, or a custom domain.
- Run a tunnel that forwards to `localhost:8000`; use the tunnel URL as your callback host.
- Some setups keep the same subdomain across restarts; with a custom domain you get a fully stable URL.
- Set that URL once in eBay as the Auth Accepted URL.

---

## Option 2: Deploy backend to a fixed host (best for “real” use)

- Deploy the **backend** to a host with a fixed URL (e.g. **Railway**, **Render**, **Fly.io**, or a VPS).
- The callback URL is then always e.g. `https://your-app.railway.app/api/stock/ebay/callback`.
- Set that URL once in eBay; no tunnel to run.
- Use the same `.env` (e.g. `FRONTEND_URL` for where users go after OAuth; can be your frontend or localhost if you only use the API).

This is the most robust: one stable URL, no tunnel restarts, and you can use the same eBay app for local frontend + deployed backend if needed.

---

## Summary

| Approach           | Cost   | Effort | Callback URL      |
|--------------------|--------|--------|--------------------|
| localhost.run      | Free   | Low    | Stable (recommended) |
| Cloudflare Tunnel  | Free   | Medium | Stable (or custom) |
| Deploy backend     | Varies | Medium | Stable, no tunnel  |

**Recommendation:** For development, use **localhost.run** (see [LOCALHOST_RUN_SETUP.md](LOCALHOST_RUN_SETUP.md)). For production or serious testing, **deploy the backend** and use its URL as the callback.
