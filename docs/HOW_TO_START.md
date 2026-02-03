# How to Start the App (Terminal Commands)

Run from the **project root** (`evamp-ops`).

---

## One command (app + tunnel + open browser)

```bash
cd /Users/marius/evamp-ops
make run
```

Starts backend + frontend, opens http://localhost:5173 in your browser, then starts the tunnel (for eBay). Keep the terminal open; press **Ctrl+C** to stop the tunnel only. To stop the app: `make down` in another terminal.

---

## Start app only (backend + frontend)

**Terminal 1:**

```bash
cd /Users/marius/evamp-ops
make up
```

Then open: **http://localhost:5173**

- Frontend: http://localhost:5173  
- Backend API: http://localhost:8000  
- API docs: http://localhost:8000/docs  

---

## If you need eBay (Connect with eBay, order import)

**Terminal 1** (backend + frontend):

```bash
cd /Users/marius/evamp-ops
make up
```

**Terminal 2** (tunnel — keep running):

```bash
cd /Users/marius/evamp-ops
make tunnel
```

Leave both running. Open **http://localhost:5173** and use Settings → eBay. The tunnel URL is stable (localhost.run), so you only set it in eBay once.

---

## Stop the app

```bash
cd /Users/marius/evamp-ops
make down
```

Stop the tunnel in Terminal 2 with **Ctrl+C**.

---

## Hot Reload (no restart needed)

Both frontend and backend have **hot reload** enabled. When you edit code:

- **Frontend** (React): Changes appear instantly in the browser
- **Backend** (FastAPI): Server auto-restarts on file save

You do **NOT** need to run `make down && make up` after code changes. Just save the file and refresh the browser if needed.

**When you DO need to restart:**
- After changing `docker-compose.yml`
- After changing `Dockerfile`
- After changing `.env` file
- After adding new Python dependencies to `requirements.txt`

---

## Quick reference

| Task              | Command                    |
|-------------------|----------------------------|
| App + tunnel + browser | `cd evamp-ops && make run` |
| Start app         | `cd evamp-ops && make up`  |
| Start tunnel      | `cd evamp-ops && make tunnel` |
| Stop app          | `cd evamp-ops && make down`|
| View logs         | `cd evamp-ops && make logs`|
