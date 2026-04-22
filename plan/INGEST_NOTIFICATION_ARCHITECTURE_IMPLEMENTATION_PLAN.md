# Ingest, Routing, and Notification Architecture Implementation Plan

## Purpose

This document is the implementation handoff for the three agreed plans:

1. Stabilize the current stack without assuming JetStream or a proper Postgres-centered architecture already exists.
2. Introduce canonical data ownership and event foundations.
3. Move to the cloud-ready target architecture.

It is written so an implementation agent can start with accurate context, avoid rediscovering already-known system behavior, and spend tokens on execution rather than re-analysis.

## How To Use This Document

- If you are implementing phase 1, read `Current-State Context`, `Known Hazards`, `Canonical Contracts`, `Plan 1`, and `Verification Matrix`.
- If you are implementing phase 2, read phase 1 first because phase 2 assumes the event envelope and Redis routing projection already exist.
- If you are implementing phase 3, treat phases 1 and 2 as mandatory migration steps, not optional ideas.
- Do not start by redesigning everything. The system currently has real code paths, drift, and operational pain that must be stabilized before extraction or cloud migration.

## Executive Summary

The current system has two intertwined problems:

1. The video ingest plane is inconsistent.
   - MediaMTX is provisioned imperatively at runtime.
   - Django preview can open camera sources directly.
   - AI ingest can also read via MediaMTX loopback.
   - Runtime state is split across backend database state, MediaMTX runtime state, and AI-side runtime JSON.

2. The incident fan-out path is expensive and tightly coupled.
   - Alerts flow from AI to backend via Redis Streams today.
   - Backend ingest resolves camera and tenant context in Django.
   - Notification fan-out queries memberships, user preferences, unread counts, and channels directly in the hot path.
   - WebSocket push, alert creation, and email dispatch are coupled to the same backend-side notification logic.

The target design is:

- `Postgres` as the canonical source of truth for routing and policy.
- `Redis` as derived routing and camera-context state.
- `JetStream` as the durable event backbone.
- `AI` events carrying trusted `tenant_id` and `community_id` context from backend-owned camera registration state.
- Notification fan-out using Redis route objects, not runtime DB joins.
- A single ingest owner per camera session, with preview, inference, and evidence paths separated.

The migration path matters because the current system does not yet have the architecture to cleanly introduce JetStream and Postgres as first-class components. That means phase 1 must improve correctness and reduce cost using the existing backend and Redis stack before phase 2 introduces canonical data/event patterns.

## Current-State Context

### What Is True Today

- AI publishes incident events to Redis Streams.
- Backend runs a long-lived Redis stream subscriber and passes events into backend ingest logic.
- Backend notification fan-out currently lives inside the Django backend and pushes frontend updates via Django Channels WebSockets.
- MediaMTX exists as an optional relay for AI ingest, but Django browser preview can bypass it and read sources directly.
- Some runtime camera state is persisted in AI-side JSON, while MediaMTX relay state is provisioned dynamically and can drift across restarts.

### Current Request Drivers

This plan is optimizing for the following explicit goals:

- Stop out-of-memory behavior and startup drift in the ingest path.
- Eliminate or sharply reduce hot-path DB reads during alert fan-out.
- Lower future cloud cost.
- Preserve correctness and tenant/community isolation.
- Create a migration path to a scalable architecture without requiring a big-bang rewrite.

### Known Current Components

- Backend incident ingest:
  - `services/backend/ai_integration/incident_ingest.py`
  - `services/backend/ai_integration/management/commands/subscribe_incidents.py`
  - `services/backend/ai_integration/redis_queue.py`
- Backend notification logic:
  - `services/backend/api/notification_service.py`
  - `services/backend/api/consumers.py`
- Backend MediaMTX and sync logic:
  - `services/backend/api/views.py`
  - `services/backend/api/stream_workers.py`
- AI service registration and runtime:
  - `services/ai/src/api/server.py`
  - `services/ai/src/app.py`
  - `services/ai/configs/models.yaml`
  - `services/ai/configs/cameras.yaml`
- System wiring:
  - `docker-compose.yml`
  - `DESIGN.md`
  - `README.md`

### Current Live Code Path Map

#### Incident Path Today

The effective live path today is:

1. AI publishes incident events to Redis Streams.
2. Backend subscriber consumes those events.
3. Backend incident ingest normalizes the event and persists incident-related state.
4. Backend queues notification dispatch on commit.
5. Backend notification service performs recipient resolution, alert creation, unread count work, WebSocket fan-out, and optional email dispatch.

This means the current hot path still mixes:

- incident normalization
- business resolution
- fan-out decisioning
- delivery execution
- frontend push side effects

