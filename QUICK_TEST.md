# Quick Phase 1 Test - 5 Minute Version

**Fastest way to verify Phase 1 works:**

## 1. Setup (One-Time)

```bash
cd /Users/marius/evamp-ops

# Install Python package for key generation (if needed)
pip3 install cryptography

# Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# COPY THE OUTPUT

# Create .env file
cp .env.example .env

# Edit .env - set these two lines:
# DB_PASSWORD=TestPassword123!
# ENCRYPTION_KEY=<paste the key you copied>
```

## 2. Start (30 seconds)

```bash
cd /Users/marius/evamp-ops
docker-compose up
```

Wait until you see:
- "Application startup complete" 
- "Local: http://localhost:5173"

## 3. Test (2 minutes)

**Open browser to http://localhost:5173**

1. **Click "Settings"** in the navigation
2. **Add credential:** 
   - Service: Anthropic
   - Key Name: api_key  
   - Value: test123 (or real key)
   - Click "Add Credential"
   - ✓ Should see it in the list

3. **Click "AI Models" tab**
   - Provider: Anthropic
   - Model: claude-3-5-sonnet-20241022
   - Check "Set as default"
   - Click "Add Model"
   - ✓ Should see "Default" badge

4. **Click "Warehouses" tab**
   - Shortname: Test
   - Address: 123 Test St
   - Country: UK
   - Click "Add Warehouse"
   - ✓ Should see it in the list

5. **Refresh page (F5)**
   - ✓ All data should still be there

## 4. Verify Backend

**Open new tab: http://localhost:8000/docs**

- ✓ See Swagger UI with API endpoints
- ✓ Try "GET /api/settings/credentials" → Execute
- ✓ Should return 200 with your credential (no value shown)

**Open: http://localhost:8000/health**

- ✓ Should show: `{"status":"healthy","database":"connected"}`

## Success!

If all checkmarks pass, **Phase 1 is working correctly.**

**Troubleshooting:** See TEST_PHASE1.md for detailed guide.

**Next:** Proceed to Phase 2 or commit your work to Git.
