# VigilZone — Quick Start

## Option A: Docker (one command)

```bash
docker compose up --build -d        # starts all 5 services
# UI  → http://localhost:8085
# API → http://localhost:8000/api/
# AI  → http://localhost:8080
```

Stop: `docker compose down -v`

---

## Option B: Local Dev (3 terminals)

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ (with venv at repo root `.venv`) |
| Node.js | 20+ |
| GPU (optional) | CUDA-capable NVIDIA GPU for fast inference |

### Terminal 1 — Django Backend (port 8000)

```powershell
cd services/backend
..\..\..\.venv\Scripts\python.exe manage.py migrate --noinput
..\..\..\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

### Terminal 2 — AI Module (port 8080)

```powershell
cd services/ai
..\..\..\.venv\Scripts\python.exe run.py
# First start loads models (~20s). Webcam auto-opens via cameras.yaml.
```

### Terminal 3 — React UI (port 5000)

```powershell
cd web/ui
npm install   # first time only
npm run dev
# Opens http://localhost:5000
```

### Access

| What | URL |
|------|-----|
| **Web UI** | http://localhost:5000 |
| **API root** (DRF browsable) | http://localhost:8000/api/ |
| **AI health** | http://localhost:8080/ |
| **AI cameras** | http://localhost:8080/cameras |

### First-time setup

```powershell
# Create a user (from services/backend/)
..\..\..\.venv\Scripts\python.exe manage.py createsuperuser
```

Or register via POST `/api/auth/register/` with `{ username, email, password }`.

---

## Architecture (local dev)

```
Browser :5000  ──Vite proxy──▶  Django :8000  ──proxy──▶  AI :8080
                                                           │
                                                    webcam (cam_live)
```

Vite proxies `/api/*` → Django, which proxies `/api/ai/*` → AI module.

---

## Key Endpoints

| Route | Auth | Description |
|-------|------|-------------|
| `POST /api/auth/token/` | — | Get JWT (`{username, password}`) |
| `GET /api/ai/cameras/` | JWT | Camera list (via AI) |
| `GET /api/ai/alerts/` | JWT | Recent alerts |
| `GET /api/ai/system/status/` | JWT | AI system diagnostics |
| `GET /api/ai/entities/` | JWT | Known entities list |
| `POST /api/ai/entities/enroll_person/` | JWT | Enroll person (multipart) |
| `GET /api/ai/frame/<cam_id>/` | JWT | Live snapshot (JPEG) |
| `GET /api/streams/` | JWT | Available video streams |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `npm run dev` fails on Windows | Already fixed with `cross-env`. Run `npm install` again. |
| AI module can't open webcam | Check `services/ai/configs/cameras.yaml` → `camera_index: 0` |
| Django can't reach AI | Ensure AI is running on `:8080`. Check `services/backend/.env` → `AI_BASE_INTERNAL=http://127.0.0.1:8080` |
| Port already in use | Kill the old process: `netstat -ano \| findstr :8080` then `taskkill /PID <pid> /F` |
