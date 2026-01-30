#!/bin/bash
# Start app (backend + frontend) and tunnel in one go. Opens the app in your browser.
# Run from project root: bash scripts/start-app-and-tunnel.sh  or  make run
set -e
cd "$(dirname "$0")/.."

echo "Starting backend + frontend..."
docker compose up -d

echo "Waiting for app to be ready..."
sleep 5

# Open browser (macOS; on Linux use xdg-open)
if command -v open >/dev/null 2>&1; then
  open "http://localhost:5173"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:5173"
fi

echo ""
echo "App: http://localhost:5173"
echo "Tunnel starting (keep this terminal open for eBay OAuth)..."
echo "Press Ctrl+C to stop the tunnel only; run 'make down' to stop the app."
echo ""

exec bash scripts/start-tunnel.sh
