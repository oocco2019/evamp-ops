# localhost.run: Stable Tunnel for eBay OAuth

**localhost.run** gives you a **stable HTTPS URL** for the eBay callback. The URL is tied to your account and SSH key, so each time you run the tunnel you get the **same subdomain** and set it in eBay once.

---

## Why localhost.run

- **Stable URL:** Same subdomain every restart (after you add your SSH key to your account) → set in eBay **once**
- **Free:** Sign up at admin.localhost.run and add your key; no payment

---

## Setup (One Time)

### 0. Get a stable URL: sign up and add your SSH key

Without this step you get a **random** URL each time ("authenticated as anonymous user").

1. Sign up at **[admin.localhost.run](https://admin.localhost.run/)**
2. Add your SSH **public** key: copy the contents of `~/.ssh/id_ed25519.pub` (or `~/.ssh/id_rsa.pub`) and paste it in your account. To display it: `cat ~/.ssh/id_ed25519.pub`

After that, when you start the tunnel (step 1 below) you will be identified by your key and get the **same** URL every time.

### 1. Start the tunnel

In a new terminal (keep it running):

```bash
cd /Users/marius/evamp-ops
make tunnel
```
Or: `bash scripts/start-tunnel.sh`
(Or `./scripts/start-tunnel.sh` if the script is executable.)

It prints something like:

```
** your connection id is abc123-def456-..., please mention it if you send me a message about an issue. **

abc123.localhost.run tunneled with tls termination, https://abc123.localhost.run
```

**Copy** the URL shown (e.g. `https://abc123.localhost.run`). That's your stable tunnel URL.

### 2. Set CALLBACK_BASE_URL

In `.env` at project root:

```bash
CALLBACK_BASE_URL=https://abc123.localhost.run
```

(Use the exact URL from step 1, no trailing slash.)

### 3. Restart the backend

So it picks up the new env var:

```bash
make down && make up
```

### 4. Copy callback URL from Settings

- Open the app: `http://localhost:5173`
- Go to **Settings → eBay tab**
- You'll see a box **"Callback URL for eBay"** with the full URL: `https://abc123.localhost.run/api/stock/ebay/callback`
- Click **Copy**

### 5. Paste in eBay Developer Portal

- Log in to eBay Developer Program → Your Account → Application Keys
- Find your app → **User Tokens** → the **Production** RuName you use for `EBAY_REDIRECT_URI`
- Set **Your auth accepted URL** to the URL you copied (e.g. `https://abc123.localhost.run/api/stock/ebay/callback`)
- Click **Save**

Done. From now on, each time you start the tunnel with `./scripts/start-tunnel.sh` you get the **same** URL (because it uses your SSH key). So you never update eBay again.

---

## Daily Workflow

**Each time you develop:**

1. Start the backend: `make up` (or `make start`)
2. Start the tunnel: `make tunnel` or `bash scripts/start-tunnel.sh` (in a second terminal; keep it running)
3. Open the app: `http://localhost:5173`

The tunnel URL is the same every time, so eBay OAuth works immediately.

---

## Troubleshooting

- **"connection refused" or "tunnel not reachable"** → Backend not running. Start backend first: `make up`.
- **"SSH connection failed"** → Check internet. localhost.run uses SSH; no firewall should block port 22 outbound.
- **Different URL each time** → You are "authenticated as anonymous user". Sign up at [admin.localhost.run](https://admin.localhost.run/) and add your SSH public key (`cat ~/.ssh/id_ed25519.pub`). Then the subdomain stays the same every time.

---

