You are a senior full-stack + AI systems engineer. Your task is to integrate TWO existing codebases into ONE repo that runs as a single “monolith microservice” from the user’s perspective (one base URL), while keeping services internally separated.

INPUTS (local files):
- /mnt/data/ai_module.zip  (VigilZone AI module)
- /mnt/data/295A-main.zip  (Main UI + Django backend)

HIGH-LEVEL GOAL:
Create a single repo (monorepo) with:
- React UI (from 295A-main/UI) served at `/`
- Django REST API (from 295A-main/backend/server) served at `/api/*`
- AI FastAPI microservice (from ai_module/src/app.py and ai_module/src/api/server.py) served at `/ai/*` AND websocket at `/ai/ws`
All behind ONE Nginx reverse proxy so the user hits one URL/port only.

IMPORTANT CONSTRAINTS:
- Do NOT redesign the AI model logic. Treat AI module as a black box that already exposes REST/WebSocket/Webhooks.
- Prefer minimal invasive changes. Integration should be “wiring + contracts”, not refactors.
- Keep the existing Django API endpoints intact (JWT endpoints etc).
- Ensure websocket proxying works for the AI module (`/ai/ws`).

WHAT YOU MUST DO (deliverables):
1) Unzip both archives, inspect existing run commands, ports, and API endpoints.
2) Create a NEW unified repo folder, suggested name `vigilzone-monolith/` with this layout:
   vigilzone-monolith/
     services/
       ai/          (from ai_module/; keep src/ as-is)
       backend/     (from 295A-main/backend/server/)
     web/
       ui/          (from 295A-main/UI/)
     deploy/
       nginx/
         nginx.conf
     docker-compose.yml
     .env.example
     README.md

3) Build a reverse-proxy gateway (Nginx):
   - Route `/api/` to Django backend service (port 8000 inside container).
   - Route `/ai/` to AI FastAPI service (port 8080 inside container).
   - Route `/ai/ws` (websocket) to AI FastAPI with proper Upgrade/Connection headers.
   - Route `/` to the built UI static files (from Vite build output).
   (Make the gateway listen on a single port, e.g., 8085 or 80.)

4) Dockerize all services:
   - Dockerfile for Django backend (gunicorn or uvicorn ASGI ok; simplest: `python manage.py runserver 0.0.0.0:8000` for dev).
   - Dockerfile for AI module (install requirements, run `python -m src.app` OR uvicorn entry if defined).
   - Dockerfile for UI build stage (node build) that outputs static assets into a shared location for Nginx.
   - docker-compose.yml that starts:
     - backend (Django) 
     - ai (FastAPI)
     - nginx (reverse proxy serving UI + routing to backend/ai)

5) Update the UI to talk to the new single-origin routing:
   - Current UI uses axios baseURL default `http://localhost:8000/api`.
   - Change it to default to relative `/api` so it works behind Nginx without CORS.
   - Add a second client for AI endpoints:
     - AI base should be relative `/ai` (e.g., `/ai/api/v1/...` or `/ai/alerts` depending on which endpoints you standardize on).
   - Implement minimal UI wiring:
     - Add a “Live AI” page or dashboard panel that:
       - lists cameras from AI: GET `/ai/cameras` OR `/ai/api/v1/cameras`
       - shows live snapshots: `<img src="/ai/frame/{camera_id}?t=...">` OR `/ai/api/v1/cameras/{camera_id}/snapshot`
       - shows latest alerts: GET `/ai/alerts` or `/ai/api/v1/alerts`
       - optional: websocket subscription to `/ai/ws` for real-time alerts (recommended if already supported)
   - Keep existing pages intact; just add this integration without breaking auth flows.

6) Backend integration (minimal but meaningful):
   Implement a Django endpoint to RECEIVE AI webhooks and store them into existing models:
   - Add POST `/api/ai/webhook/receive/` (no auth or HMAC-auth; choose simplest but document it)
   - When webhook event `alert.created` arrives:
     - map `camera_id` to existing Camera rows (use a simple mapping: Camera.name == camera_id OR add a new field `ai_camera_id` via migration)
     - create/update an Incident row (use status OPEN; close when inactivity occurs if desired)
     - create a Detection row with payload JSON (store entire AI alert payload)
     - set Incident.media_key to the AI evidence URL (e.g., `/ai/evidence/{camera_id}/{filename}`)
   - Optional: add a management command `register_ai_webhook` that calls AI `/webhooks` API to register the Django receiver URL.

7) Provide a working README:
   - `docker compose up --build` instructions
   - required env vars:
     - DJANGO_DEBUG, SECRET_KEY, ALLOWED_HOSTS
     - AI_WEBHOOK_SECRET (optional)
     - AI_BASE_INTERNAL=http://ai:8080 (for backend to register/pull)
     - PUBLIC_BASE_URL=http://localhost:8085 (for composing webhook callback url)
   - how to access:
     - UI: http://localhost:8085/
     - Django API: http://localhost:8085/api/
     - AI API: http://localhost:8085/ai/

8) Acceptance criteria (must pass):
   - One port exposed publicly (via Nginx).
   - UI loads and can login (existing auth works).
   - UI “Live AI” page shows camera list + snapshot + recent alerts.
   - AI websocket (if used) works through Nginx.
   - AI webhook receiver endpoint works and persists at least one incident/detection in Django DB.
   - No hardcoded localhost URLs in frontend—use relative paths or env variables.

NOTES / HINTS:
- FastAPI behind a proxy path prefix may require setting uvicorn `--proxy-headers` and optionally `--root-path /ai` if swagger/docs/assets break under the path. If anything fails, adjust AI startup to include root_path.
- For dev simplicity, use SQLite volume for Django; later can swap to Postgres.
- Avoid duplicating the AI module’s older Django/React folders unless needed; focus on its `src/` FastAPI service.

OUTPUT:
Return the final integrated repo structure with updated configs, docker-compose, nginx config, and key modified files. Provide a concise “How to run” section and a “What changed” section.