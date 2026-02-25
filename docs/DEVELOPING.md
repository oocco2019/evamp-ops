# Developing EvampOps

## How you run the app

**Use Docker.** That is the supported path. Everything (DB, backend, frontend) runs in containers with the right dependencies and env.

1. **Docker Desktop** must be running.
2. From project root, with a valid `.env` (see below):

   ```bash
   make up
   ```

   - Frontend: http://localhost:5173  
   - Backend: http://localhost:8000  
   - API docs: http://localhost:8000/docs  

3. To stop: `make down`.

**Optional:** `make run` starts the stack and a localhost.run tunnel (for eBay OAuth callback). It still requires Docker and the same `.env`.

## Required env for Docker

In project root, copy and edit `.env`:

```bash
cp .env.example .env
```

**Required:**

- `DB_PASSWORD` – used by Postgres and `DATABASE_URL` for the backend.
- `ENCRYPTION_KEY` – generate once:  
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

Docker Compose passes `DATABASE_URL` and `ENCRYPTION_KEY` into the backend container; they are not read from a file inside the container. If you see “Field required” for those, it means the backend is **not** running under Docker with this `.env` (e.g. you started uvicorn on the host).

## AI drafting (messaging)

1. **Settings > API Credentials** – add the API key for your provider (Anthropic or OpenAI). The app expects key name `api_key`; the UI sets this when you pick a provider.
2. **Settings > AI Models** – add a model and set it as default.
3. **Customer Service** – open a thread and use “Draft reply”.

The backend image must have `anthropic>=0.25.0` (and the rest of `backend/requirements.txt`). If you had an older image, rebuild so the container gets the right SDK:

```bash
make build
make up
```

## Why not run the backend with `./venv/bin/uvicorn` on the host?

You can, but then the process is **outside** Docker:

- It does not get `DATABASE_URL` or `ENCRYPTION_KEY` from docker-compose. You must have a `.env` in the directory from which you run (e.g. `backend/`) that defines them, or set them in the shell.
- The DB must be reachable (e.g. Postgres still running in Docker on 5432, or a local Postgres).

So for a single, consistent setup we use **Docker for the whole stack** and only run uvicorn locally when you explicitly want to debug outside containers.

## Hot reload

Code changes are picked up automatically via Docker bind mounts:

- **Backend:** uvicorn runs with `--reload`; Python file changes trigger restart.
- **Frontend:** Vite dev server hot-reloads on file save.

No need to run `make down && make up` for code changes. Just save the file.

## Rebuilding after changes

Only rebuild when dependencies or Dockerfiles change:

- **Backend (Python deps or Dockerfile):**  
  `make build` then `make up`  
  (or `docker compose build backend && docker compose up -d`)

- **Frontend (npm deps or Dockerfile):**  
  `make build` then `make up`

## Avoiding regressions

Some features have **behavior docs** and **tests** that lock in how they work. Before changing those areas, read the doc and run the relevant tests so you don’t break behavior that was previously fixed.

| Area | Doc | Tests |
|------|-----|--------|
| Message attachments (thread API, media URLs, blobs) | [MESSAGE_ATTACHMENTS.md](MESSAGE_ATTACHMENTS.md) | — |
| Voice instructions (AI instructions textarea while recording) | [VOICE_INSTRUCTIONS.md](VOICE_INSTRUCTIONS.md) | `frontend/src/utils/voiceInstructionsDisplay.test.ts` |

**Rule:** When editing code covered by a behavior doc, read the doc first. Do not re-introduce pitfalls that the doc warns against. After your change, run `npm run test` (in `frontend/`) so the voice display test still passes; add tests for other areas when you touch them.

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| “Cannot connect to the Docker daemon” | Start Docker Desktop and wait until it’s fully up, then run `make up` again. |
| “Address already in use” (e.g. 8000) | Another process is using the port (often an old uvicorn). Stop it or use a different port. |
| “Field required” for DATABASE_URL / ENCRYPTION_KEY | Backend is not running in Docker with the project’s `.env`. Use `make up` or fix local `.env` and ensure the running process loads it. |
| “AsyncAnthropic object has no attribute 'messages'” | Backend image was built with an old `anthropic` version. Run `make build` then `make up` so the backend image includes `anthropic>=0.25.0`. |
| Dockerfile build fails on `chmod +x /app/start.sh` | Use the current Dockerfile (chmod is done as root before switching to `appuser`). Pull latest and rebuild. |
