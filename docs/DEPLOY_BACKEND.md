# Deploy the Backend (Stable eBay Callback URL)

Deploying the backend gives you a **fixed public URL**. You set that URL once in eBay as the Auth Accepted URL. You can run the frontend on any machine (this one, another PC, or later on the same host) and point it at the deployed backend.

---

## What You Get

- **Stable entry point:** e.g. `https://evamp-ops-api.railway.app`
- **eBay callback URL:** `https://evamp-ops-api.railway.app/api/stock/ebay/callback` — set once in eBay Developer Portal
- **No tunnel to run:** Backend has a fixed URL; no localhost.run or Cloudflare Tunnel needed
- **Run frontend anywhere:** Set `VITE_API_URL` (or your env) to the deployed backend URL on any machine

---

## Option A: Railway (recommended, simple)

1. **Account:** Go to [railway.app](https://railway.app), sign up (GitHub login is easiest).

2. **New project:** Dashboard → **New Project** → **Deploy from GitHub repo**. Connect GitHub and select your `evamp-ops` repo.

3. **Root directory:** Railway will detect the repo. You need to deploy **only the backend**. Either:
   - Add a **Monorepo** setup: set **Root Directory** to `backend` for the service, or
   - In **Settings** for the service, set **Root Directory** to `backend` so Railway builds from the `backend/` folder (and uses `backend/Dockerfile` if you configure Docker deploy).

   If Railway does not support root directory per service, create a **new service** in the same project, connect the same repo, set **Root Directory** to `backend`, and use the **Dockerfile** build (path `backend/Dockerfile`).

4. **PostgreSQL:** In the same project, click **New** → **Database** → **PostgreSQL**. Railway creates a DB and exposes `DATABASE_URL`. Copy it (or use the Variables tab; it’s often auto-linked to the service).

5. **Variables:** In your **backend service** → **Variables**, set:

   | Variable | Value |
   |----------|--------|
   | `DATABASE_URL` | From step 4 (Railway Postgres; often `postgres://...` or `postgresql://...`) |
   | `ENCRYPTION_KEY` | Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
   | `EBAY_APP_ID` | Your eBay Production App ID |
   | `EBAY_CERT_ID` | Your eBay Production OAuth Client Secret (Cert ID) |
   | `EBAY_REDIRECT_URI` | Your **Production RuName** (short string from eBay, not the full URL) |
   | `CORS_ORIGINS` | Where the frontend runs, e.g. `http://localhost:5173` or `https://your-frontend.railway.app` (comma-separated if multiple) |
   | `FRONTEND_URL` | Same as the origin you use for CORS, e.g. `http://localhost:5173` (used for OAuth redirect after eBay login) |
   | `DEBUG` | `false` |

   Do **not** set `EBAY_REDIRECT_URI` to the full callback URL; that must be the **RuName** from eBay. The **full** callback URL is what you set in eBay (see step 7).

6. **Build & deploy:**  
   - If using **Dockerfile:** Set build to use `backend/Dockerfile` and context `backend/` (or root with Dockerfile path `backend/Dockerfile`).  
   - If using **Nixpacks/Railway build:** Ensure root directory is `backend`, and that `requirements.txt` and `alembic` are used. The Dockerfile is preferred so `start.sh` runs (migrations + uvicorn).

   After deploy, Railway gives a public URL like `https://evamp-ops-api-production-xxxx.up.railway.app`.

7. **eBay Developer Portal:**  
   - Open your app → **User Tokens** → **Production** → the RuName you use for `EBAY_REDIRECT_URI`.  
   - Set **Auth Accepted URL** to:  
     `https://<your-railway-backend-url>/api/stock/ebay/callback`  
     (e.g. `https://evamp-ops-api-production-xxxx.up.railway.app/api/stock/ebay/callback`).  
   - Save. You won’t need to change this when you move machines or restart anything.

8. **Run frontend on your machine (or another):**  
   - Clone the repo (or copy the frontend).  
   - In the frontend env (e.g. `.env` or `.env.local`), set:  
     `VITE_API_URL=https://<your-railway-backend-url>`  
     (no trailing slash).  
   - Run the frontend: `cd frontend && npm install && npm run dev`.  
   - Open the app in the browser; it will call the deployed backend. CORS is already allowed for the origin you set in `CORS_ORIGINS` (e.g. `http://localhost:5173`).

---

## Option B: Render

1. **Account:** [render.com](https://render.com), sign up (GitHub OK).

2. **New Web Service:** Connect the repo, then create a **Web Service**. Set **Root Directory** to `backend`.

3. **Build:**  
   - **Build Command:** `pip install -r requirements.txt` (or use Docker if Render supports it and you use the Dockerfile).  
   - **Start Command:** `./start.sh` (or `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`).  
   Render sets `PORT`; the Dockerfile’s `start.sh` uses 8000 — on Render use `$PORT` in the start command if not using Docker.

4. **PostgreSQL:** In the same Render account, create a **PostgreSQL** database; copy the **Internal Database URL** (or External if your service is public).

5. **Environment:** In the Web Service → **Environment**, add the same variables as in the Railway table above (including `DATABASE_URL` from step 4). Set `CORS_ORIGINS` and `FRONTEND_URL` to where you run the frontend (e.g. `http://localhost:5173`).

6. **eBay:** Set **Auth Accepted URL** to `https://<your-render-service-url>/api/stock/ebay/callback`. Use your **RuName** in `EBAY_REDIRECT_URI` in Render env.

7. **Frontend:** Point `VITE_API_URL` at the Render backend URL and run the frontend locally (or on another machine) as in step 8 above.

---

## Moving the App to Another Machine

- **Backend:** Already deployed; no change. The URL stays the same.
- **Frontend:** On the new machine, clone the repo, set `VITE_API_URL` to the same backend URL, run `npm install && npm run dev`. If the new machine uses a different origin (e.g. different port or host), add that origin to `CORS_ORIGINS` and `FRONTEND_URL` in the **deployed** backend’s environment and redeploy once.
- **eBay:** No change; callback URL is still the deployed backend.

---

## Summary

| Step | What to do |
|------|------------|
| Deploy backend | Railway or Render, with PostgreSQL and env vars |
| Callback URL | Set in eBay once: `https://<deployed-backend-url>/api/stock/ebay/callback` |
| RuName | Keep using the same RuName in `EBAY_REDIRECT_URI` (not the full URL) |
| Frontend | Any machine: set `VITE_API_URL` to deployed backend; set `CORS_ORIGINS`/`FRONTEND_URL` to that frontend’s origin |

This gives you a single, stable entry point for the API and for eBay OAuth, with no tunnels to manage.