#### Notification Path Today

Current notification behavior is backend-centric:

- channel configuration is checked in backend code
- memberships and preferences are read from the backend data model
- per-user alerts are created in the backend
- unread counts are computed in backend logic
- frontend push is done through Django Channels groups

This is exactly why reducing DB reads requires projection and worker separation, not just adding one more field to AI payloads.

#### Ingest Path Today

The ingest plane is split:

- browser preview can use direct camera access through Django workers
- AI ingest can use MediaMTX-backed paths
- MediaMTX paths are provisioned dynamically
- AI runtime registration persists some state in runtime JSON

This means there is no single declarative owner of camera session state yet.

#### OOM Risk Shape Today

The most likely OOM drivers are:

- too many concurrently loaded or runnable AI lanes
- GPU inflight concurrency higher than the hardware budget can safely support
- queue depth allowing burst accumulation instead of bounded shedding
- frame-store and evidence buffering retaining more data than the hot path can safely carry
- duplicate ingest paths causing more decode and buffering work than expected

This is why phase 1 treats memory and concurrency as a control-plane problem, not only a resolution problem.

## Known Hazards And Do-Not-Rediscover Facts

An implementation agent should not spend time rediscovering the following:

1. MediaMTX state drift is real.
   - Backend provisions paths imperatively through runtime API calls.
   - Manual reconciliation exists today.
   - Relay state is not treated as fully declarative deployment state.

2. Duplicate ingest paths already exist.
   - Django preview can open cameras directly.
   - AI ingest can still route through MediaMTX.
   - This creates multiple sessions and operational ambiguity.

3. The out-of-memory issue is not only about 480p.
   - GPU model residency, lane concurrency, queue depth, evidence buffering, and multiple frame copies are likely the larger issue.

4. Current notification fan-out is DB-heavy.
   - Membership lookup, preference checks, alert row creation, unread count queries, and channel checks all happen close to incident delivery time.

5. Redis Streams already exist and are the current event backbone.
   - JetStream is a target-state replacement or addition, not something the current codebase already uses correctly.

6. AI runtime registration is not fully idempotent.
   - The backend and AI service do not yet behave like a single declarative control plane.

7. There are known correctness bugs in current ingest control code.
   - MediaMTX reconciliation and sync code need audit and repair as part of phase 1 stabilization.
   - AI re-registration logic can trigger unnecessary restarts because compared fields are not consistently represented.

## Architecture Principles

1. One source of truth per concern.
   - Current release: backend persistence layer owns canonical business data.
   - Target state: Postgres owns canonical business data.

2. Redis is always derived state.
   - Redis may be authoritative for hot-path reads, but never for canonical truth.

3. The hot incident path must be cheap.
   - No repeated multi-table joins or repeated per-user unread count queries during normal fan-out.

4. AI events carry stable routing context.
   - `tenant_id` and `community_id` are attached from trusted backend registration state, not arbitrary client input.

5. Notification decisioning and notification execution must separate over time.
   - Short term: separate modules/workers inside the backend.
   - Long term: separate services.

6. Single ingest owner.
   - The system must eventually ensure one upstream camera session per camera under normal operation.

7. Backpressure must be explicit.
   - Bounded queues, bounded buffers, bounded concurrency, and graceful dropping or deferral under load.

8. Migration beats replacement.
   - Prefer dual-write, dual-read, shadow comparison, and feature flags over big-bang swaps.

## Non-Goals

- Phase 1 is not a full microservice decomposition.
- Phase 1 is not a full cloud migration.
- Phase 1 is not a full JetStream rollout.
- Phase 2 is not the point where every runtime service must already be extracted.
- Phase 3 should not reintroduce direct DB fan-out logic in new services.

## Domain Naming Guidance

Current code clearly uses `tenant_id` in backend notification paths. Product discussion also uses `community_id`. Until the domain model is frozen:

- Carry both `tenant_id` and `community_id` in event envelopes.
- Treat `tenant_id` as the current isolation boundary needed by backend code.
- Treat `community_id` as the business grouping required for fan-out policies.
- Do not assume they are interchangeable unless the data model explicitly guarantees it.

## Canonical Contracts To Introduce Early

### 1. Backend To AI Camera Registration Contract

The backend-owned camera registration contract should include at least:

```json
{
  "camera_id": "cam_42",
  "camera_name": "North Gate",
  "rtsp_url": "rtsp://...",
  "ingest_backend": "opencv",
  "sample_hz": 2.0,
  "tenant_id": "t1",
  "community_id": "c7",
  "source_type": "rtsp",
  "stream_path": "north-gate",
  "policy_version": 3
}
```

Rules:

