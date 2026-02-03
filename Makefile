# EvampOps - one-command start/stop
# Run from project root: make up, make down, make logs

.PHONY: up down logs build restart test-backend test-frontend test migrate

# Backend unit tests. Uses one-off container; installs pytest if missing. Run from repo root.
test-backend:
	docker compose run --rm backend sh -c "pip install -q pytest pytest-asyncio 2>/dev/null; python -m pytest tests/ -v"
# Local backend tests (no Docker): cd backend && pip install -r requirements-dev.txt && PYTHONPATH=. pytest tests/ -v
test-backend-local:
	cd backend && PYTHONPATH=. python -m pytest tests/ -v 2>&1 || (echo "Install dev deps: pip install -r requirements-dev.txt" && exit 1)

test-frontend:
	cd frontend && npm run build

test: test-backend

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

restart: down up

# Run DB migrations (Docker). From project root: make migrate
migrate:
	docker compose run --rm backend python -m alembic upgrade head

# Start and tail logs (useful for first run)
start: up
	@echo "---"
	@echo "Frontend: http://localhost:5173"
	@echo "Backend:  http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	@echo "---"
	docker compose logs -f

# Start localhost.run tunnel for eBay OAuth (stable URL, no signup). Keep running in a separate terminal.
tunnel:
	bash scripts/start-tunnel.sh

# Start app + tunnel in one command; opens browser. Tunnel runs in foreground (Ctrl+C stops tunnel only).
run:
	bash scripts/start-app-and-tunnel.sh
