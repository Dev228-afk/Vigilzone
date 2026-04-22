# MediaMTX Relay Architecture Plan

## Purpose

This document is the updated implementation handoff for keeping MediaMTX in the architecture as the canonical low-latency relay layer.

It is written for an implementation agent that needs enough context to:

- understand the current MediaMTX problem in the latest repo state
- distinguish what has already been built from what is still missing
- complete the runtime cutover without reintroducing split ownership
- preserve low latency while making the system cloud-ready and restart-safe

This is not a tuning-only document. The remaining issue is primarily a control-plane problem, not a codec or buffer problem.

## Executive Summary

The project has progressed since the original version of this plan.

The repo now already contains:

- canonical Postgres models for desired MediaMTX relay state
- canonical Postgres models for observed MediaMTX relay state
- service-layer methods that persist desired relay state and emit outbox events
- a cloud-oriented preview redirect path that can send clients to MediaMTX directly

However, the project has not yet completed the most important part of the relay migration:

1. MediaMTX path provisioning is still primarily imperative and view-driven.
2. Desired relay state is still being mirrored after live MediaMTX changes instead of driving them.
3. Camera save/delete signals still spawn local threads that patch MediaMTX directly.
4. Startup auto-reconcile exists, but it is still a process-local recovery loop, not a first-class reconciler service.
5. Documentation and compose comments still describe MediaMTX as optional or secondary.

The exact architectural problem is no longer "there is no DB model for relay state."

The exact architectural problem now is:

- the control-plane schema exists
- but runtime ownership has not been inverted yet

The mature fix is:

- keep MediaMTX
- make MediaMTX the single steady-state relay owner
- make Postgres the authoritative desired-state source
- move runtime apply/verify/remove logic into a dedicated relay reconciler worker
- make preview and AI consume relay outputs in steady state
- treat startup auto-reconcile and direct HTTP patching as temporary compatibility paths only

## Current Repo State (Latest)

### What Is Already In Place

The latest repo already contains important phase-one groundwork.

#### 1. Canonical relay desired-state model exists

`services/backend/api/models.py` now contains `MediaMTXDesiredPath` with fields for:

- `camera`
- `stream_path`
- `desired_enabled`
- `relay_mode`
- `source_uri`
- `source_kind`
- `transcode_required`
- `preview_consumer_uri`
- `ai_consumer_uri`
- `evidence_consumer_uri`
- `path_generation`
- `last_reconciled_at`
- `drift_detected`
- `last_error`

This is the right shape for authoritative relay state.

#### 2. Canonical observed-state model exists

`services/backend/api/models.py` also contains `MediaMTXObservedPathState` with fields for:

- `desired_path`
- `observed_enabled`
- `observed_source`
- `observed_payload`
- `observed_at`
- `last_error`

This means the repo now has an explicit desired-state versus observed-state split.

#### 3. Service-layer methods already persist relay desired state

`services/backend/api/services/runtime_registration_service.py` already exposes:

- `set_desired_mediamtx_path(...)`
- `mark_observed_mediamtx_path(...)`

`set_desired_mediamtx_path(...)` also emits an outbox event:

- `event_type = "mediamtx.desired_path_set"`

That is an important control-plane building block.

#### 4. Camera create/bootstrap flows already create relay sidecars

The phase-one test suite shows the project already expects camera CRUD to create relay sidecars and related config records:

- `bootstrap_postgres_config`
- camera service CRUD
- API tests asserting `MediaMTXDesiredPath` exists after camera creation

This is strong evidence that Postgres-side ownership is already part of the intended direction.

#### 5. A MediaMTX-based preview redirect path already exists

`services/backend/api/views.py` now contains a cloud-oriented `streams_mjpeg(...)` implementation that:

- validates access
- resolves the camera
- redirects the client to `MEDIAMTX_EXTERNAL_URL/{stream_path}/stream`

That means the repo is no longer purely "Django direct preview only." It now has a real relay-facing preview path, even though the docs are still mixed.

### What Is Still Architecturally Wrong

The runtime write path is still backwards.

#### 1. `_ensure_mediamtx_path(...)` is still the real runtime authority

`services/backend/api/views.py` still provisions MediaMTX directly by:

- probing the MediaMTX API
- patching or adding `/v3/config/paths/...`
- rendering path payloads inline