- `tenant_id` and `community_id` must come from trusted backend data.
- `policy_version` should increment when routing-relevant camera assignment changes.
- AI should persist only runtime-operational state, not become the source of truth for ownership.

### 2. AI Incident Event Envelope

This envelope should exist before phase 2 begins, even if it is first carried over Redis Streams instead of JetStream:

```json
{
  "event_id": "uuid",
  "event_type": "incident.detected.v1",
  "tenant_id": "t1",
  "community_id": "c7",
  "camera_id": "cam_42",
  "camera_name": "North Gate",
  "stream_path": "north-gate",
  "source_type": "rtsp",
  "incident_type": "intrusion",
  "severity": "high",
  "confidence": 0.92,
  "ts_utc": "2026-04-15T19:17:12Z",
  "policy_version": 3,
  "evidence": {
    "thumbnail_uri": null,
    "clip_uri": null
  },
  "trace": {
    "producer": "ai-service",
    "schema_version": 1
  }
}
```

Rules:

- `event_id` is required for idempotency.
- `tenant_id`, `community_id`, and `policy_version` are required for cheap routing.
- Do not put dynamic recipient lists into this payload.
- The event can contain evidence metadata, but not full recipient resolution.

### 3. Redis Camera Context Projection

Recommended key:

`cameractx:{camera_id}`

Recommended value:

```json
{
  "tenant_id": "t1",
  "community_id": "c7",
  "camera_name": "North Gate",
  "stream_path": "north-gate",
  "policy_version": 3,
  "updated_at": "2026-04-15T19:17:12Z"
}
```

Purpose:

- Fast validation and enrichment.
- Protection against stale or malformed AI events.
- Enables low-cost consistency checks without hitting the database.

### 4. Redis Route Projection

Recommended initial key:

`route:{tenant_id}:{community_id}:{incident_type}:{severity}`

Recommended value:

```json
{
  "email": ["user_1", "user_7"],
  "push": ["user_1", "user_3", "user_7"],
  "sms": ["user_7"],
  "version": 18,
  "generated_at": "2026-04-15T19:17:12Z",
  "policy_version": 3
}
```

Rules:

- This is a derived projection.
- It must be rebuilt from canonical data, not manually edited.
- It should be small and final enough that fan-out requires one fetch, not a series of secondary joins.

### 5. Route Key Cardinality Guardrail

If the combination space of `tenant_id`, `community_id`, `incident_type`, and `severity` grows too large:

- Keep a simple fully materialized route object in phase 1 and phase 2.
- Introduce layered projections only when route cardinality becomes a real operational issue.
- Do not prematurely optimize into an unreadable projection system.

## Plan 1: Stabilize Current System Without Assuming JetStream/Postgres

### Objective

Stabilize ingest and fan-out using the current backend and Redis environment, while reducing hot-path DB work and removing manual reconcile dependence.

### Why Plan 1 Comes First

The current system is already operational enough to expose real pain:

- restart drift
- MediaMTX reconcile dependence
- duplicate ingest paths
- hot-path notification DB calls
- memory pressure and GPU overcommit

Jumping straight to a new architecture without stabilizing those failure modes will make later migration slower and harder to validate.

### Scope

In scope:

- define the canonical incident envelope
- push trusted business context into AI events
- add Redis route projection
- move notification fan-out off the immediate ingest transaction path
- stabilize current ingest control paths
- reduce OOM risk with bounded concurrency and buffering

Out of scope:

- JetStream rollout
- dedicated notification microservice
- full Postgres-centered canonical data redesign
- full edge/cloud split

### Plan 1 Workstreams

#### Workstream 1.1: Freeze Event And Registration Contracts

Tasks:

- Add `tenant_id`, `community_id`, `camera_name`, `stream_path`, and `policy_version` to the backend-to-AI registration contract.
- Add the same trusted business context to AI incident payloads.
- Ensure backend ingest treats these fields as first-class and logs when they are missing.
- Make contract validation strict enough to detect malformed producers, but tolerant enough to support a staged rollout.

Implementation notes:

- Backend should remain the authority for `tenant_id` and `community_id`.
- AI should echo these fields from registration state, not derive them from client-side input.
- Use feature flags if necessary to allow old and new payloads during rollout.

Likely files:

- `services/backend/api/views.py`
- `services/backend/ai_integration/incident_ingest.py`
- `services/backend/ai_integration/redis_queue.py`
- `services/ai/src/api/server.py`
- `services/ai/src/app.py`

Verification:

- Unit tests for payload validation and backward-compatible parsing.
- Integration test that registers a camera, emits an alert, and confirms the received event includes trusted business context.
- Negative test where AI sends an event without `tenant_id` or `community_id`; backend should flag it and follow the configured fallback path.

