# VigilZone Monolith

Unified monorepo integrating the **React UI**, **Django REST API**, and **AI FastAPI** microservice behind a single Nginx reverse proxy.

## Architecture

```
Browser ──▶ Nginx :8085
              │
              ├─ /           → React UI (static files)
              ├─ /api/       → Django REST API :8000
              │    └─ /api/ai/*  → Django proxies to AI :8080
              └─ /ai/ (internal) → AI FastAPI :8080 (not exposed to browser)

RTSP Camera/Webcam ──▶ Django OpenCV workers ──▶ MJPEG/Snapshot endpoints

AI Module ──webhook──▶ Django /api/ai/webhook/receive/
```

> **Key principle:** The UI never calls `/ai/*` directly.
> All AI access is proxied through Django at `/api/ai/*` (JWT-protected).

## Quick Start

### Docker (full stack)

```bash
# 1. Copy env file and adjust if needed
cp .env.example .env

# 2. Build and start all services
docker compose up --build

# 3. (First run) Apply Django migrations + create superuser
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser

# 4. Webhook auto-registers on startup. To manually (re-)register:
docker compose exec backend python manage.py register_ai_webhook
```

Once running, open **http://localhost:8085** in your browser.

### Local Development (Windows)

```powershell
# 1. Start AI module (cam_live is optional and defaults to OFF)
cd services\ai
python run.py                          # runs on :8080

# 2. Start Django backend
cd services\backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# 3. Start React UI dev server
cd web\ui
npm install
npm run dev                            # runs on :5000, serves UI + Vite middleware

# 4. Register webhook (once, while AI + Django are running)
set AI_BASE_INTERNAL=http://127.0.0.1:8080
set PUBLIC_BASE_URL=http://127.0.0.1:8000
python manage.py register_ai_webhook
```

Open **http://localhost:5000** — login with your user credentials.

To start the webcam stream automatically at AI boot, set:

```powershell
set AI_WEBCAM_DEFAULT_ENABLED=true
```

Otherwise, enable/disable webcam runtime from **Live AI** (calls `/api/ai/webcam-state/`).

## Services

| Service | Port | Path | Description |
|---------|------|------|-------------|
| **Nginx** | 8085 | `/` | Reverse proxy + UI static files (Docker only) |
| **Django** | 8000 | `/api/*` | REST API, JWT auth, incidents, cameras, AI proxy |
| **AI** | 8080 | *(internal)* | CCTV AI detection — accessed only via Django proxy |
| **OpenCV Worker Pool** | in backend | `/api/streams/*` | In-process capture workers for snapshot + MJPEG preview |
| **UI Dev Server (Express + Vite middleware)** | 5000 | `/` | Local dev server (`npm run dev`) |

## Key Endpoints

### Django Core API (`/api/`)
- `POST /api/auth/token/` — Obtain JWT access/refresh tokens
- `POST /api/auth/refresh/` — Refresh access token
- `POST /api/auth/register/` — Register new user
- `GET  /api/auth/context/` — Current user + tenants
- `GET  /api/cameras/` — List cameras (CRUD)
- `GET  /api/cameras/{id}/zones/` — List camera zones
- `POST /api/cameras/{id}/zones/` — Create zone
- `PUT  /api/cameras/{id}/zones/{zone_id}/` — Update zone
- `DELETE /api/cameras/{id}/zones/{zone_id}/` — Delete zone
- `POST /api/cameras/{id}/sync_zones_to_ai/` — Push zones to AI
- `POST /api/cameras/{id}/sync_ai_settings/` — Push per-camera AI thresholds
- `GET  /api/streams/` — List stream-capable cameras with derived stream URLs
- `GET  /api/streams/{id}/` — Stream metadata for one camera
- `GET  /api/streams/{id}/signed_stream_token/` — Issue short-lived token for MJPEG/snapshot image tags
- `GET  /api/streams/{id}/snapshot/` — Fast latest JPEG snapshot (JWT or token auth)
- `GET  /api/streams/{id}/mjpeg/` — Multipart MJPEG stream (`?token=...`)
- `GET  /api/streams/health/` — Per-camera worker health and viewer counts
- `GET  /api/incidents/` — List incidents (filter: `?type=`, `?status=`, `?search=`)
- `POST /api/incidents/{id}/acknowledge/` — Acknowledge incident
- `POST /api/incidents/{id}/resolve/` — Resolve incident
- `GET  /api/incidents/stats/` — Incident statistics (today/week/month, breakdown)
- `GET  /api/dashboard/summary/` — Dashboard summary (cameras, stats, recent)
- `GET  /api/profile/me/` — Current user profile (GET/PATCH)
- `GET  /api/detections/` — List detections
- `GET  /api/audit/` — Audit log
- `GET/PUT /api/notifications/settings/` — Notification channel config
- `POST /api/notifications/test/` — Send test notification
- `POST /api/notifications/register_device/` — Store FCM token
- `GET  /api/notifications/transport-status/` — Channel transport health (Redis/in-memory reachability)
- `GET/POST /api/ai/webcam-state/` — Persisted + runtime cam_live toggle/status
- `GET  /api/debug/system/` — Aggregated system diagnostics (Django + AI)

