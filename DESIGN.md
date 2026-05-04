I reviewed the repo shape and current worktree. The MediaMTX stamp-convergence fix is already partly/mostly implemented, so this plan treats relay stability as the baseline and focuses on broader optimization without sacrificing immediate add/update/delete reaction.

**Core Principle**
Optimize for “fast reaction, quiet steady state.” Camera changes should wake the right worker immediately, but unchanged systems should not poll, reload, re-query, or re-encode unnecessarily.

**P0: Correctness Before Speed**
- Tighten MediaMTX stamping in [relay_reconciler.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/services/relay_reconciler.py:335). It stamps `last_applied_payload_hash` even if verification returns `None`; only stamp after runtime GET confirms no drift.
- Guard Postgres advisory locks in [relay_reconciler.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/services/relay_reconciler.py:120). Local SQLite/dev will fail on `pg_try_advisory_lock`; use Postgres lock only when `connection.vendor == "postgresql"`.
- Expand MediaMTX payload hashing in [mediamtx_helpers.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/services/mediamtx_helpers.py:21). Current hash excludes emitted fields like `runOnDemandStartTimeout`, `runOnDemandCloseAfter`, `sourceOnDemandStartTimeout`, `sourceOnDemandCloseAfter`, and `sourceFingerprint`.
- Prefer event-driven reconciler wakeups over longer polling. Keep immediate camera reaction by emitting an outbox/Redis “relay path changed” event on camera create/update/delete, then reconcile that path first. Keep periodic audit at 300s for safety.

**P1: Backend/API Hot Paths**
- Cache tenant membership per request. [views.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/views.py:69) does repeated membership lookups via `get_active_tenant`, `assert_member`, and `get_membership`. Add middleware/request attributes so each request resolves tenant and membership once.
- Collapse dashboard DB queries in [dashboard_summary](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/views.py:853). Replace five incident `.count()` calls with one `aggregate(Count(..., filter=Q(...)))`. Move the 3s AI health request at line 922 to cached/stale health so dashboard polling cannot block.
- Move notification backfill out of read path. [notifications_list](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/views.py:2045) calls `_ensure_user_alert_backfill` every request and scans up to 300 incidents. Convert this to a background/watermarked job.
- Normalize alerts. [Alert](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/models.py:286) filters through `incident__tenant` and JSON `payload__user_id`. Add `tenant` FK, enforce `(incident,user,channel)` uniqueness, and index `(tenant,user,delivered_at,created_at)`.
- Add missing incident/audit indexes. [Incident](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/models.py:247) needs indexes for dashboard and active-window ingest: `(tenant, started_at)`, `(tenant, status, started_at)`, `(tenant, severity, started_at)`, `(camera, type, status, started_at)`. [AuditLog](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/models.py:300) needs `(tenant, created_at)`.
- Fix serializer N+1s. [TenantSerializer.get_role](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/serializers.py:17) ignores the user and queries memberships per tenant. [KnownEntitySerializer.get_cameras](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/serializers.py:246) needs `prefetch_related`.
- Optimize incident ingest camera resolution. [incident_ingest.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/ai_integration/incident_ingest.py:154) does sequential lookups by AI ID/name/stream path. Use one scoped `Q(...)` query plus a small TTL cache, invalidated by camera config events.
- Remove per-user unread count query loops in [notification_service.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/notification_service.py:83). Replace with grouped aggregate over all affected users.
- Entity processing: [entity_processing_service.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/services/entity_processing_service.py:221) creates embeddings one row at a time, and line 345 reads each asset fully into memory. Use `bulk_create` and streamed multipart file handles. Also fix the non-interpolated error string at line 368.

**P1: AI/Media Runtime**
- Avoid full-frame copies on every tick. [opencv_reader.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/ingest/opencv_reader.py:64) and [ffmpeg_reader.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/ingest/ffmpeg_reader.py:66) return `.copy()`. Move to double-buffer or immutable frame references, copying only when a lane mutates.
- Replace 1ms busy sleeps in [app.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/app.py:491). Use `reader.wait_for_frame(timeout=next_lane_due)` so idle cameras do not burn CPU.
- Reduce evidence encoding load. [ringbuffer.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/evidence/ringbuffer.py:44) JPEG-encodes every frame at quality 85. Make evidence FPS/quality configurable, default lower on cloud, and add `get_frames_after()` to avoid repeated full-buffer list copies at line 82.
- Replace full-sort identity search. [matcher.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/identity/matcher.py:63) sorts every embedding. Use FAISS/top-K or `np.argpartition`, then aggregate top entity candidates.
- Build camera processor maps. [server.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/api/server.py:332) and [app.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/app.py:830) scan arrays by camera id. Maintain `dict[camera_id, processor]`.

**P1: Frontend**
- Dashboard currently polls four endpoints: [Dashboard.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/pages/Dashboard.tsx:63), :89, :100, :110. Combine stable data into `/dashboard/summary/`, use SSE invalidation for incidents/health, and pause polling when tab is hidden.
- [LiveAI.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/pages/LiveAI.tsx:210) fires many requests every 10s. Split into React Query hooks with separate stale times, build `streamsByAiId` once instead of `streams.find` at line 318, and partition entities once instead of repeated `.filter()` at lines 643 and 656.
- Deduplicate signed stream tokens. [AuthedMjpeg.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/components/AuthedMjpeg.tsx:81), [CanvasStream.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/components/CanvasStream.tsx:93), and [SnapshotStream.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/components/SnapshotStream.tsx:120) each fetch/refresh tokens. Add shared token cache keyed by camera id and pause when offscreen.
- Lower or avoid snapshot polling. [CanvasStream.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/components/CanvasStream.tsx:25) defaults to 40 FPS despite comment saying 10. On low-spec cloud, prefer WebRTC/HLS/MJPEG relay, or cap snapshot polling to 2-5 FPS.
- Query keys need tenant awareness. [AuthProvider.tsx](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/auth/AuthProvider.tsx:141) invalidates all queries on tenant switch, but many query keys omit tenant. Include `tenantId` in tenant-scoped keys to avoid stale cross-tenant flashes.

**P2: Security/API Hygiene**
- Stop logging tokenized URLs. [useNotifications.ts](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/web/ui/client/src/hooks/useNotifications.ts:306) logs `sseUrl`, which includes a token. Also avoid SSE tokens in query strings if headers already work.
- Upload endpoints read whole files in memory at [server.py](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/ai/src/api/server.py:621), :916, :952, :1207. Add size limits, streaming temp files, image dimension validation, and proper HTTP errors.
- Restrict [debug_system](C:/Users/devan/OneDrive/Desktop/yolov12-cls/vigilzone-monolith/services/backend/api/views.py:2409) to owner/admin and ensure frontend debug polling is disabled outside debug pages.
- Centralize frontend API calls. `useNotifications.ts` uses raw `fetch` while most code uses axios. One client should handle tenant header, refresh, error envelope, and retries.

**Execution Order**
1. Add measurements: Django query count middleware in dev, endpoint p95 logs, AI loop FPS/CPU counters, browser network waterfall baseline.
2. Land P0 MediaMTX correctness fixes and event-driven reconciler wakeup.
3. Add DB indexes and notification normalization migrations.
4. Fix dashboard/notification backend query patterns.
5. Optimize AI frame/ringbuffer/matcher memory pressure.
6. Refactor frontend polling and stream token dedupe.
7. Verify with: camera add/update/delete reaction under one poll or event wakeup, zero MediaMTX reloads in steady state, dashboard p95 under 200ms excluding cold AI, and stable CPU/memory with 3-5 cameras.