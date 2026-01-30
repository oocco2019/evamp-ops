# How to Test Phase 1

You have **3 testing options** - choose based on your preference:

---

## Option 1: Quick Test (5 minutes) - **RECOMMENDED**

**Best for:** First-time verification

**Guide:** Open **QUICK_TEST.md**

**Summary:**
1. Generate encryption key: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Copy .env.example to .env, set DB_PASSWORD and ENCRYPTION_KEY
3. Run: `docker-compose up`
4. Open http://localhost:5173 → Settings
5. Add 1 credential, 1 AI model, 1 warehouse
6. Refresh page - data should persist ✓

**Time:** ~5 minutes

---

## Option 2: Comprehensive Test (15-20 minutes)

**Best for:** Thorough verification before Phase 2

**Guide:** Open **TEST_PHASE1.md**

**What it covers:**
- Prerequisites check
- Docker AND manual setup instructions
- Step-by-step testing of every feature
- API testing via Swagger UI
- Navigation testing
- Data persistence verification
- Troubleshooting guide
- Success criteria checklist

**Time:** 15-20 minutes (first time)

---

## Option 3: Automated Script (2 minutes)

**Best for:** Quick automated verification

**Run:**
```bash
cd /Users/marius/evamp-ops

# Make script executable (one-time)
chmod +x scripts/test-phase1.sh

# Run test (requires Docker + .env configured)
bash scripts/test-phase1.sh
```

**What it does:**
- Checks prerequisites (Python, Docker)
- Verifies .env file
- Starts Docker containers
- Tests backend health (HTTP 200)
- Tests frontend (HTTP 200)
- Reports pass/fail

**Note:** You still need to manually test the Settings UI (add credential, AI model, warehouse) - see Option 1 steps 4-6.

**Time:** ~2 minutes (+ 5 min manual UI test)

---

## Prerequisites (All Options)

**Required:**
- Python 3.11+ (for key generation)
- Docker & Docker Compose (for Option 1 & 3)

**Optional (for manual setup in Option 2):**
- Node.js 18+
- PostgreSQL 15+

**One-time setup:**
```bash
# Install cryptography (for key generation)
pip3 install cryptography
```

---

## Quick Reference: What to Test

**Backend:**
- [ ] http://localhost:8000/health → 200 OK
- [ ] http://localhost:8000/docs → Swagger UI loads
- [ ] GET /api/settings/credentials → Returns list
- [ ] GET /api/settings/ai-models → Returns list
- [ ] GET /api/settings/warehouses → Returns list

**Frontend:**
- [ ] http://localhost:5173 → Home page loads
- [ ] Settings page → All 3 tabs work
- [ ] Add credential → Appears in list
- [ ] Add AI model → Appears with "Default" badge
- [ ] Add warehouse → Appears in list
- [ ] Refresh page → Data persists
- [ ] Navigation → All links work (Analytics, SKUs, Messages, Settings)

**Database:**
- [ ] Data persists after refresh
- [ ] No errors in backend logs when adding data

---

## If Something Fails

**Docker won't start:**
- See "Troubleshooting" in TEST_PHASE1.md
- Check: `docker-compose logs` for errors
- Verify .env has DB_PASSWORD and ENCRYPTION_KEY

**Backend errors:**
- Check: `docker-compose logs backend`
- Common: Missing ENCRYPTION_KEY, wrong DATABASE_URL
- Fix: Regenerate key, verify .env

**Frontend can't connect:**
- Ensure backend is running: http://localhost:8000/health
- Check CORS (backend allows http://localhost:5173)
- Check browser console (F12) for errors

**Database connection failed:**
- Docker: Ensure postgres container is "Up" (`docker-compose ps`)
- Manual: Start PostgreSQL, create database: `createdb evamp_ops`

**More help:** GETTING_STARTED.md has detailed troubleshooting

---

## After Testing

**If all tests pass:**
1. ✓ Phase 1 verified and working
2. Option: Commit to Git: `git add . && git commit -m "Phase 1 complete"`
3. Option: Push to GitHub (set up remote first)
4. Ready for Phase 2: eBay integration + SKU management

**If tests fail:**
1. Check troubleshooting in TEST_PHASE1.md
2. Review GETTING_STARTED.md
3. Verify .env configuration
4. Check Docker logs: `docker-compose logs -f`

---

## File Guide

- **QUICK_TEST.md** - 5 min quick verification (start here!)
- **TEST_PHASE1.md** - Full testing guide with troubleshooting
- **HOW_TO_TEST.md** - This file (testing options overview)
- **GETTING_STARTED.md** - Initial setup and run instructions
- **scripts/test-phase1.sh** - Automated prerequisite + health check

**Recommendation:** Start with QUICK_TEST.md. If you want more depth, use TEST_PHASE1.md.

Good luck! You've got comprehensive testing documentation.