### Django AI Proxy (`/api/ai/`) — JWT-protected
- `GET  /api/ai/cameras/` — AI camera list
- `GET  /api/ai/alerts/` — Filtered alerts
- `GET  /api/ai/frame/<camera_id>/` — Live JPEG snapshot (streaming)
- `GET  /api/ai/system/status/` — GPU + system diagnostics
- `GET  /api/ai/entities/` — List known entities
- `POST /api/ai/entities/enroll_person/` — Enroll person (multipart)
- `POST /api/ai/entities/enroll_pet/` — Enroll pet (multipart)
- `POST /api/ai/entities/enroll_person_from_upload/` — Enroll person from staged upload images
- `POST /api/ai/entities/enroll_pet_from_upload/` — Enroll pet from staged upload images
- `POST /api/ai/uploads/enroll_images/` — Stage enrollment images
- `DELETE /api/ai/entities/<id>/` — Delete entity
- `POST /api/ai/webhooks/register/` — Register webhook with AI
- `GET  /api/ai/evidence/<camera_id>/<filename>` — Download evidence

### Webhook (token-protected, not JWT)
- `POST /api/ai/webhook/receive/` — AI → Django alert ingestion
  - Auth: `X-AI-WEBHOOK-TOKEN` header **or** `X-Vigilzone-Signature` (HMAC-SHA256)
  - Auto-creates camera if not found, deduplicates incidents (60s window)

## Local Preview Streaming (OpenCV + MJPEG)

Live browser preview now runs directly from Django with OpenCV workers. No MediaMTX, WebRTC, or external streaming server is required.

### Streaming Architecture

```text
RTSP camera or webcam index "0"
            │
            └──▶ Django StreamWorker (OpenCV capture thread per camera)
                        ├── latest JPEG in memory (cached snapshot)
                        └── MJPEG multipart stream

React UI
  ├── GET /api/streams/<id>/signed_stream_token/
  ├── <img src="/api/streams/<id>/mjpeg/?token=...">
  └── optional health poll: GET /api/streams/health/
```

### API Endpoints

- `GET /api/streams/<id>/signed_stream_token/` issues a short-lived stream token (default 60s).
- `GET /api/streams/<id>/snapshot/` returns `image/jpeg`.
  - Auth mode A: JWT + tenant membership.
  - Auth mode B: `?token=` signed token.
- `GET /api/streams/<id>/mjpeg/?token=...` returns multipart MJPEG stream for `<img>`.
- `GET /api/streams/health/` returns per-camera worker health:
  - `connected`, `last_frame_ts`, `last_error`, `fps_config`, `viewers`.

### Runtime Reliability Notes