#### Workstream 1.2: Introduce Redis Routing Projection Without Requiring Postgres Yet

Tasks:

- Build a route projection generator inside the backend using the current canonical membership and preference data source.
- Materialize route objects in Redis keyed by `tenant_id`, `community_id`, `incident_type`, and `severity`.
- Add cache refresh hooks after membership changes, preference changes, role changes, channel enablement changes, and camera reassignment.
- Add a fallback path:
  - normal path: Redis route lookup only
  - cache miss path: recompute from backend data source, repopulate Redis, then continue
- Add metrics for cache hit, miss, rebuild latency, and projection staleness.

Implementation notes:

- Do not put recipient lists into AI events.
- The backend may still be the only place that knows how to derive recipients in plan 1.
- Prefer one fully materialized route object per route combination first.
- Keep route objects versioned.

Likely files:

- `services/backend/api/notification_service.py`
- `services/backend/ai_integration/incident_ingest.py`
- `services/backend/ai_integration/redis_queue.py`
- backend models, signals, or service modules responsible for memberships/preferences

Verification:

- Unit tests that compare route projection output against the current DB-driven notification logic.
- Dual-path test mode where Redis route recipients are compared against current live DB-derived recipients before sending.
- Load test with many alerts for one tenant/community and verify Redis hit rate stays high.
- Confirm DB query count drops sharply for repeated alerts after cache warm-up.

#### Workstream 1.3: Decouple Notification Execution From Incident Ingest

Tasks:

- Keep incident creation/idempotency in backend ingest.
- Stop doing full notification resolution inline with incident persistence.
- Introduce an internal dispatch step:
  - ingest persists incident
  - ingest enqueues or schedules notification dispatch
  - notification worker resolves route from Redis and sends
- Keep the notification worker inside the backend codebase for now.
- Preserve current frontend WebSocket behavior, but have it emit from the worker path instead of from transaction-adjacent business logic.

Implementation notes:

- This is a modular-monolith step, not yet a service split.
- Move toward a clean boundary:
  - incident ingest owns incident normalization and persistence
  - notification module owns recipient resolution and delivery execution

Likely files:

- `services/backend/ai_integration/incident_ingest.py`
- `services/backend/api/notification_service.py`
- `services/backend/api/consumers.py`
- any backend task runner or management command used for async processing

Verification:

- Integration test that an incident persists even if the notification worker is unavailable.
- Retry test where notification dispatch fails once, then succeeds without duplicate incident creation.
- Idempotency test ensuring the same event does not create duplicate alerts or duplicate external sends.

#### Workstream 1.4: Stabilize MediaMTX And Ingest Reconciliation

Tasks:

- Audit and fix current MediaMTX path provisioning and reconciliation code.
- Remove manual operator dependence on a reconcile command for normal startup.
- Make startup idempotent:
  - backend desired camera state is replayed automatically
  - AI registration state is replayed automatically
  - MediaMTX path state is reconciled automatically
- Decide the temporary steady-state ingest owner for plan 1.

Recommended plan 1 choice:

- Keep MediaMTX only for the paths that still require it.
- Do not expand MediaMTX usage while duplicate ingest paths still exist.
- Make the current runtime consistent before choosing the final single-ingest-owner model.

Known current issues to repair in this workstream:

- MediaMTX path creation/sync return semantics need correction.
- Reconciliation paths must be idempotent and testable.
- Backend restart must not require human replay to restore path state.

Likely files:

- `services/backend/api/views.py`
- `docker-compose.yml`
- `README.md`
- `DESIGN.md`

Verification:

- Cold-start test: stop all relevant containers, start them, verify cameras reconcile without manual intervention.
- Partial restart test: restart backend only, verify AI and MediaMTX state are restored.
- Partial restart test: restart MediaMTX only, verify relay paths are rebuilt.
- Multi-camera test with mixed RTSP and MJPEG/snapshot sources.

#### Workstream 1.5: Bound Memory, Queueing, And GPU Concurrency

Tasks:

- Lower aggressive defaults for GPU inflight work and queue sizes.
- Audit lane enablement per camera and disable nonessential lanes by default.
- Ensure only one canonical frame copy is retained per stage when possible.
- Cap evidence ring buffers and evidence export concurrency.
- Add explicit drop/defer policies when inference backlog exceeds budget.

Implementation notes:

- 480p alone is not the root fix.
- The first priority is memory plateau and predictable degradation under load.
- Any high-cost verification models should trigger conditionally, not always-on.

Likely files:

- `services/ai/configs/models.yaml`
- `services/ai/configs/cameras.yaml`
- `services/ai/src/app.py`
- evidence, frame-store, and lane modules in `services/ai/src`

