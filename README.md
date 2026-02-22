# EvampOps - Stock Management & Customer Service Platform

A full-stack application for managing eBay stock operations and customer service with AI-powered message drafting.

## Features

### Stock Manager
- **Sales Analytics Dashboard** (SM01) - Interactive charts with filtering
- **eBay Data Import** (SM02) - Automated order sync via API
- **SKU Management** (SM03) - Product catalog with costs
- **Stock Planning** (SM04) - Order calculation tools
- **Warehouse Management** (SM05) - Address tracking
- **Supplier Orders** (SM06-07) - Order generation and tracking

### Customer Service
- **Message Import** (CS01) - Real-time eBay message sync (incremental, full, periodic full every 10 min). See [docs/SYNC_LOGIC.md](docs/SYNC_LOGIC.md).
- **Thread Management** (CS02-03) - Organized conversation view
- **AI Message Drafting** (CS04-06) - Multi-provider AI support
- **Translation** (CS07-08) - Automatic language detection and translation
- **Message Sending** (CS09) - Direct eBay API integration; image attachments (attach or drag onto reply box). Attachment bytes are stored in DB for retention after eBay purges messages. See [docs/MESSAGE_ATTACHMENTS.md](docs/MESSAGE_ATTACHMENTS.md).
- **Search & Flagging** (CS10-12) - Quick message retrieval

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React, TypeScript, Vite, TailwindCSS
- **AI**: Anthropic Claude, OpenAI GPT, LiteLLM
- **Testing**: Pytest, Vitest

## Quick Start

### Prerequisites

- Docker & Docker Compose
- (Optional) Python 3.11+, Node.js 18+, PostgreSQL 15+

### Setup

1. **Clone and configure:**
   ```bash
   cd evamp-ops
   cp .env.example .env
   ```

2. **Edit `.env` file:**
   - Generate encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - Set a strong database password
   - Add eBay API credentials (from https://developer.ebay.com/my/keys)

3. **Start the application:**
   ```bash
   make up
   ```
   Or: `docker compose up -d`. From project root only.

4. **Access the app:**
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

**One-command start:** From project root, `make up` (or `make start` to start and tail logs). `make down` to stop. See [Makefile](Makefile). **Exact commands:** [docs/HOW_TO_START.md](docs/HOW_TO_START.md). **One command (app + tunnel + browser):** `make run`.

**eBay OAuth:** Free ngrok gives a new URL each restart, so you’d have to update eBay’s Auth Accepted URL every time. Use **[localhost.run](docs/LOCALHOST_RUN_SETUP.md)** (free; sign up and add your SSH key for a stable URL). Run `make tunnel` when you need eBay; set the callback URL once in eBay. Or [deploy the backend](docs/DEPLOY_BACKEND.md) or [other tunnels](docs/STABLE_CALLBACK_URL.md).

### Manual Setup (Without Docker)

<details>
<summary>Click to expand</summary>

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**PostgreSQL:**
Ensure PostgreSQL is running locally on port 5432 with the database configured in `.env`

</details>

## Development

### Running Tests

**Backend:**
```bash
cd backend
pytest --cov=app --cov-report=html
```

**Frontend:**
```bash
cd frontend
npm run test
```

### Security Scanning

```bash
cd backend
safety check
pip-audit
```

## eBay API Setup

1. Create a developer account at https://developer.ebay.com
2. Register your application to get App ID, Cert ID, and Dev ID
3. Set up OAuth tokens through the application
4. Configure webhooks for message notifications

## AI Provider Setup

Configure AI providers in the Settings page:
- **Anthropic**: Get API key from https://console.anthropic.com
- **OpenAI**: Get API key from https://platform.openai.com
- **LiteLLM**: Configure local models (Ollama) or other providers

## Security

- All API keys encrypted at rest using Fernet
- Database localhost-only access
- CORS restricted to localhost
- Input validation on all endpoints
- Webhook signature verification
- No sensitive data in logs

## Project Structure

```
evamp-ops/
├── backend/          # FastAPI application
├── frontend/         # React application
├── docker-compose.yml
├── .env.example
└── README.md
```

## License

Private - Internal Use Only

## Support

For issues or questions, contact the development team.