- Stream capture reconnect uses exponential backoff (starts near 2s, capped at 60s) and resets on successful frames.
- Lane scheduling in the AI processor uses per-lane in-flight backpressure to avoid runaway unfinished-future buildup.
- AnyAnomaly lane performs dependency preflight and gracefully disables itself when required packages are missing.
- During Django autoreload, transient requests can return `503 {"detail":"Service restarting"}` instead of a noisy ASGI 500 traceback.

### Runbook

1. Configure stream env vars in `.env` (`STREAM_PREVIEW_*`, `OPENCV_FFMPEG_CAPTURE_OPTIONS`).
2. Ensure cameras have a valid source:
   - local webcam: `rtsp_url="0"`
   - remote stream: `rtsp://...`
3. Start backend and UI.
4. Open Dashboard or Live AI. UI fetches a signed token and uses MJPEG `<img>` playback.
5. Check `/api/streams/health/` for warm-up/errors/reconnect diagnostics.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_DEBUG` | `1` | Django debug mode |
| `UI_PORT` | `5000` | Local UI dev server port |
| `SECRET_KEY` | insecure default | Django secret key |
| `ALLOWED_HOSTS` | `localhost,...` | Django allowed hosts |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8085,...` | CORS origins |
| `AI_BASE_INTERNAL` | `http://127.0.0.1:8080` (local) / `http://ai:8080` (docker) | AI module URL (backend→AI internal network) |
| `AI_WEBHOOK_TOKEN` | *(empty)* | Flat token for `X-AI-WEBHOOK-TOKEN` auth |
| `AI_WEBHOOK_SECRET` | `vigilzone-webhook-secret` | HMAC secret for `X-Vigilzone-Signature` auth |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000` (local) / `http://localhost:8085` (docker proxy) | Public URL for webhook callbacks |
| `CHANNEL_LAYER_BACKEND` | `inmemory` (local) | Channels backend: `inmemory` for local dev, `redis` for docker/prod |
| `REDIS_HOST` | *(empty local)* / `redis` (docker) | Redis hostname used when `CHANNEL_LAYER_BACKEND=redis` |
| `REDIS_PORT` | `6379` | Redis port used by channel layer |
| `AI_AUTO_REGISTER_WEBHOOK` | `0` (debug local) | Auto-register AI webhook on startup (`1` enables startup registration) |
| `DEFAULT_AI_TENANT_ID` | *(empty)* | Optional tenant id used for AI webhook incidents when camera mapping is missing |
| `FETCH_AI_RUNTIME_STATUS` | `true` | Whether `/api/ai/webcam-state/` GET actively polls AI runtime status |
| `AI_WEBCAM_DEFAULT_ENABLED` | `false` | AI startup default for `cam_live` processor (`true` starts webcam automatically) |
| `STREAM_PREVIEW_FPS` | `3` | Capture FPS per camera worker |
| `STREAM_PREVIEW_MAX_WIDTH` | `960` | Optional max width for preview JPEG resizing |
| `STREAM_PREVIEW_JPEG_QUALITY` | `70` | JPEG encoding quality for snapshots/MJPEG |
| `STREAM_IDLE_TTL_SECONDS` | `60` | Stop worker after this idle period |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | `rtsp_transport;tcp|stimeout;3000000` | OpenCV FFmpeg capture options for RTSP reliability |
| `WEBCAM_FALLBACK` | `testsrc` | Webcam publisher fallback: `testsrc` or `mp4` |
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` | Email backend (use `smtp.EmailBackend` for prod) |
| `DEFAULT_FROM_EMAIL` | `vigilzone@localhost` | Sender address for notifications |
| `EMAIL_HOST` | `smtp.gmail.com` | SMTP host |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_USE_TLS` | `True` | Use TLS for SMTP |
| `EMAIL_HOST_USER` | *(empty)* | SMTP username |
| `EMAIL_HOST_PASSWORD` | *(empty)* | SMTP password / app-specific password |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite dev proxy → Django backend |
| `VITE_ENABLE_WEBRTC` | `false` | Enable WebRTC-first playback in camera cards (`true` enables staged migration path) |
| `VITE_WEBRTC_VIEWER_BASE_URL` | *(empty)* | Base URL for MediaMTX WebRTC viewer (example: `http://localhost:8889`) |