Only after the live MediaMTX change succeeds does it attempt to persist desired state via `runtime_registration_service.set_desired_mediamtx_path(...)`.

That desired-state write is currently best-effort and wrapped in:

- `except Exception: pass`

This is the core control-plane inversion bug that still remains.

#### 2. Camera signals still patch MediaMTX directly

`services/backend/api/signals.py` still:

- spawns a thread on `Camera` save
- calls `_ensure_mediamtx_path(...)`
- spawns a thread on `Camera` delete
- calls `_remove_mediamtx_path(...)`

This is not cloud-grade orchestration. It is process-local, non-durable, hard to retry, and easy to duplicate across replicas.

#### 3. Startup auto-reconcile exists, but it is still a stopgap

`services/backend/api/apps.py` starts a daemon thread that:

- polls MediaMTX availability
- calls `reconcile_all_cameras_to_mediamtx()` when MediaMTX appears

This is useful as a temporary recovery mechanism, but it is not yet a proper reconciler service because it:

- lives inside web app startup
- is not independently scalable
- is not an explicit worker role
- still reuses imperative provisioning logic from views

#### 4. Manual reconcile still exists in the operational surface

The repo still contains:

- `services/backend/api/management/commands/reconcile_mediamtx.py`
- camera API reconcile endpoints
- bulk replay logic in `reconcile_all_cameras_to_mediamtx()`

That means reconcile has not yet been reduced to a background control-plane responsibility.

#### 5. The docs are now behind the code

At least two documentation surfaces are still mixed or stale:

- `README.md` still says browser preview runs directly from Django and does not require MediaMTX
- `docker-compose.yml` still labels MediaMTX as an optional relay for AI ingest

Those statements no longer match the intended target architecture and partially no longer match the code.

## The Fundamental Problem

The project's MediaMTX problem has changed shape.

### Old problem

Earlier, the project mainly lacked durable relay-state ownership.

### New problem

Now the schema and service layer exist, but the runtime execution path has not been inverted.

The system still behaves like this:

1. camera save or sync path decides to patch MediaMTX now
2. backend writes to MediaMTX runtime API
3. backend then tries to mirror that into Postgres
4. background startup thread may replay all cameras later if drift occurs

That is still imperative patching with a DB sidecar.

The architecture must instead behave like this:

1. camera create/update/delete changes canonical desired state in Postgres
2. outbox event records the desired-state change durably
3. relay reconciler consumes desired-state changes
4. reconciler applies deterministic MediaMTX config changes
5. reconciler verifies actual runtime state
6. reconciler persists observed state and drift

Until that inversion happens, MediaMTX will remain operationally fragile even though the correct models already exist.

## Non-Negotiable Design Decisions

1. MediaMTX stays in the architecture.
2. MediaMTX becomes the single steady-state relay owner for camera sessions.
3. Postgres is the authoritative source of desired relay state.
4. `MediaMTXDesiredPath` becomes the primary driver of runtime configuration, not a best-effort mirror.
5. `MediaMTXObservedPathState` becomes the canonical record of actual applied state and drift.
6. A dedicated reconciler worker owns apply, verify, repair, and remove operations.
7. Backend web workers must not be responsible for durable relay orchestration.
8. Preview and AI both consume relay outputs in steady state.
9. Low latency is achieved by single-session ownership plus pass-through/remux defaults, not by bypassing the relay.

## What Low Latency Means In This Architecture

Low latency does not mean "skip MediaMTX."

Low latency means:

- one upstream session per camera
- no duplicate camera pulls from preview and AI separately
- pass-through or remux as the default
- transcode only when source compatibility requires it
- minimal buffering at relay and consumer boundaries
- stable consumer URIs so reconnect behavior is predictable

### Relay-mode policy

The control plane should treat these as explicit policy choices:

- `relay_only`
- `remux`
- `transcode`

Use them like this:

- `relay_only` for RTSP sources already consumable by target clients
- `remux` when protocol/container normalization is needed without re-encode
- `transcode` only for MJPEG, snapshot, or other incompatible sources

## Updated Target Architecture

### Logical flow

```text
Camera / NVR
  -> MediaMTX relay (single upstream owner)
     -> preview output
     -> AI inference output
     -> evidence/original output

Backend control plane
  -> Postgres desired state
  -> outbox events
  -> relay reconciler worker
  -> observed-state persistence

AI
  -> consumes relay URI / relay identity

Frontend preview
  -> consumes relay output directly
```