Verification:

- 24-hour soak test with target cameras at 480p and at least one higher resolution profile.
- Measure RSS, GPU memory, frame drop rate, queue depth, and incident latency over time.
- Validate stable memory plateau instead of monotonic growth.
- Confirm overload behavior is degraded throughput, not OOM.

#### Workstream 1.6: Add Observability Before More Architecture

Tasks:

- Add per-stage metrics for:
  - Redis route cache hit/miss
  - projection rebuild latency
  - incident ingest latency
  - notification dispatch latency
  - notification retries/failures by channel
  - queue depth
  - MediaMTX reconciliation success/failure
  - per-camera reconnect count
  - AI queue depth, GPU inflight count, dropped frames, and model latency
- Add correlation IDs:
  - reuse `event_id`
  - propagate to incident, notification, and delivery logs

Verification:

- Smoke test that a single incident can be traced end-to-end by `event_id`.
- Dashboard check that all high-value counters move during test alerts.

### Plan 1 Rollout Strategy

Recommended order:

1. Contract additions and parsing support.
2. Observability additions.
3. Redis route projection in shadow mode.
4. Notification worker path behind a feature flag.
5. MediaMTX/startup stabilization.
6. Memory and concurrency hardening.
7. Switch hot-path fan-out to Redis route lookup.

### Plan 1 Acceptance Criteria

- Alerts normally fan out without DB membership/preference resolution in the hot path.
- Restart no longer requires manual MediaMTX reconciliation.
- AI events include trusted `tenant_id` and `community_id`.
- Notification execution is decoupled from direct incident ingest.
- Memory plateaus under sustained load.
- All critical flows are observable with correlation IDs and metrics.

### Plan 1 Rollback Strategy

- Feature flag Redis route lookup and keep DB-derived fallback available.
- Feature flag asynchronous notification worker path.
- Keep old payload parsing during transition.
- If route projection fails, fail open to the current authoritative backend-derived logic until phase 2 is complete.

## Plan 2: Introduce Canonical Data And Event Foundations

### Objective

Introduce a proper canonical data model and event-driven projection layer so Redis routing state becomes fully derived from source-of-truth data instead of being rebuilt ad hoc inside request paths.

### Important Constraint

The current system does not yet have the architecture to properly involve JetStream and Postgres. Therefore phase 2 is the transition phase that creates those foundations. It is not safe to assume those systems already exist as first-class citizens in the current codebase.

### Scope

In scope:

- define canonical business data ownership
- move or harden canonical routing data into Postgres
- introduce transactional outbox
- introduce routing projector
- project route objects and camera context into Redis
- prepare transport abstraction so Redis Streams can later be swapped for JetStream

Out of scope:

- final service extraction for every component
- final cloud/edge deployment topology

### Plan 2 Workstreams

#### Workstream 2.1: Make Postgres The Canonical Store For Routing-Relevant Business Data

Tasks:

- Move or harden these entities into Postgres-backed canonical ownership:
  - users
  - communities
  - memberships
  - roles
  - cameras
  - camera-to-community mapping
  - notification preferences
  - routing policies
- Ensure each entity has clear ownership and versioning.
- Define which updates are routing-affecting and therefore must emit change events.

Important nuance:

- If the backend already uses Postgres underneath, the real task is not just "switch database."
- The real task is to make Postgres-backed canonical business data explicit, normalized, and the only source of truth for routing policy.

Suggested canonical metadata additions:

- `policy_version`
- `updated_at`
- `updated_by`
- soft-delete or active status flags where needed

Verification:

- Schema tests and migrations.
- Data correctness checks after migration or normalization.
- Rebuild Redis routing projections from Postgres and compare results to phase 1 projections.

#### Workstream 2.2: Introduce A Transactional Outbox

Tasks:

- Create an outbox table for routing-related and incident-related change publication.
- Write outbox records in the same transaction as the canonical data update.
- Introduce a publisher worker that reads outbox rows and publishes change events.
- Ensure publisher is idempotent and marks outbox delivery state.

Suggested outbox columns:

- `id`
- `event_id`
- `aggregate_type`
- `aggregate_id`
- `event_type`
- `payload`
- `created_at`
- `published_at`
- `attempt_count`
- `last_error`

Why this matters:

- Without the outbox pattern, Postgres and the event bus will drift under failure.
- This drift would directly corrupt routing projections and notification correctness.

Verification:

- Transactional test that data update and outbox row commit together.
- Failure injection where publisher crashes after reading but before ack; replay must be safe.
- Idempotency test where duplicate outbox publication does not corrupt Redis projections.

#### Workstream 2.3: Introduce The Routing Projector

Tasks:

