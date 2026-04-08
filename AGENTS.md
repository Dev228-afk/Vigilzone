# AGENTS.md

These rules are mandatory for any AI or human agent changing this repository.
If a requested change conflicts with a rule below, stop and surface the tradeoff
before editing production code.

## 1. Preserve working behavior

- Do not rewrite a working flow just to simplify code or make the diff look cleaner.
- Do not replace a real integration with dummy code, demo data, placeholders, or
  stub logic inside a live runtime path.
- If a fallback is truly required, gate it behind explicit config or a feature flag
  and expose that fallback state in diagnostics.

## 2. Realtime incident contract

- The primary incident path is:
  AI `alert.created` -> Redis stream (`AI_INCIDENT_CHANNEL`) -> backend
  `subscribe_incidents` -> `process_alert_event()` -> `NotificationService` ->
  Django Channels/WebSocket -> client without refresh.
- Webhook ingestion is a backup or compatibility path only. Do not make the UI
  depend on manual refresh or polling to receive incident notifications.
- Preserve event idempotency via `IncidentEventReceipt`.
- Transport health is only "ready" when Redis is reachable, the subscriber
  heartbeat is fresh, and the client WebSocket subscription is active.

## 3. Dashboard and camera wall contract

- The dashboard camera list must come from the Django camera or streams registry,
  not from the AI camera list.
- Camera preview must work even when AI runtime is disabled, unsynced, or
  temporarily unavailable.
- Preferred preview order is:
  MediaMTX/WebRTC when healthy -> authenticated MJPEG -> authenticated snapshot.
- Never render protected API image URLs in raw `<img>` tags that bypass auth.
- Stream availability indicators must reflect stream health, not AI status alone.

## 4. Single source of config

- Do not add new hardcoded runtime URLs, ports, tenant ids, camera ids, Redis
  channels, lane lists, or service hosts in application code.
- Backend Redis settings must go through `server.redis_runtime`.
- If code needs AI or MediaMTX base URLs, extend a shared helper or config module
  instead of adding another scattered `os.getenv(...default...)` call.
- Frontend env reads must go through small helper modules under
  `web/ui/client/src/lib/`.
- Hardcoded defaults are allowed only in one config module per service, test
  fixtures, and docs/examples.

## 5. Database efficiency

- Do not add read-path backfills, reconciliation, or repair work to frequently
  polled endpoints.
- Avoid N+1 queries. Use `select_related`, `prefetch_related`, `values`,
  `annotate`, or batching intentionally.
- Avoid JSON-field filters on hot paths unless indexed or unavoidable.
- Any new polling endpoint must stay cheap and the query pattern must be clear in
  code review.
- Notification fan-out writes must be batched or queued when scaling beyond local
  SQLite behavior.

## 6. Memory and runtime efficiency

- Keep only the minimum in-memory frame state needed for streaming.
- Revoke object URLs and dispose timers, intervals, workers, and subscriptions on
  unmount or shutdown.
- Avoid duplicate background caches, duplicate capture threads, and duplicate
  polling loops for the same camera or feed.
- Do not introduce unbounded lists, queues, or per-frame object allocation in hot
  paths unless necessary and justified.

## 7. No dummy or mismatched implementations

- Do not mark a feature complete if it still relies on stub inference,
  placeholder notifications, fake health, or demo data in the real production
  path.
- If a model, lane, or integration is stubbed, label it explicitly in code,
  diagnostics, and UI. Do not hide it behind production wording.
- Keep docs, env examples, compose files, and runtime code aligned. Update all of
  them together when a flow changes.

## 8. Validation required for risky changes

- Changes touching incidents, streaming, auth, tenant routing, Redis, MediaMTX,
  or config must include:
  - a code-path audit of the affected runtime flow
  - at least one automated test, or a short explanation for why the repo cannot
    support one yet
  - manual verification steps in the change summary
- Never merge a change that only works with local hardcoded values.

## 9. When to stop and escalate

- Stop and ask for direction if a change would alter an existing working flow,
  remove a fallback, mutate stored camera ids or stream paths, or introduce
  migration risk.
- Stop if the repo already contains conflicting in-flight edits you do not fully
  understand.

## 10. Definition of done