### Control plane

Postgres owns:

- camera identity
- stable `stream_path`
- relay desired state
- relay mode
- source URI and source kind
- path generation
- intended preview and AI consumer identities
- observed relay state
- last reconcile result
- drift and error state

### Data plane

MediaMTX owns:

- upstream camera session
- runtime path state
- downstream relay outputs

MediaMTX does not own canonical truth.

## Current Code Inventory That Matters

### Canonical state and service layer

- `services/backend/api/models.py`
  - `MediaMTXDesiredPath`
  - `MediaMTXObservedPathState`
- `services/backend/api/services/runtime_registration_service.py`
  - `set_desired_mediamtx_path(...)`
  - `mark_observed_mediamtx_path(...)`
- `services/backend/api/test_phase1_config_migration.py`
  - phase-one validation that sidecars and outbox flows exist

### Still-imperative runtime path

- `services/backend/api/views.py`
  - `_ensure_mediamtx_path(...)`
  - `_remove_mediamtx_path(...)`
  - `reconcile_all_cameras_to_mediamtx()`
  - `sync_to_ai`
  - `reconcile_mediamtx`

### Stopgap auto-recovery hooks

- `services/backend/api/apps.py`
  - startup daemon thread polling MediaMTX and replaying full reconcile
- `services/backend/api/signals.py`
  - camera save/delete side effects that patch MediaMTX directly

### Consumer-facing relay path

- `services/backend/api/views.py`
  - `streams_mjpeg(...)` redirecting to `MEDIAMTX_EXTERNAL_URL`

### Documentation drift to clean up later

- `README.md`
- `docker-compose.yml`

## Exact Problem Statement For The Agent

The repo is not missing relay models anymore.

The repo is missing a complete cutover from:

- imperative relay provisioning in request paths, signals, and startup threads

to:

- durable desired-state changes
- dedicated relay reconciler worker
- explicit observed-state writeback

That is the fundamental task.

## Implementation Plan

## Phase 1: Complete Control-Plane Inversion

### Goal

Make Postgres desired state primary and MediaMTX runtime apply secondary.

### Required changes

1. Move all camera-driven relay mutations behind service-layer methods.
2. Ensure camera create/update/delete first update canonical DB state.
3. Make desired-state writes mandatory, not best-effort.
4. Remove silent swallow patterns around relay desired-state persistence.
5. Treat `_ensure_mediamtx_path(...)` as a compatibility shim until reconciler cutover is complete.

### Specific repo actions

1. Refactor camera create/update/delete flows so they:
   - persist `Camera`
   - persist `MediaMTXDesiredPath`
   - emit outbox event
   - do not directly own long-running MediaMTX repair logic

2. Refactor `_ensure_mediamtx_path(...)` so it becomes:
   - a renderer/apply helper used by the reconciler
   - not the first-class control-plane entrypoint

3. Remove `except Exception: pass` around `set_desired_mediamtx_path(...)`.

4. Ensure `MediaMTXDesiredPath.path_generation` changes on meaningful desired-state mutation.

5. Ensure delete/disable semantics are represented in desired state before runtime deletion occurs.

### Exit criteria

- DB desired state is always written before or as part of any relay mutation intent
- no request-path logic relies on "patch MediaMTX first, record desired state later"
- desired-state mutation is durable and observable

## Phase 2: Introduce A Real Relay Reconciler Worker

### Goal

Replace process-local reconcile behavior with a dedicated worker role.

### What the reconciler must do

1. Read desired relay state from Postgres.
2. Determine whether the target path is missing, stale, or needs deletion.
3. Render deterministic MediaMTX config payloads.
4. Apply add/patch/delete via MediaMTX API.
5. Read back runtime state from MediaMTX.
6. Persist `MediaMTXObservedPathState`.
7. Update `last_reconciled_at`, `drift_detected`, and `last_error`.
8. Retry failures with bounded backoff.

### What the reconciler must replace

The reconciler should eventually replace:

- startup auto-reconcile thread in `apps.py`
- camera save/delete background thread behavior in `signals.py`
- manual reliance on `reconcile_mediamtx` as normal operations

### Deployment model

Run as its own worker/service in cloud.

Acceptable short-term packaging:

- Django management command wrapper over service-layer reconciler logic

Target-state packaging:

- dedicated worker process/container

### Exit criteria

- reconcile no longer depends on Django web process startup
- relay repair survives web pod restarts cleanly
- observed state is actually updated by the worker

## Phase 3: Finish Consumer Cutover

### Goal

Make relay outputs the steady-state access path for both preview and AI.

### Preview path

Preview should use stable relay output identities derived from canonical state.

The existing `streams_mjpeg(...)` redirect is a good direction, but it needs to be treated as part of the standard architecture, not as a cloud-only special case hidden behind stale docs.

### AI path

AI registration and runtime should consume relay identities derived from canonical DB state:

- stable `stream_path`
- stable relay consumer URI
- source-specific policy such as transcode versus relay-only

`sync_to_ai` should evolve toward a registration step that reads canonical relay state rather than reprovisioning the relay inline.

### Exit criteria

- preview steady state uses MediaMTX outputs
- AI steady state uses MediaMTX outputs
- camera session ownership is no longer split between direct source pulls and relay pulls

## Phase 4: Remove Transitional Imperative Paths

### Goal

Remove the old operational crutches once the reconciler is proven.

### Remove or downgrade

- camera save/delete direct relay patching from signals
- startup auto-reconcile thread in `apps.py`
- normal-runbook dependence on `reconcile_mediamtx`
- inline relay provisioning inside `sync_to_ai`

### Keep only as break-glass or migration tools

- manual reconcile command
- diagnostic probe endpoints

### Exit criteria

- manual reconcile is not part of normal operations
- web tier no longer owns durable relay orchestration
- docs and compose describe MediaMTX as canonical relay, not optional sidecar

## Verification Plan

## Functional verification

1. Create camera:
   - `Camera` row exists
   - `MediaMTXDesiredPath` row exists
   - outbox event exists
   - reconciler creates path in MediaMTX
   - observed state is written

2. Update camera source or relay mode:
   - desired path generation increments
   - reconciler patches MediaMTX
   - observed state reflects new runtime config

3. Disable or delete camera:
   - desired state reflects disable/delete intent
   - reconciler removes or disables MediaMTX path
   - observed state and error fields update correctly

4. Restart MediaMTX:
   - reconciler detects missing runtime paths
   - paths are rebuilt from Postgres without operator action

5. Restart backend web process:
   - relay state remains correct because worker owns reconciliation
   - no hidden dependency on `apps.py` startup loop

## Low-latency verification

Measure and compare:

- preview latency before and after cutover
- AI ingest latency before and after cutover
- camera reconnect time
- duplicate upstream session count
- transcode versus relay-only behavior by source type

The success condition is not merely "latency stayed acceptable."

The success condition is:

- acceptable latency
- no duplicate camera pulls
- stable restarts
- no manual reconcile in normal operations

## Failure-mode verification

Test these explicitly:

1. MediaMTX unavailable during desired-state change
2. MediaMTX restart while cameras remain active
3. backend web pod restart
4. relay reconciler restart
5. transient MediaMTX API failure
6. duplicate worker instances

Expected behavior:

- desired state remains durable
- reconciler retries safely
- observed state records failures
- system converges without manual repair

## Rollout Strategy

### Step 1

Keep current imperative compatibility paths while building the reconciler, but make Postgres desired-state persistence authoritative.

### Step 2

Run reconciler in shadow mode:

- compute and verify
- update observed state
- compare with current imperative behavior

### Step 3

Switch runtime apply ownership to the reconciler.

### Step 4

Disable signal-driven and startup-thread-driven patching.

### Step 5

Clean docs, compose comments, and operator runbooks.

## Agent Guidance

When working on this plan, the agent should assume:

- the schema groundwork already exists
- the biggest remaining task is runtime control-plane inversion
- request handlers and signals should not become the durable orchestrator
- MediaMTX remains the relay and should be optimized for low latency, not bypassed

The agent should not spend time redesigning away the current models unless there is a correctness bug. The right move is to complete the migration, not restart the architecture from scratch.

## Final Architectural Statement

The latest repo no longer has a "missing relay schema" problem.

It now has a "relay schema exists, but runtime ownership still lives in imperative web-process code" problem.

The exact fix is to finish the cutover:

- Postgres desired state first
- reconciler applies and verifies
- MediaMTX owns the session
- preview and AI consume the relay
- observed state records reality
- manual reconcile leaves the normal runbook