- Build a dedicated routing projector worker.
- Consume routing change events from the current event transport.
- Rebuild only affected Redis keys, not the entire projection store.
- Maintain camera context projection and route projection separately.
- Track projector lag, last processed event, rebuild counts, and failures.

Recommended projections:

- `cameractx:{camera_id}`
- `route:{tenant_id}:{community_id}:{incident_type}:{severity}`
- reverse index keys to support targeted invalidation and reconciliation

Recommended additional keys:

- `routeidx:community:{community_id}` -> set of route keys
- `routeidx:camera:{camera_id}` -> set of keys affected by camera reassignment

Verification:

- Targeted update tests:
  - membership change updates only affected routes
  - preference change updates only affected routes
  - camera reassignment updates camera context and route associations
- Replay tests from event history.
- Full rebuild job that regenerates all projections and confirms no diff.

#### Workstream 2.4: Refactor Incident Ingest Around Business Envelope First

Tasks:

- Update incident ingest to trust the event envelope first and use DB fallback second.
- Resolve `camera_id`, `tenant_id`, and `community_id` from the event and Redis camera context before touching Postgres.
- Treat DB resolution as a fallback, audit, or repair path rather than the normal path.
- Preserve incident idempotency and durable storage.

Implementation notes:

- Incident ingest still needs durable incident/audit persistence.
- What must disappear is repetitive business-context lookup on every alert when the event already carries valid trusted context.

Verification:

- Contract test where event envelope contains complete trusted context and no camera DB lookup is needed.
- Fallback test where event is missing `community_id` and the system recovers via DB lookup plus cache repair.
- Latency comparison before and after envelope-first ingest.

#### Workstream 2.5: Split Decisioning From Execution More Cleanly

Tasks:

- Make notification decisioning depend on Postgres truth plus Redis projections.
- Make notification execution consume only already-decided recipient/channel information.
- Keep service boundaries internal if full extraction is not yet justified, but enforce code boundaries.

Suggested modules:

- `routing_policy_service`
- `routing_projector`
- `notification_dispatcher`
- `delivery_audit_writer`

Verification:

- Unit tests for route build logic independent of channel sending logic.
- Integration tests that swap channel providers without touching policy computation.

### Event Backbone Strategy In Phase 2

Recommended progression:

1. Keep Redis Streams as the live transport if needed.
2. Introduce a transport abstraction for:
   - publish incident event
   - publish routing change event
   - consume routing change event
   - consume incident event
3. Ensure no business logic depends on Redis-specific message semantics.
4. Only after this abstraction is stable should JetStream be introduced in phase 3.

### Plan 2 Acceptance Criteria

- Postgres is the explicit canonical source of truth for routing-relevant data.
- All routing-affecting changes emit transactional outbox events.
- Redis routing state is projector-built from canonical data.
- Incident ingest normally resolves routing context from event plus Redis, not DB.
- Notification decisioning and execution have clean boundaries.

### Plan 2 Rollback Strategy

- Keep Redis Streams transport active while transport abstraction is introduced.
- Maintain rebuild tooling to repopulate Redis from Postgres truth.
- Keep DB fallback paths in incident ingest until projector correctness is proven over soak/load tests.

## Plan 3: Cloud-Ready Target Architecture

### Objective

Move from a stabilized modular monolith with projections into a scalable, fault-tolerant, cost-aware architecture that can run in the cloud without reintroducing hot-path DB fan-out or duplicate ingest ownership.

### Target Architecture Overview

Core principles:

- Postgres = source of truth
- Redis = derived routing and camera context
- JetStream = durable event backbone
- Notification service = independent horizontal scaling unit
- Ingest gateway = single owner of camera sessions
- Object storage = evidence durability

### Target Logical Components

1. Edge/site ingest gateway
   - MediaMTX or GStreamer-based
   - single owner of camera sessions
   - emits preview, inference, and evidence-friendly outputs

2. AI detection workers
   - consume dedicated low-resolution inference streams or sampled frames
   - emit incident events with trusted business context

3. Postgres control plane
   - canonical cameras, communities, memberships, preferences, policies, audit

4. Routing projector
   - consumes change events
   - updates Redis projections

5. Notification service
   - consumes incident events
   - fetches Redis route
   - dispatches email/push/SMS
   - emits delivery results

6. Backend/API service
   - manages user-facing CRUD, ack flows, admin operations, and policy updates

7. Object storage and evidence service
   - durable clip and thumbnail storage
   - metadata references in Postgres

### Why Notification Service Extraction Happens Here, Not Earlier

Keep notification logic in the backend until at least these are true:

- route projection is stable and trusted
- transport abstraction exists
- async dispatch behavior is already proven
- retries and idempotency are well-defined

