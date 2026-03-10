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

MediaMTX :8554 (RTSP) ◀── webcam_publisher (FFmpeg, host webcam or test pattern)
              │
              └── AI Module reads rtsp://mediamtx:8554/webcam

AI Module ──webhook──▶ Django /api/ai/webhook/receive/
```

> **Key principle:** The UI never calls `/ai/*` directly.
> All AI access is proxied through Django at `/api/ai/*` (JWT-protected).

## Quick Start

### Docker (full stack)

```bash
# 1. Copy env file and adjust if needed
cp .env.example .env

# 2. Build and start all services (includes MediaMTX + webcam publisher)
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
# 1. Start AI module (uses local webcam via cameras.yaml cam_live)
cd services\ai
python run.py                          # runs on :8080

# 2. Start Django backend
cd services\backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# 3. Start React UI dev server
cd web\ui
npm install
npx vite                               # runs on :5173, proxies /api → :8000

# 4. Register webhook (once, while AI + Django are running)
set AI_BASE_INTERNAL=http://127.0.0.1:8080
set PUBLIC_BASE_URL=http://127.0.0.1:8000
python manage.py register_ai_webhook
```

Open **http://localhost:5173** — login with your user credentials.

## Services

| Service | Port | Path | Description |
|---------|------|------|-------------|
| **Nginx** | 8085 | `/` | Reverse proxy + UI static files (Docker only) |
| **Django** | 8000 | `/api/*` | REST API, JWT auth, incidents, cameras, AI proxy |
| **AI** | 8080 | *(internal)* | CCTV AI detection — accessed only via Django proxy |
| **MediaMTX** | 8554 | *(RTSP)* | RTSP relay: receives webcam feed, serves to AI |
| **webcam_publisher** | — | — | FFmpeg: host webcam → RTSP → MediaMTX |
| **Vite** | 5173 | `/` | Dev UI server (local dev only) |

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
- `GET  /api/incidents/` — List incidents (filter: `?type=`, `?status=`)
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
- `GET  /api/debug/system/` — Aggregated system diagnostics (Django + AI)

### Django AI Proxy (`/api/ai/`) — JWT-protected
- `GET  /api/ai/cameras/` — AI camera list
- `GET  /api/ai/alerts/` — Filtered alerts
- `GET  /api/ai/frame/<camera_id>/` — Live JPEG snapshot (streaming)
- `GET  /api/ai/system/status/` — GPU + system diagnostics
- `GET  /api/ai/entities/` — List known entities
- `POST /api/ai/entities/enroll_person/` — Enroll person (multipart)
- `POST /api/ai/entities/enroll_pet/` — Enroll pet (multipart)
- `DELETE /api/ai/entities/<id>/` — Delete entity
- `POST /api/ai/webhooks/register/` — Register webhook with AI
- `GET  /api/ai/evidence/<camera_id>/<filename>` — Download evidence

### Webhook (token-protected, not JWT)
- `POST /api/ai/webhook/receive/` — AI → Django alert ingestion
  - Auth: `X-AI-WEBHOOK-TOKEN` header **or** `X-Vigilzone-Signature` (HMAC-SHA256)
  - Auto-creates camera if not found, deduplicates incidents (60s window)

## Live Camera Feed (MediaMTX + FFmpeg)

The `webcam_publisher` service captures the host webcam and publishes it to MediaMTX via RTSP. The AI module then reads the RTSP stream.

### Streaming Architecture

```
Camera/Webcam ──RTSP──▶ MediaMTX :8554
                           │
                           ├── AI Module reads  rtsp://mediamtx:8554/<stream_path>
                           ├── WebRTC viewer    /webrtc/<stream_path>  (port 8889, proxied via Nginx)
                           └── HLS viewer       /hls/<stream_path>    (port 8888, proxied via Nginx)

Nginx :8085
   ├─ /webrtc/*  →  mediamtx:8889   (WebRTC signalling + media)
   └─ /hls/*     →  mediamtx:8888   (HLS segments)

React UI loads:
   <iframe src="/webrtc/<stream_path>">   (main live feed via WebRTC)
   AuthImage src="/api/streams/{id}/snapshot/"  (thumbnails — JWT-authenticated blob fetch)
```

### Stream Path Mapping

Each camera in Django has a `stream_path` field that maps to a MediaMTX publish path.

| Camera Name | `stream_path` | MediaMTX RTSP URL | WebRTC URL |
|-------------|---------------|-------------------|------------|
| Webcam (dev) | `webcam` | `rtsp://mediamtx:8554/webcam` | `/webrtc/webcam` |
| Front Door | `front-door` | `rtsp://mediamtx:8554/front-door` | `/webrtc/front-door` |

If `stream_path` is left blank when creating a camera, it is auto-derived:
1. From `ai_camera_id` if set
2. From `slugify(name)` otherwise (e.g. "Front Door" → "front-door")

### Docker mode
- `webcam_publisher` reads `/dev/video0` (Linux) or generates an SMPTE test pattern as fallback
- Publishes to `rtsp://mediamtx:8554/webcam`
- AI ingests via `cameras.docker.yaml` (`camera_id: webcam`, `rtsp_url: rtsp://mediamtx:8554/webcam`)
- WebRTC/HLS proxied through Nginx at `/webrtc/webcam` and `/hls/webcam`

### Local dev (Windows)

#### Without MediaMTX (simplest)
The AI module uses `cam_live` with `live_camera` backend (OpenCV, index 0) — reads the webcam directly.
No streaming URLs will work in the UI, but AI detection runs.

#### With MediaMTX (full streaming)
1. Download [MediaMTX](https://github.com/bluenviron/mediamtx/releases) for Windows
2. Run `mediamtx.exe` (listens on :8554 RTSP, :8889 WebRTC, :8888 HLS)
3. Publish your webcam:
   ```powershell
   ffmpeg -f dshow -i video="<webcam name>" -c:v libx264 -preset ultrafast -tune zerolatency -f rtsp rtsp://localhost:8554/webcam
   ```
4. In `cameras.yaml`, use the `cam1` entry with `rtsp_url: rtsp://localhost:8554/webcam`
5. In Django, create a camera with `stream_path = webcam`
6. Vite proxies `/webrtc` → `localhost:8889` and `/hls` → `localhost:8888` automatically

### Adding a real RTSP camera
1. Configure the camera to publish RTSP (e.g. `rtsp://192.168.1.100:554/stream1`)
2. **(Option A) Direct** — Set `rtsp_url` on the Django camera and `stream_path` to match a MediaMTX path. Relay via MediaMTX: add a `paths:` entry in `mediamtx.yml` pointing the source to the camera's RTSP URL.
3. **(Option B) AI-only** — Set `rtsp_url` on the Django camera and sync to AI. AI reads directly; no WebRTC in the UI.

### Vite Dev Proxy

The Vite dev server proxies `/api`, `/webrtc`, and `/hls` so the React app can reach all services.
Defaults work for local dev; override with env vars when targets differ:

```bash
VITE_PROXY_TARGET=http://192.168.1.50:8000       # Django backend
VITE_MEDIAMTX_TARGET=http://192.168.1.50:8889    # MediaMTX WebRTC
VITE_MEDIAMTX_HLS_TARGET=http://192.168.1.50:8888 # MediaMTX HLS
```

### Fallback modes
Set `WEBCAM_FALLBACK` env var:
- `testsrc` (default) — SMPTE colour bars with timestamp overlay
- `mp4` — Loop a test video file (set `FALLBACK_MP4` path)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_DEBUG` | `1` | Django debug mode |
| `SECRET_KEY` | insecure default | Django secret key |
| `ALLOWED_HOSTS` | `localhost,...` | Django allowed hosts |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8085,...` | CORS origins |
| `AI_BASE_INTERNAL` | `http://ai:8080` | AI module URL (backend→AI internal network) |
| `AI_WEBHOOK_TOKEN` | *(empty)* | Flat token for `X-AI-WEBHOOK-TOKEN` auth |
| `AI_WEBHOOK_SECRET` | `vigilzone-webhook-secret` | HMAC secret for `X-Vigilzone-Signature` auth |
| `PUBLIC_BASE_URL` | `http://backend:8000` | Public URL for webhook callbacks |
| `WEBCAM_FALLBACK` | `testsrc` | Webcam publisher fallback: `testsrc` or `mp4` |
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` | Email backend (use `smtp.EmailBackend` for prod) |
| `DEFAULT_FROM_EMAIL` | `vigilzone@localhost` | Sender address for notifications |
| `EMAIL_HOST` | `smtp.gmail.com` | SMTP host |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_USE_TLS` | `True` | Use TLS for SMTP |
| `EMAIL_HOST_USER` | *(empty)* | SMTP username |
| `EMAIL_HOST_PASSWORD` | *(empty)* | SMTP password / app-specific password |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite dev proxy → Django backend |
| `VITE_MEDIAMTX_TARGET` | `http://127.0.0.1:8889` | Vite dev proxy → MediaMTX WebRTC |
| `VITE_MEDIAMTX_HLS_TARGET` | `http://127.0.0.1:8888` | Vite dev proxy → MediaMTX HLS |

## Project Structure

```
vigilzone-monolith/
  services/
    ai/                     # AI FastAPI microservice (port 8080)
      src/                  # AI module source code
      configs/
        cameras.yaml        # Local dev config (webcam direct)
        cameras.docker.yaml # Docker config (RTSP from MediaMTX)
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

## What Changed (Integration v5 — Streaming Bug-Fixes)

### A) Fix Snapshot 401
- **AuthImage component** — Reusable `<AuthImage>` fetches images through the authenticated axios instance (blob), auto-refreshes on interval
- **LiveAI.tsx** — Sidebar thumbnails and evidence images now use `AuthImage` instead of raw `<img>`, eliminating 401 errors

### B) Fix "No stream URL mapped"
- **Auto-derive `stream_path`** — `CameraWriteSerializer.validate()` and `Camera.save()` auto-set `stream_path` from `ai_camera_id` or `slugify(name)` when empty
- **Cameras.tsx** — Added `stream_path` field to the Add Camera form and table view

### C) Fix Vite Proxy ECONNREFUSED
- **vite.config.ts** — Proxy targets now use `VITE_PROXY_TARGET`, `VITE_MEDIAMTX_TARGET`, `VITE_MEDIAMTX_HLS_TARGET` env vars with sensible defaults
- **Added `/webrtc` and `/hls` proxy rules** for local dev without Nginx

### D) AI Camera Hot-Load
- **AlertServer.set_app_context()** — Receives shared evidence exporter, model config, etc. from CCTVAIModule
- **Register endpoint** — `POST /api/v1/cameras/register` now immediately creates and starts a `CameraProcessor` (hot-load), no restart required
- **sync_to_ai** — Django view now also back-fills `stream_path` and returns `hot_loaded` status

### E) MediaMTX Mapping Strategy
- **README** — Comprehensive streaming architecture docs: stream path mapping, dev/docker/real-camera workflows, Vite proxy configuration

---

## What Changed (Integration v4)

### RTSP Snapshot Fix (§1)
- **FFmpegReader** — Fully rewritten subprocess-based reader with configurable `rtsp_transport`, reconnect logic, and `get_diagnostics()` method
- **AI proxy** — Added `Cache-Control: no-store` header on streaming snapshot responses

### Intrusion Zones & Camera Types (§2)
- **Camera model** — Added `camera_type` (BACKYARD, FRONT_DOOR, BEDROOM, GARAGE, LIVING_ROOM, OTHER)
- **CameraZone model** — Per-camera polygon zones (RESTRICTED / MONITOR), full CRUD via REST
- **AI endpoints** — `PUT /cameras/{id}/zones` and `PUT /cameras/{id}/settings` to push zone/threshold config live
- **CameraProcessor.update_zones()** — Propagates zone polygons to zone-aware lanes at runtime

### False-Positive Reduction (§3)
- **Per-camera AI settings** — `min_confidence`, `min_bbox_area`, `k_of_n_k`, `k_of_n_n`, `cooldown_s` on Camera model
- **sync_ai_settings** view — Pushes thresholds from Django to AI module

### Notification API (§4)
- **NotificationChannel model** — OneToOne per Tenant: email/push toggles, email recipients, FCM tokens, severity threshold
- **Settings/Test/Register views** — GET/PUT settings, POST test email, POST register FCM device
- **dispatch_notifications()** — Auto-sends email on incident create/escalate (wired into webhook receiver)
- **Email config** — Console backend (dev), SMTP env vars for production

### YOLO12 Critical Lane (§5)
- **yolo12_critical.py** — New detection lane: fire, smoke, knife, gun, bear, dog, wolf, deer
- **Persistence tracking** — K-of-N confirmation (default 3-of-6) before alerting
- **Registered** in `LANE_REGISTRY`, `_LANE_HZ_CATEGORY`, models.yaml, cameras.yaml

### Debug Tab (§7)
- **debug_system** API — Aggregates Django uptime, DB status, AI status + camera health
- **Debug.tsx** — New UI page with system stats, camera health table, raw diagnostics
- **Dashboard.tsx** — Removed system health section (moved to Debug)
- **NavBar** — Added Debug nav item

### Housekeeping
- **Removed Watchlist** (§8) — Removed from KnownEntity model, serializers, views, UI
- **MediaMTX** (§9) — Already complete in docker-compose
- **Migration 0008** applied — All new models and fields

---

## What Changed (Integration v3)

### Phase 1 & 2 — UI + Backend wiring
- **All 8+ UI pages** rewritten: Dashboard, Cameras, Incidents, IncidentDetails, Reports, Settings, Community, Entities — wired to real Django/AI APIs via `useQuery`/`useMutation`
- **LiveAI.tsx** — Fixed `device` object rendering error; properly handles nested `SystemStatus.device`
- **New Django endpoints**: `dashboard_summary`, `incidents/stats`, `incidents/{id}/acknowledge`, `incidents/{id}/resolve`, `profile/me` (GET/PATCH)
- **Extended models**: Profile with notification/privacy/system settings (8 new fields)
- **IncidentSerializer** — Added `camera_name` field

### Phase 3 — MediaMTX + RTSP live camera
- **docker-compose.yml** — Added `mediamtx` (RTSP server) and `webcam_publisher` (FFmpeg) services
- **webcam_publisher/** — Dockerfile + `entrypoint.sh` (tries v4l2 webcam, falls back to SMPTE test pattern)
- **cameras.docker.yaml** — Docker-specific AI camera config reading from `rtsp://mediamtx:8554/webcam`
- **cameras.yaml** — Added commented RTSP camera entry for reference

### Phase 4 — Webhook persistence
- **Webhook auth aligned** — Django receiver now accepts both `X-AI-WEBHOOK-TOKEN` (flat) and `X-Vigilzone-Signature` (HMAC-SHA256)
- **Auto-registration** — `AiIntegrationConfig.ready()` spawns background thread to register webhook with AI on startup
- **register_ai_webhook** command — Now passes `AI_WEBHOOK_SECRET` as HMAC secret when registering

### Phase 5 — Deliverables
- **Acceptance tests** — `tests/acceptance.sh` (bash) + `tests/acceptance.ps1` (PowerShell)
- **README** — Comprehensive docs with architecture, local dev, Docker, testing
