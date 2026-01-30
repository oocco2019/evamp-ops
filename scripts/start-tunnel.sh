#!/bin/bash
# Start localhost.run tunnel for eBay OAuth callback.
# The subdomain is tied to your SSH key and stays the same across restarts.
#
# Usage: bash scripts/start-tunnel.sh  (or ./scripts/start-tunnel.sh if executable)
# Then copy the URL shown (e.g. https://abc123.localhost.run) and:
# 1. Set CALLBACK_BASE_URL=https://abc123.localhost.run in .env
# 2. Paste https://abc123.localhost.run/api/stock/ebay/callback in eBay Developer Portal → Auth Accepted URL

echo "Starting localhost.run tunnel to backend (port 8000)..."
echo ""
echo "The subdomain is tied to your SSH key and will be the same every time."
echo "Copy the URL shown below and:"
echo "  1. Set CALLBACK_BASE_URL in .env to that URL"
echo "  2. Restart backend: make down && make up"
echo "  3. Paste the callback URL shown in Settings → eBay into eBay Developer Portal"
echo ""
echo "Press Ctrl+C to stop the tunnel."
echo ""

ssh -R 80:localhost:8000 localhost.run