Extract when one or more of these become true:

- alert burstiness affects API latency
- independent scaling is required
- channel integrations become operationally heavy
- retry logic and provider rate limits need isolation

### Plan 3 Workstreams

#### Workstream 3.1: Introduce JetStream As The Event Backbone

Tasks:

- Create event subjects for:
  - routing changes
  - incident detected
  - incident normalized
  - notification dispatch requested
  - notification sent
  - notification failed
  - incident acknowledged
- Configure durable consumers for projector, notification service, and audit processors.
- Define replay and retention rules by event type.

Recommended subject examples:

- `routing.change.v1`
- `incident.detected.v1`
- `incident.normalized.v1`
- `notification.dispatch.requested.v1`
- `notification.sent.v1`
- `notification.failed.v1`

Verification:

- Consumer restart replay test.
- At-least-once delivery test with idempotent consumers.
- Backpressure test under alert bursts.

#### Workstream 3.2: Extract Notification Service

Tasks:

- Move notification dispatch logic into its own service.
- Keep policy resolution dependent on Redis route projections and canonical data versions.
- Emit delivery result events rather than directly mutating every state synchronously in the caller.
- Scale service independently from backend API and AI workers.

Implementation notes:

- The notification service should not become a second source of truth.
- It consumes already-computed route objects and delivery requests.
- Provider-specific integrations should remain behind channel adapters.

Verification:

- Dual-run backend worker and notification service in shadow mode, compare deliveries.
- Channel-provider failure test with retry/backoff and dead-letter handling.
- Scale test with bursty multi-tenant traffic.

#### Workstream 3.3: Finalize Single Ingest Owner And Stream Tiers

Tasks:

- Ensure each camera has one upstream session under normal operation.
- Separate outputs:
  - preview output for UI
  - low-resolution inference stream for AI
  - original/high-quality path for evidence
- Move ingest as close to the cameras or site network as practical.
- Prevent UI preview and AI inference from opening separate direct camera sessions.

Why this matters for cloud cost:

- Repeated direct pulls from cloud services to on-prem cameras are fragile and expensive.
- Edge/site relay reduces WAN fragility and central compute waste.

Verification:

- Session count audit per camera.
- WAN interruption test.
- Preview and inference continuity test during service restarts.

#### Workstream 3.4: Move Evidence To Durable Object Storage

Tasks:

- Store clips and thumbnails in object storage.
- Keep only metadata references in canonical data store.
- Treat local disk as transient cache only.

Verification:

- Evidence retrieval test after worker restart.
- Storage lifecycle and TTL validation.

#### Workstream 3.5: Cost And Capacity Controls

Tasks:

- Separate autoscaling pools for:
  - API/backend
  - notification service
  - CPU workers
  - GPU inference workers
- Add per-tenant or per-community quotas if needed.
- Budget expensive verification models behind incident triggers or policy rules.
- Track cost drivers:
  - GPU time
  - evidence storage
  - notification provider usage
  - Redis memory
  - event bus throughput

Verification:

- Cost model review before full cloud rollout.
- Burst test with projected tenant growth.
- Monthly storage growth simulation.

### Plan 3 Acceptance Criteria

- JetStream is the durable backbone for change and incident events.
- Notification service scales independently and does not require DB joins on the hot path.
- Redis route and camera context projections are authoritative for hot-path reads.
- Ingest ownership is singular and stream tiers are separated.
- Evidence is durably stored outside local worker disks.
- The platform can tolerate bursts, restarts, and partial dependency outages without manual recovery.

## Redis Routing Resolution Design

### Basic Runtime Resolution

Normal hot path:

1. Notification worker receives incident event.
2. Extract `tenant_id`, `community_id`, `incident_type`, `severity`, and `policy_version`.
3. Optional validation against `cameractx:{camera_id}`.
4. Fetch route key from Redis.
5. Send notifications to the listed recipients/channels.
6. Emit delivery results asynchronously.

### Cache Miss Strategy

Phase 1 and phase 2:

- On route miss:
  - increment miss metric
  - derive recipients from canonical backend data or Postgres
  - repopulate Redis
  - continue delivery

Phase 3 target:

- Route misses should be rare enough to treat as projection failure.
- Prefer one of:
  - synchronous fallback with repair for critical incidents only
  - route-repair event plus retry queue for standard incidents

### Versioning Strategy

Use both:

- route object `version`
- business `policy_version`

Purpose:

- `version` tracks projection rebuild versioning.
- `policy_version` tracks routing-policy generation and allows stale event detection.

### Reconciliation Jobs

Add two periodic jobs:

1. Full route rebuild:
   - rebuild all route objects from canonical truth
   - compare counts and checksums

