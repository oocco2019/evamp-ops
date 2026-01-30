# Phase 1 Testing Guide

Step-by-step guide to test the EvampOps Phase 1 implementation.

## Prerequisites Check

Before starting, verify you have:

```bash
# Check Python (need 3.11+)
python3 --version

# Check Node.js (need 18+)
node --version

# Check Docker (optional but recommended)
docker --version
docker-compose --version
```

## Option A: Test with Docker (Recommended - Easiest)

### Step 1: Generate Encryption Key

```bash
cd /Users/marius/evamp-ops

# Install cryptography if needed (one-time)
pip3 install cryptography

# Generate key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Copy the output** (looks like: `dGhpc2lzYXRlc3RrZXkxMjM0NTY3ODkw...`)

### Step 2: Configure Environment

```bash
cd /Users/marius/evamp-ops
cp .env.example .env

# Edit .env file (use your preferred editor)
# Required:
# - DB_PASSWORD=YourSecurePassword123!
# - ENCRYPTION_KEY=<paste the key from Step 1>

# Optional (for later phases):
# - EBAY_APP_ID, EBAY_CERT_ID, EBAY_DEV_ID
```

### Step 3: Start Application

```bash
cd /Users/marius/evamp-ops
docker-compose up
```

**Wait for:** 
- "Application startup complete" (backend)
- "Local: http://localhost:5173" (frontend)
- Usually takes 30-60 seconds

### Step 4: Verify Services Are Running

**Open 3 browser tabs:**

1. **Backend Health Check**
   - URL: http://localhost:8000/health
   - Expected: `{"status":"healthy","database":"connected","debug_mode":true}`

2. **API Documentation**
   - URL: http://localhost:8000/docs
   - Expected: Swagger UI with API endpoints listed

3. **Frontend**
   - URL: http://localhost:5173
   - Expected: EvampOps welcome page with navigation

### Step 5: Test Settings - API Credentials

1. Go to http://localhost:5173/settings
2. Click **API Credentials** tab (should be active by default)
3. **Add a credential:**
   - Service: Select "Anthropic" (or "OpenAI")
   - Key Name: `api_key`
   - Value: Paste a test API key (or use placeholder: `test-key-123`)
   - Click **Add Credential**
4. **Verify:** Credential appears in list below with "Active" badge
5. **Test delete:** Click "Delete" on the credential (optional)

### Step 6: Test Settings - AI Models

1. Stay on Settings page, click **AI Models** tab
2. **Add an AI model:**
   - Provider: Select "Anthropic (Claude)"
   - Model: Select "claude-3-5-sonnet-20241022"
   - Check "Set as default model"
   - Click **Add Model**
3. **Verify:** Model appears in list with "Default" badge
4. **Test set default:** Add another model (e.g., OpenAI), then click "Set Default" on it
5. **Verify:** Default badge moves to the new model

### Step 7: Test Settings - Warehouses

1. Click **Warehouses** tab
2. **Add a warehouse:**
   - Shortname: `UK-Main`
   - Address: `123 Warehouse St, London, UK`
   - Country Code: `UK`
   - Click **Add Warehouse**
3. **Verify:** Warehouse appears in list
4. **Test delete:** Click "Delete" (optional)

### Step 8: Test API Directly (Optional)

**Using Swagger UI (http://localhost:8000/docs):**

1. **GET /api/settings/credentials**
   - Click "Try it out" → "Execute"
   - Expected: 200 response with list of credentials (no decrypted values)

2. **GET /api/settings/ai-models**
   - Click "Try it out" → "Execute"
   - Expected: 200 response with AI model configurations

3. **GET /api/settings/ai-models/default**
   - Click "Try it out" → "Execute"
   - Expected: 200 response with default AI model (or 404 if none set)

4. **GET /api/settings/warehouses**
   - Click "Try it out" → "Execute"
   - Expected: 200 response with warehouse list

### Step 9: Test Navigation

1. Click **Sales Analytics** in nav
   - Expected: Placeholder page "Coming in Phase 3"

2. Click **SKUs**
   - Expected: Placeholder page "Coming in Phase 2"

3. Click **Messages**
   - Expected: Placeholder page "Coming in Phase 4-6"

4. Click **Settings**
   - Expected: Back to Settings page with your data

5. Click **EvampOps** (logo)
   - Expected: Home page with 4 feature cards

### Step 10: Verify Data Persistence

1. Add a credential, AI model, and warehouse (if you haven't)
2. **Refresh the page** (F5 or Cmd+R)
3. **Verify:** All data still there (loaded from database)

---

## Option B: Test Without Docker (Manual Setup)

### Backend Testing

```bash
cd /Users/marius/evamp-ops/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up .env (from project root)
cd ..
cp .env.example .env
# Edit .env with DATABASE_URL, ENCRYPTION_KEY, DB_PASSWORD