- No new hardcoded runtime strings were added.
- No dummy code was introduced into live paths.
- Existing successful behavior was preserved.
- Realtime incidents still arrive without refresh.
- Dashboard previews still work independently of AI sync state.
- Query count and memory impact were considered, not ignored.


xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Critical Failures
Worker Exhaustion via Synchronous IPC (Concurrency Vulnerability)

Location: services/backend/api/views.py (sync_to_ai endpoint).

Issue: The backend makes a synchronous HTTP call to the AI service: http_client.post(..., timeout=15). Standard Django WSGI setups (like Gunicorn) typically run 2 to 4 workers per CPU core. If the AI service hangs, and just 4 users click "Sync Camera" at the same time, the entire backend server will freeze for 15 seconds. No other users will be able to log in, view dashboards, or receive API responses.

Infinite Thread Blocking in AI Ingest

Location: services/ai/src/ingest/ffmpeg_reader.py (_read_loop and _connect).

Issue: The AI engine uses cv2.VideoCapture(self.source, cv2.CAP_FFMPEG). OpenCV's FFmpeg backend does not have a native, built-in timeout for network stream drops. If the RTSP camera goes offline abruptly, cap.read() will block the ingest thread indefinitely. The reconnect logic (if not ret) will never trigger because the thread is permanently stuck waiting for a frame.

JSON Type Pollution (Database Efficiency / Migration Killer)

Location: services/backend/api/views.py (notifications_list, _ensure_user_alert_backfill).

Issue: The AI generated the following ORM filter: Q(payload__user_id=request.user.id) | Q(payload__user_id=str(request.user.id)). This proves that across the codebase, user_id is being shoved into the JSON payload as both an integer and a string. This makes it impossible to build a highly efficient GIN/GiST index on that JSON field for future Cloud DB migrations, forcing full table scans on the Alert table.

Architectural Deviations
The "God Object" Anti-Pattern: services/backend/api/views.py is bloated. It handles HTTP routing, JSON serialization, RTSP stream subprocess management, AI microservice HTTP requests, and WebSocket business logic. This violates the Single Responsibility Principle. Complex orchestrations should be moved to a services/ layer.

Refactored Code Blocks
1. Preventing Worker Exhaustion (services/backend/api/views.py)
Fix: Enforce an aggressive timeout for synchronous microservice calls. UI must handle asynchronous status states.