2. Camera context rebuild:
   - rebuild `cameractx` projections
   - detect orphaned or stale camera mappings

These jobs are required even after the projector exists.

## Verification Matrix

| Area | What To Verify | Method | Pass Condition |
| --- | --- | --- | --- |
| Event contract | AI emits trusted business context | integration tests, payload snapshots | all required fields present and validated |
| Idempotency | duplicate events do not duplicate incidents or sends | replay same `event_id` | one incident, one delivery set |
| Redis routing | route projection matches canonical policy | dual-path compare, snapshot tests | no recipient drift |
| Cache fallback | route miss does not drop alert | fault injection | alert still delivered and cache repaired |
| Restart behavior | no manual MediaMTX reconcile | cold restart and partial restart tests | ingest restores automatically |
| Memory safety | no OOM under sustained load | soak tests | stable plateau in RSS and GPU memory |
| Backpressure | overload degrades gracefully | load test | drops/defers within policy, no crash |
| Tenant isolation | no cross-tenant delivery | integration and security tests | recipients belong only to intended scope |
| Transport replay | consumers handle duplicates/restarts | consumer restart tests | safe replay, no corruption |
| Notification retries | transient provider failure is retried safely | provider failure simulation | at-least-once delivery without duplicate audit corruption |
| Cost reduction | hot-path DB queries shrink materially | query count and latency baseline | repeated alerts rely on Redis path |

## Implementation Order By Team Or Agent

### If One Agent Is Implementing Phase 1

Recommended order:

1. Add event envelope fields and tolerant parsing.
2. Add metrics and correlation IDs.
3. Build route projection and shadow comparison path.
4. Introduce async notification worker path.
5. Stabilize MediaMTX/startup reconcile behavior.
6. Tighten AI memory and concurrency controls.
7. Enable Redis route hot path by feature flag.

### If Work Is Split Across Multiple Agents

Split by responsibility, not by arbitrary file slices:

- Agent A: incident envelope and backend ingest contract
- Agent B: Redis route projection and notification worker
- Agent C: MediaMTX and startup reconciliation
- Agent D: AI memory/concurrency hardening and observability

Avoid overlap on:

- shared incident schema
- Redis key naming
- idempotency contract
- feature flag names

## Agent Reading Order To Save Tokens

Read these first for phase 1:

1. `DESIGN.md`
2. `services/backend/ai_integration/incident_ingest.py`
3. `services/backend/api/notification_service.py`
4. `services/backend/ai_integration/management/commands/subscribe_incidents.py`
5. `services/backend/ai_integration/redis_queue.py`
6. `services/backend/api/views.py`
7. `services/backend/api/stream_workers.py`
8. `services/ai/src/api/server.py`
9. `services/ai/src/app.py`
10. `services/ai/configs/models.yaml`
11. `services/ai/configs/cameras.yaml`
12. `docker-compose.yml`

Read these next for phase 2:

1. backend models and migrations related to users, memberships, channels, cameras, and incidents
2. any existing task runner, async worker, or management command framework
3. current database settings and deployment manifests

Read these next for phase 3:

1. deployment manifests
2. container orchestration configuration
3. infra docs for object storage, queueing, and observability

## Known Traps

1. Do not stuff dynamic recipient lists into AI payloads.
   - Stable routing context belongs in the event.
   - Dynamic recipient resolution belongs in Redis projection.

2. Do not make Redis the source of truth.
   - Redis is for hot-path reads and fast projections only.

3. Do not extract a notification microservice before route projection and async dispatch are stable.

4. Do not keep multiple camera session owners long term.

5. Do not remove DB fallback paths until the projector and projection rebuild jobs are proven in real soak tests.

6. Do not assume 480p solves the ingest OOM problem by itself.

## Final Deliverables By Phase

### End Of Phase 1

- stable startup without manual MediaMTX reconcile
- trusted business context in AI events
- Redis route projection in production hot path
- async notification execution inside the backend
- bounded memory and queue behavior

### End Of Phase 2

- Postgres-backed canonical routing data model
- transactional outbox
- routing projector
- Redis route and camera context projections built from canonical truth
- event- and projection-aware incident ingest

### End Of Phase 3

- JetStream backbone
- separate notification service
- single ingest owner with stream tiers
- durable evidence storage
- independently scalable and cost-aware cloud-ready system

## Definition Of Success

This effort is successful when:

- alerts do not require repeated DB joins to decide recipients
- restart and reconcile behavior is automatic
- routing correctness remains anchored in canonical business data
- ingest no longer burns memory unpredictably
- notification fan-out scales independently from API and AI work
- the cloud migration becomes mostly infrastructure work instead of another application rewrite