# Start PostgreSQL (if not running)
# macOS: brew services start postgresql@15
# Create database: createdb evamp_ops

# Run migrations
cd backend
alembic upgrade head

# Start backend
uvicorn app.main:app --reload
```

**Test backend:** http://localhost:8000/health

### Frontend Testing (New Terminal)

```bash
cd /Users/marius/evamp-ops/frontend

# Install dependencies
npm install

# Start frontend
npm run dev
```

**Test frontend:** http://localhost:5173

**Note:** Update `.env` with `VITE_API_URL=http://localhost:8000` if backend is on different port.

---

## Automated Test Script (Backend)

Run backend unit tests (when implemented):

```bash
cd /Users/marius/evamp-ops/backend
source venv/bin/activate
pytest tests/ -v
```

Run with coverage:

```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html  # View coverage report
```

---

## Automated Test Script (Frontend)

Run frontend tests (when implemented):

```bash
cd /Users/marius/evamp-ops/frontend
npm test
```

Run with coverage:

```bash
npm run test:coverage
```

---

## Troubleshooting

### Docker: "database password required"
- **Fix:** Set `DB_PASSWORD` in `.env` file

### Docker: "Invalid ENCRYPTION_KEY"
- **Fix:** Generate new key with Python command, ensure no extra spaces in `.env`

### Backend: "ModuleNotFoundError: cryptography"
- **Fix:** `pip install cryptography` (or `pip install -r requirements.txt`)

### Backend: "could not connect to server"
- **Fix:** Ensure PostgreSQL is running: `docker-compose ps` (should show postgres as "Up")
- **Fix (manual):** Start PostgreSQL: `brew services start postgresql@15`

### Frontend: "Network Error" when calling API
- **Fix:** Ensure backend is running on http://localhost:8000
- **Fix:** Check CORS in backend (should allow http://localhost:5173)
- **Fix:** If using Docker, ensure both containers are running: `docker-compose ps`

### Port already in use
- **Fix:** Stop other services using ports 5432, 8000, or 5173
- **Fix:** Or change ports in `docker-compose.yml`

### Settings page: "Failed to fetch"
- **Fix:** Backend not running or wrong URL
- **Fix:** Check browser console (F12) for exact error
- **Fix:** Verify backend: http://localhost:8000/health

---

## Success Criteria

Phase 1 passes if:

- [x] Backend starts without errors
- [x] Frontend loads in browser
- [x] Can add/view/delete API credentials
- [x] Can add/view/delete AI models
- [x] Can set default AI model
- [x] Can add/view/delete warehouses
- [x] Data persists after page refresh
- [x] API docs accessible at /docs
- [x] Health check returns 200
- [x] Navigation works between all pages

---

## Next Steps After Testing

If all tests pass:
1. **Commit your work:** `git add . && git commit -m "Phase 1 complete - foundation and settings"`
2. **Push to GitHub:** Set up remote and push (see README)
3. **Proceed to Phase 2:** eBay integration and SKU management

If tests fail:
1. Check troubleshooting section above
2. Review logs: `docker-compose logs -f`
3. Verify `.env` configuration
4. Check GETTING_STARTED.md for detailed setup

---

## Quick Test Checklist

Print this and check off as you test:

```
[ ] Prerequisites installed (Python, Node, Docker)
[ ] Encryption key generated
[ ] .env file configured
[ ] docker-compose up (or manual start)
[ ] Backend health check: 200 OK
[ ] Frontend loads: http://localhost:5173
[ ] Settings page loads
[ ] Add API credential - success
[ ] Add AI model - success
[ ] Set default AI model - success
[ ] Add warehouse - success
[ ] Refresh page - data persists
[ ] API docs load: http://localhost:8000/docs
[ ] Navigation works (all 4 nav links)
```

**Estimated testing time:** 15-20 minutes (first time), 5-10 minutes (subsequent)

Good luck! You've got a solid foundation.