Python
# In sync_to_ai, sync_zones_to_ai, and sync_ai_settings:
# Replace the 10-15 second timeouts with a strict 3-second cap.

        try:
            resp = http_client.post(
                f"{ai_base}/api/v1/cameras/register",
                json=payload, 
                timeout=3.0, # STRICT MAX TIMEOUT. Do not block Django workers!
            )
            # ... existing success logic ...
        except http_client.Timeout:
            # Tell the frontend it's taking a while, let the frontend poll status
            return Response(
                {
                    "error": "AI service is busy or starting up.", 
                    "suggestion": "The request was sent, please refresh in a few moments."
                }, 
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
2. Fixing the OpenCV Infinite Block (services/ai/src/ingest/ffmpeg_reader.py)
Fix: Inject FFmpeg network timeout environment variables directly into the OS environment before OpenCV initializes, forcing the underlying C++ backend to yield if the network drops.

Python
# At the top of services/ai/src/ingest/ffmpeg_reader.py
import os

# Add this to the __init__ method of FFmpegReader:
class FFmpegReader(IngestBackend):
    def __init__(self, camera_id: str, source: str, reconnect_delay: float = 5.0, 
                 width: int = 640, height: int = 480):
        super().__init__(camera_id, source)
        
        # FORCE underlying OpenCV FFmpeg wrappers to drop dead connections
        # 5000000 microseconds = 5 seconds
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
        
        self.reconnect_delay = reconnect_delay
        # ... rest of init
3. Fixing JSON Type Pollution (services/backend/api/views.py)
Fix: Normalize the schema. When writing JSON to the DB, strictly enforce string casting for IDs. Update the read path to only expect strings.

Python
# 1. Write Path: Update _ensure_user_alert_backfill and ANY notification dispatchers
        alerts.append(Alert(
            incident=incident,
            channel="websocket",
            payload={
                # ... other fields
                "user_id": str(user.id), # ALWAYS cast to string for JSON schema consistency
                "username": user.username,
            }
        ))

# 2. Read Path: Update notifications_list and unread_count
    # Remove the OR condition. Enforce strict type matching.
    alerts_qs = Alert.objects.filter(
        incident__in=incidents_qs,
    ).filter(
        Q(payload__user_id=str(request.user.id)) | Q(payload__user_id__isnull=True)
    ).select_related("incident", "incident__camera").order_by("-created_at")

Critical Failures
Hardcoded Django Secret Key (Catastrophic Security Flaw)

Location: services/backend/server/settings.py (Line 16)

Issue: The SECRET_KEY is completely hardcoded into version control as "django-insecure-k8i=...". An AI likely copy-pasted the boilerplate from the django-admin startproject template. If deployed, this allows attackers to forge JWTs, manipulate sessions, and execute Remote Code Execution (RCE) via pickled cookie payloads.

OOM (Out of Memory) Vulnerability in RTSP Probe

Location: services/backend/api/views.py (Line 160, _probe_rtsp)

Issue: The subprocess call for ffprobe uses capture_output=True. If a malicious or corrupted RTSP stream responds with an endless stream of garbage stderr data instead of valid frames, the backend will buffer it all into RAM until the server crashes.

Architectural Deviations
Silent Failures (Anti-Pattern): In services/backend/api/views.py (dashboard_summary), the AI health check is wrapped in a bare except Exception: pass. Masking exceptions makes debugging network segmentation or container orchestration failures nearly impossible. You must log the failure reason.

Token Refresh Race Condition: In web/ui/client/src/lib/api.ts, the Axios response interceptor catches 401 errors and attempts to refresh the token. However, it does not queue concurrent requests. If the frontend fires 3 simultaneous API calls when the token is expired, 3 refresh requests will fire simultaneously, invalidating the previous refresh tokens and causing an infinite loop or unexpected logout.

Refactored Code Blocks
1. Fixing the Security Risk (services/backend/server/settings.py)
Fix: Enforce environment-based secrets. Crash the app on startup if a secret is missing in production.

Python
# Replace Line 15-20 in settings.py
from django.core.exceptions import ImproperlyConfigured

DEBUG = bool(int(os.getenv("DJANGO_DEBUG", "0"))) # Default to 0 (False) for safety

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

if not SECRET_KEY:
    if DEBUG:
        # Fallback ONLY permitted in local development
        SECRET_KEY = "django-insecure-local-dev-key-do-not-use-in-prod"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable is missing. Refusing to start in production.")

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,backend,nginx").split(",")
2. Fixing Silent Failures & Hardcoding (services/backend/api/views.py)
Fix: Catch specific exceptions and log them so DevOps can monitor system health without exposing internals to the user.

Python
# Replace the dashboard_summary AI health check block
    # AI health check (non-blocking, best effort)
    ai_healthy = False
    try:
        import requests as http_client
        from requests.exceptions import RequestException
        
        ai_base = get_ai_base_url() # Utilizing the helper defined in the previous audit
        resp = http_client.get(f"{ai_base}/api/v1/health", timeout=3)
        ai_healthy = resp.status_code == 200
    except RequestException as exc:
        logging.getLogger(__name__).warning("AI Engine health check failed: %s", exc)
        # Continue silently for the user, but now we have an audit trail
3. Fixing the Axios Refresh Race Condition (web/ui/client/src/lib/api.ts)
Fix: Implement a refresh token lock/queue so multiple failed requests wait for a single refresh operation to complete.

TypeScript
// Replace the interceptor in api.ts
let isRefreshing = false;
let failedQueue: Array<{ resolve: (value?: unknown) => void; reject: (reason?: any) => void }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const originalRequest = err.config;

    if (err.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        // If already refreshing, queue the request
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const rt = localStorage.getItem("refreshToken");
        if (!rt) throw new Error("no refresh");

        const { data } = await axios.post(`${API_BASE}/auth/refresh/`, { refresh: rt });

        setAccessToken(data.access);
        originalRequest.headers.Authorization = `Bearer ${data.access}`;
        
        processQueue(null, data.access);
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        setAccessToken(null);
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(err);
  }
);