### Local vs Docker `.env` presets

Use one of these minimal presets to avoid environment-specific guesswork.

#### Local development (Windows/macOS/Linux, no Redis required)

```env
DJANGO_DEBUG=1
CHANNEL_LAYER_BACKEND=inmemory
REDIS_HOST=
REDIS_PORT=6379
AI_AUTO_REGISTER_WEBHOOK=0
AI_BASE_INTERNAL=http://127.0.0.1:8080
PUBLIC_BASE_URL=http://127.0.0.1:8000
VITE_PROXY_TARGET=http://127.0.0.1:8000
VITE_ENABLE_WEBRTC=false
VITE_WEBRTC_VIEWER_BASE_URL=
```

#### Docker / Compose development

```env
DJANGO_DEBUG=0
CHANNEL_LAYER_BACKEND=redis
REDIS_HOST=redis
REDIS_PORT=6379
AI_AUTO_REGISTER_WEBHOOK=1
AI_BASE_INTERNAL=http://ai:8080
PUBLIC_BASE_URL=http://localhost:8085
VITE_PROXY_TARGET=http://backend:8000
VITE_ENABLE_WEBRTC=true
VITE_WEBRTC_VIEWER_BASE_URL=http://mediamtx:8889
```

## Project Structure

```
vigilzone-monolith/
  services/
    ai/                     # AI FastAPI microservice (port 8080)
      src/                  # AI module source code
      configs/
        cameras.yaml        # Local dev config (webcam direct)
        cameras.docker.yaml # Docker config
      models/               # YOLO weights
      Dockerfile
    backend/                # Django REST API (port 8000)
      ai_integration/       # AI proxy + webhook Django app
        proxy.py            # Generic proxy helper (Django → AI)
        views.py            # All AI proxy views + webhook receiver
        urls.py             # /api/ai/* URL patterns
        apps.py             # Auto-registers webhook on startup
        management/commands # register_ai_webhook, close_stale_incidents
      api/                  # Core Django app (models, views, serializers)
      server/               # Django project (settings, urls)
      Dockerfile
    webcam_publisher/       # FFmpeg webcam → RTSP publisher
      Dockerfile
      entrypoint.sh
  web/
    ui/                     # React UI (Vite + wouter + Radix)
      client/src/           # React source
      Dockerfile            # Multi-stage: build UI → Nginx
  deploy/
    nginx/
      nginx.conf            # Reverse proxy configuration
  tests/
    acceptance.sh           # Acceptance tests (bash)
    acceptance.ps1          # Acceptance tests (PowerShell)
  docker-compose.yml
  .env.example
```

## Acceptance Testing

### PowerShell (Windows)
```powershell
.\tests\acceptance.ps1
```

### Bash (Linux/macOS/WSL)
```bash
bash tests/acceptance.sh
```

### Manual curl tests
```bash
# Obtain JWT
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"dev","password":"VigilZone2024!"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

# Core endpoints
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/cameras/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/incidents/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/dashboard/summary/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/incidents/stats/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/profile/me/

# AI proxy
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/ai/cameras/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/ai/system/status/
curl -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 2" http://localhost:8000/api/ai/frame/cam_live/ --output frame.jpg

# Simulate webhook
curl -X POST http://localhost:8000/api/ai/webhook/receive/ \
  -H 'Content-Type: application/json' \
  -d '{"event":"alert.created","data":{"id":"test-1","camera_id":"cam_live","type":"fire","severity":"high","timestamp":"2025-01-01T12:00:00Z","message":"Test fire","confidence":0.92,"evidence":{}}}'
```

## Management Commands

```bash
# Register webhook URL with AI module
python manage.py register_ai_webhook

# Close stale incidents (no updates for 5 minutes)
python manage.py close_stale_incidents --minutes 5
```
