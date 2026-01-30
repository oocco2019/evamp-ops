#!/bin/bash
# Phase 1 Quick Test Script
# Run from project root: ./scripts/test-phase1.sh

set -e

echo "=========================================="
echo "EvampOps Phase 1 - Quick Test Script"
echo "=========================================="
echo ""

# Check if we're in project root
if [ ! -f "docker-compose.yml" ]; then
    echo "Error: Run this script from project root (/Users/marius/evamp-ops)"
    exit 1
fi

echo "Step 1: Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 not found. Please install Python 3.11+"
    exit 1
fi
echo "  ✓ Python 3 found: $(python3 --version)"

if ! command -v docker &> /dev/null; then
    echo "  ✗ Docker not found. Please install Docker or use manual testing (see TEST_PHASE1.md)"
    exit 1
fi
echo "  ✓ Docker found: $(docker --version)"
echo ""

echo "Step 2: Checking .env file..."
if [ ! -f ".env" ]; then
    echo "  ✗ .env file not found!"
    echo "  Create it with: cp .env.example .env"
    echo "  Then edit .env and set: DB_PASSWORD, ENCRYPTION_KEY"
    exit 1
fi

if ! grep -q "ENCRYPTION_KEY=." .env || ! grep -q "DB_PASSWORD=." .env; then
    echo "  ✗ .env file incomplete. Set DB_PASSWORD and ENCRYPTION_KEY"
    echo "  Generate key: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    exit 1
fi
echo "  ✓ .env file configured"
echo ""

echo "Step 3: Starting Docker containers..."
docker-compose up -d

echo "  Waiting for services to be ready (30 seconds)..."
sleep 30
echo ""

echo "Step 4: Testing backend health..."
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "  ✓ Backend healthy (HTTP 200)"
    curl -s http://localhost:8000/health | python3 -m json.tool
else
    echo "  ✗ Backend not responding (HTTP $HEALTH_RESPONSE)"
    echo "  Check: docker-compose logs backend"
    exit 1
fi
echo ""

echo "Step 5: Testing frontend..."
FRONTEND_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || echo "000")

if [ "$FRONTEND_RESPONSE" = "200" ]; then
    echo "  ✓ Frontend responding (HTTP 200)"
else
    echo "  ✗ Frontend not responding (HTTP $FRONTEND_RESPONSE)"
    echo "  Check: docker-compose logs frontend"
    exit 1
fi
echo ""

echo "=========================================="
echo "✓ Phase 1 Quick Test PASSED"
echo "=========================================="
echo ""
echo "Manual testing steps:"
echo "1. Open http://localhost:5173 in your browser"
echo "2. Go to Settings page"
echo "3. Add an API credential (Settings → API Credentials)"
echo "4. Add an AI model (Settings → AI Models)"
echo "5. Add a warehouse (Settings → Warehouses)"
echo "6. Verify data persists after refresh"
echo ""
echo "API Documentation: http://localhost:8000/docs"
echo "Backend Health: http://localhost:8000/health"
echo ""
echo "To stop: docker-compose down"
echo ""
