# Getting Started with EvampOps

Welcome! This guide will help you set up and run the EvampOps application locally.

## Phase 1 Complete

The foundation is ready:
- Backend API with FastAPI
- Database models (PostgreSQL)
- Frontend with React + TypeScript
- Settings page for API credentials and AI model configuration
- Security: encrypted credential storage
- Docker Compose for easy startup

## Prerequisites

Before starting, ensure you have:

1. **Docker & Docker Compose** (recommended)
   - Download from: https://www.docker.com/products/docker-desktop

OR (if running manually):

2. **Python 3.11+**
   - Check: `python --version`
3. **Node.js 18+**
   - Check: `node --version`
4. **PostgreSQL 15+**
   - Install via Homebrew: `brew install postgresql@15`

## Quick Start (Docker - Recommended)

### Step 1: Generate Encryption Key

```bash
cd /Users/marius/evamp-ops
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output - you'll need it in the next step.

### Step 2: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` file and set:
- `DB_PASSWORD`: Choose a strong password (e.g., `MySecurePassword123!`)
- `ENCRYPTION_KEY`: Paste the key from Step 1
- Optional: Add eBay API credentials if you have them

### Step 3: Start the Application

```bash
docker-compose up
```

This will:
- Start PostgreSQL database
- Start FastAPI backend on http://localhost:8000
- Start React frontend on http://localhost:5173

### Step 4: Access the Application

Open your browser to:
- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs (interactive Swagger UI)
- **Health Check**: http://localhost:8000/health

### Step 5: Configure Settings

1. Go to http://localhost:5173/settings
2. Add your API credentials:
   - **eBay**: app_id, cert_id, dev_id (get from https://developer.ebay.com/my/keys)
   - **Anthropic**: api_key (get from https://console.anthropic.com)
   - **OpenAI**: api_key (get from https://platform.openai.com)
3. Configure an AI model:
   - Select a provider (Anthropic or OpenAI)
   - Choose a model
   - Set as default

You're all set! The application is now ready to use.

---

## Manual Setup (Without Docker)

### Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copy this key

# Configure environment
cd ..
cp .env.example .env
# Edit .env with your encryption key and database settings

# Start PostgreSQL (if not running)
brew services start postgresql@15

# Create database
createdb evamp_ops

# Run migrations
cd backend
alembic upgrade head

# Start backend server
uvicorn app.main:app --reload
```

Backend will be available at http://localhost:8000

### Frontend Setup

Open a new terminal:

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at http://localhost:5173

---

## Troubleshooting

### Docker Issues

**Error: "database password required"**
- Make sure `DB_PASSWORD` is set in your `.env` file

**Error: "Invalid ENCRYPTION_KEY"**
- Generate a new key using the Python command above
- Ensure there are no extra spaces in the `.env` file

**Port already in use:**
```bash
# Stop containers
docker-compose down

# Check what's using the port
lsof -i :5432  # For PostgreSQL
lsof -i :8000  # For backend
lsof -i :5173  # For frontend

# Kill the process or change port in docker-compose.yml
```

### Permission Issues

If you get permission errors with git:
```bash
cd /Users/marius/evamp-ops
rm -rf .git
git init
git add .
git commit -m "Initial commit"
```

### Database Connection Issues

**Error: "could not connect to server"**
```bash
# Check if PostgreSQL is running
docker-compose ps

# Restart PostgreSQL container
docker-compose restart postgres

# View logs
docker-compose logs postgres
```

---

## Next Steps

### Phase 2: Stock Manager Core (Complete)
- eBay order data import (SM02), SKU CRUD (SM03), eBay API client

### Phase 3: Analytics & Planning (Complete)
- Sales analytics dashboard with charts (SM01)
- Stock planning calculator (SM04)
- Supplier order management (SM06-SM07)

### Phase 4-6: Customer Service
- Message import and sync (CS01-CS03)
- AI drafting and translation (CS04-CS08)
- Message management (CS09-CS12)

---

## Useful Commands

### Docker

```bash
# Start services
docker-compose up

# Start in background
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f

# Rebuild containers (after code changes)
docker-compose up --build

# Access backend shell
docker exec -it evamp-ops-backend bash

# Access PostgreSQL
docker exec -it evamp-ops-db psql -U evamp -d evamp_ops
```

### Backend

```bash
cd backend

# Run tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=html

# Security scan
safety check
pip-audit

# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

### Frontend

```bash
cd frontend

# Run tests
npm test

# Run tests with coverage
npm run test:coverage

# Build for production
npm run build

# Preview production build
npm run preview
```

---

## Support

For issues or questions:
1. Check the logs: `docker-compose logs -f`
2. Verify environment variables in `.env`
3. Ensure all services are running: `docker-compose ps`
4. Check API health: http://localhost:8000/health

Happy building!
