# Hostinger VPS Deployment Guide

Deploy the OpenEvent AI backend to Hostinger VPS, then connect from Lovable frontend.

---

## Quick Reference

| What you need | Where to find it |
|---------------|------------------|
| **VPS IP Address** | `72.60.135.183` |
| **Backend Port** | `8000` |
| **Lovable env var** | `VITE_BACKEND_BASE=http://72.60.135.183:8000` |
| **API Endpoints** | See table below or [API_TESTS.md](./API_TESTS.md) |
| **Setup script** | `deploy/setup-vps.sh` |
| **Service config** | `deploy/openevent.service` |

### Files in this folder:
```
deploy/
├── README.md           ← You are here (setup guide)
├── API_TESTS.md        ← All endpoints with curl examples
├── setup-vps.sh        ← Run this on VPS to install everything
└── openevent.service   ← systemd service configuration
```

---

## Your VPS Info
- **Server:** srv1153474.hstgr.cloud
- **IP:** 72.60.135.183
- **Status:** Active (expires 2026-11-26)

---

## Step-by-Step Setup

### Step 1: SSH into your VPS

```bash
ssh root@72.60.135.183
```

(Use the password from Hostinger panel, or setup SSH keys)

---

### Step 2: Run the Setup Script

```bash
# Install git first
apt update && apt install -y git

# Clone your repo
cd /opt
git clone https://github.com/YOUR_USERNAME/OpenEvent-AI.git openevent
cd openevent

# Make scripts executable and run setup
chmod +x deploy/*.sh
./deploy/setup-vps.sh
```
This installs the pinned backend dependencies from `requirements-dev`.

---

### Step 3: Configure Environment

```bash
nano /opt/openevent/.env
```

Add these values:
```
# ========== HYBRID MODE (recommended) ==========
# Uses BOTH providers for optimal cost/quality:
#   - Gemini: intent detection & entity extraction (cheaper)
#   - OpenAI: client-facing verbalization (higher quality)

OPENAI_API_KEY=sk-your-openai-key-here
GOOGLE_API_KEY=AIza-your-gemini-key-here
AGENT_MODE=gemini

# CORS - Allow Lovable frontend to connect
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,http://localhost:3000
PYTHONDONTWRITEBYTECODE=1
```

**Important:**
- **Both API keys are required** for hybrid mode
- `AGENT_MODE=gemini` sets Gemini for detection; OpenAI is auto-used for verbalization
- If you only have OpenAI, set `AGENT_MODE=openai` (works but costs more)
- `ALLOWED_ORIGINS` enables CORS for Lovable!

---

### Step 4: Update Nginx Config

```bash
nano /etc/nginx/sites-available/openevent
```

Replace `your-domain.com` with either:
- Your domain (e.g., `api.yourdomain.com`)
- Or just use the IP: `72.60.135.183`

Then reload:
```bash
nginx -t && systemctl reload nginx
```

---

### Step 5: Restart Services

```bash
systemctl restart openevent
systemctl status openevent
```

You should see "active (running)".

---

### Step 6: Test the Backend

From your local machine or browser:
```bash
curl http://72.60.135.183:8000/api/workflow/health
```

Should return: `{"status":"ok"}`

---

## Production Mode (IMPORTANT)

When deploying for real clients, switch from dev to production mode:

### Required Environment Variables

Add these to `/opt/openevent/.env`:

```bash
# ========== PRODUCTION MODE ==========
ENV=prod                      # Hides debug routes, removes db_path from health endpoint
AUTH_ENABLED=1                # Requires API key for all endpoints (except health)
RATE_LIMIT_ENABLED=1          # Prevents abuse
TENANT_HEADER_ENABLED=0       # Disables header-based tenant switching

# ========== ERROR ALERTING (optional) ==========
# Get notified when AI fails and falls back to manual review
# ⚠️  PRIVACY NOTE: Alert emails include client message content (PII)
#    Only add trusted internal staff to ALERT_EMAIL_RECIPIENTS
ALERT_EMAIL_RECIPIENTS=ops@openevent.com,dev@openevent.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASS=your-smtp-password
```

### Quick Toggle Script

```bash
# Switch to production mode
nano /opt/openevent/.env
# Add: ENV=prod AUTH_ENABLED=1 RATE_LIMIT_ENABLED=1 TENANT_HEADER_ENABLED=0
systemctl restart openevent

# Verify production mode
curl http://72.60.135.183:8000/api/workflow/health
# Should return: {"ok": true}  (no db_path in prod)

curl http://72.60.135.183:8000/api/events
# Should return: 401 Unauthorized (auth required in prod)
```

### Production Checklist

- [ ] `ENV=prod` set
- [ ] `AUTH_ENABLED=1` set
- [ ] `RATE_LIMIT_ENABLED=1` set
- [ ] `TENANT_HEADER_ENABLED=0` set (never enable in prod)
- [ ] API keys configured (OPENAI + GOOGLE for hybrid mode)
- [ ] CORS origins set to your frontend domains only
- [ ] (Optional) Error alerting configured with SMTP
- [ ] Test: trigger a fallback and verify no client sees the error

### Security Notes

