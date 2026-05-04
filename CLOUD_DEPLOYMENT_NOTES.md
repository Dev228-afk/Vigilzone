# Cloud Deployment Notes

Use three different address classes in cloud deployments:

- Control plane:
  - `MEDIAMTX_API_URL`
  - Used by backend/reconciler to add, patch, delete, and inspect relay paths.
- Internal ingest plane:
  - `MEDIAMTX_INTERNAL_RTSP_URL`
  - `MEDIAMTX_RTSP_BASE`
  - Used by backend preview workers and AI ingest to consume relay RTSP internally.
- Viewer plane:
  - `MEDIAMTX_EXTERNAL_URL`
  - `VITE_WEBRTC_VIEWER_BASE_URL`
  - `VITE_HLS_VIEWER_BASE_URL`
  - Used by browsers or public clients.

Recommended multi-VM setup:

- Backend VM:
  - `AI_BASE_INTERNAL=http://ai.internal:8080`
  - `MEDIAMTX_API_URL=http://mediamtx.internal:9997`
  - `MEDIAMTX_INTERNAL_RTSP_URL=rtsp://mediamtx.internal:8554`
  - `MEDIAMTX_RTSP_BASE=rtsp://mediamtx.internal:8554`
  - `RELAY_RTSP_HOST=mediamtx.internal`
  - `STRICT_SERVICE_URL_VALIDATION=1`
  - `ALLOW_LOCALHOST_SERVICE_URLS=0`
- AI VM:
  - `BACKEND_BASE_INTERNAL=http://backend.internal:8000`
  - `BACKEND_CONFIG_SYNC_BASE=http://backend.internal:8000/api/ai/internal`
  - `MEDIAMTX_INTERNAL_RTSP_URL=rtsp://mediamtx.internal:8554`
- UI/public edge:
  - `VITE_WEBRTC_VIEWER_BASE_URL=https://streams.example.com`
  - `VITE_HLS_VIEWER_BASE_URL=https://streams.example.com`
  - `VITE_ENABLE_WEBRTC=true` only when the viewer endpoint is intentionally exposed and healthy.

Notes:

- Avoid `localhost` / `127.0.0.1` in multi-VM deployments unless the dependent service is truly on the same host.
- `STRICT_SERVICE_URL_VALIDATION=1` makes Django fail fast when control-plane and ingest URLs still point at localhost.
- Keep browser-facing viewer URLs separate from backend-facing internal URLs.
