# EvampOps - one-command start/stop
# Run from project root: make up, make down, make logs

.PHONY: up down logs build restart

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

restart: down up

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