| Setting | Dev | Prod | Why |
|---------|-----|------|-----|
| `ENV` | dev | **prod** | Hides debug routes, db paths |
| `AUTH_ENABLED` | 0 | **1** | Protects API from public access |
| `RATE_LIMIT_ENABLED` | 0 | **1** | Prevents abuse |
| `TENANT_HEADER_ENABLED` | 1 | **0** | Header spoofing risk |

---

## Connect Lovable Frontend

Once the backend is running, tell your colleague:

**In Lovable project settings, add environment variable:**
```
VITE_BACKEND_BASE=http://72.60.135.183:8000
```

That's it! The frontend will now call your Hostinger backend.

---

## API Endpoints (43 Total)

**For detailed curl examples and test results, see [API_TESTS.md](./API_TESTS.md)**.

### Authentication
Most endpoints require the `X-Team-Id` header for multi-tenancy:
```bash
curl -H "X-Team-Id: your-team-id" http://72.60.135.183:8000/api/...
```

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/start-conversation` | POST | Start new chat |
| `/api/send-message` | POST | Send message to agent |
| `/api/conversation/{id}` | GET | Get conversation state |
| `/api/tasks/pending` | GET | Get HIL tasks for manager |
| `/api/tasks/{id}/approve` | POST | Approve HIL task |
| `/api/tasks/{id}/reject` | POST | Reject HIL task |
| `/api/tasks/cleanup` | POST | Clear old tasks |
| `/api/events` | GET | List all events |
| `/api/events/{id}` | GET | Get event details |
| `/api/workflow/health` | GET | Health check |
| `/api/workflow/hil-status` | GET | HIL toggle status |
| `/api/config/global-deposit` | GET/POST | Deposit settings |
| `/api/config/hil-mode` | GET/POST | HIL mode toggle |
| `/api/config/prompts` | GET/POST | LLM prompt config |
| `/api/event/deposit/pay` | POST | Pay deposit (simulation) |
| `/api/event/{id}/deposit` | GET | Get deposit status |
| `/api/qna` | GET | Q&A data |
| `/api/test-data/rooms` | GET | Room data |
| `/api/test-data/catering` | GET | Catering menus |
| `/api/snapshots/{id}` | GET | Snapshot data |

See [API_TESTS.md](./API_TESTS.md) for full list of 43 endpoints with curl examples.

**Backend source references (for quick edits)**
Endpoints are organized in modular route files under `backend/api/routes/`:

| Route File | Endpoints |
|------------|-----------|
| `messages.py` | `/api/start-conversation`, `/api/send-message`, `/api/conversation/*` |
| `tasks.py` | `/api/tasks/pending`, `/api/tasks/{id}/approve`, `/api/tasks/{id}/reject` |
| `workflow.py` | `/api/workflow/health`, `/api/workflow/hil-status` |
| `config.py` | `/api/config/global-deposit`, `/api/config/hil-mode`, `/api/config/prompts` |
| `events.py` | `/api/events`, `/api/event/{id}/deposit`, `/api/event/deposit/pay` |
| `test_data.py` | `/api/test-data/rooms`, `/api/test-data/catering`, `/api/qna` |
| `snapshots.py` | `/api/snapshots/*` |
| `debug.py` | `/api/debug/*` (requires DEBUG_TRACE_ENABLED=true) |

---

## Useful Commands

```bash
# Check if service is running
systemctl status openevent

# View live logs
journalctl -u openevent -f

# Restart after changes
systemctl restart openevent

# Update from GitHub
cd /opt/openevent && git pull && systemctl restart openevent

# Check what's using port 8000
lsof -i :8000
```

---

## Troubleshooting

### Backend won't start
```bash
# Check logs
journalctl -u openevent -n 100 --no-pager

# Common issues:
# - Missing OPENAI_API_KEY in .env
# - Python dependencies not installed
# - Port 8000 already in use
```

### CORS errors from Lovable
Make sure `.env` has:
```
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app
```
Then restart: `systemctl restart openevent`

### Permission errors
```bash
chown -R root:root /opt/openevent
```

### Can't connect from Lovable
1. Check backend is running: `systemctl status openevent`
2. Check firewall allows port 8000: `ufw allow 8000`
3. Test from local: `curl http://72.60.135.183:8000/api/workflow/health`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LOVABLE                              │
│                 (Your colleague's frontend)             │
│                                                         │
│   VITE_BACKEND_BASE = http://72.60.135.183:8000        │
└─────────────────────────┬───────────────────────────────┘
                          │ API calls (fetch)
                          ▼
┌─────────────────────────────────────────────────────────┐
│               HOSTINGER VPS (72.60.135.183)             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  uvicorn (:8000)                                │   │
│  │  FastAPI backend                                │   │
│  │  - /api/send-message                            │   │
│  │  - /api/tasks/pending                           │   │
│  │  - /api/tasks/{id}/approve                      │   │
│  │  - etc.                                         │   │
│  └─────────────────────────────────────────────────┘   │
│                          │                              │
│                          ▼                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │  events_database.json                           │   │
│  │  (workflow state, events, tasks)                │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Optional: Setup SSL (HTTPS)

If you have a domain pointed to your VPS:

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d api.yourdomain.com
```

Then update Lovable to use `https://` instead of `http://`.
