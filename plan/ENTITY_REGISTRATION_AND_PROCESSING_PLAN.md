# Entity Registration And Processing Plan

## Purpose

This document is the repo-specific implementation plan for fixing the entity registration, vector processing, storage, access, and AI-consumption workflow.

It is written for this codebase, not as a generic identity-recognition design.

The target workflow is:

`user_register_entity -> backend validates + stores request -> backend/worker generates vectors -> Postgres pgvector stores canonical embeddings -> AI consumes only approved enabled embeddings for matching`

The plan also covers:

- secure role-based access for create/update/delete
- per-entity and per-camera/tenant detection toggles
- cloud-native processing
- robust storage and retrieval
- minimizing runtime errors and split-truth behavior

## Executive Summary

The current repo already has a useful foundation:

- `KnownEntity` is the canonical entity row
- `KnownEntityEmbedding` already stores embeddings in Postgres using pgvector
- backend exposes canonical identity snapshot endpoints
- AI has an in-memory identity cache backed by backend snapshot fetches

However, the current registration flow is still wrong for the long-term target:

1. Backend creates entity metadata.
2. Backend forwards images to AI enrollment endpoints.
3. AI computes embeddings.
4. AI syncs vectors back into backend/Postgres.

That means vector generation ownership is currently split across services.

The mature fix is:

- backend remains the source of truth for entity lifecycle
- backend-owned async processing generates embeddings
- Postgres remains canonical for entity metadata and vectors
- AI becomes a read-only consumer of canonical, enabled, approved embeddings
- entity detection is controlled explicitly through policy/toggle fields instead of implied by existence alone

## Repo-Specific Current State

### What Already Exists

Current backend models already include:

- `KnownEntity`
- `KnownEntityEmbedding`

Current backend API already includes:

- `KnownEntityViewSet` for CRUD
- internal snapshot endpoint for AI:
  - `GET /api/ai/internal/identity/snapshot/`
- internal sync endpoint used by AI:
  - `POST /api/ai/internal/identity/sync/`

Current AI code already includes:

- `EntityStore` which loads canonical entity + embedding snapshots from backend
- `IdentityMatcher` which uses in-memory vectors
- `entity_identity` lane
- aggregator logic that uses identity for suppression/severity decisions

### Important Current Problems

1. Registration ownership is split.
   - backend creates entity record
   - AI performs enrollment and vector generation
   - AI syncs vectors back into backend

2. RBAC is too broad for entity mutation.
   - current entity create/update/delete flows use `assert_non_viewer`
   - that allows `member` to mutate enrolled identities
   - for security-sensitive biometric/pet identity enrollment, create/delete should be `owner/admin` only

3. The pipeline is sync-ish and brittle.
   - user request can trigger file forwarding and AI dependency directly
   - failures can leave partially enrolled state

4. There is no explicit entity lifecycle state machine.
   - there is not yet a first-class `PENDING -> PROCESSING -> READY -> FAILED -> DISABLED -> DELETED` model

5. Detection enablement is not modeled strongly enough.
   - existence of an entity is too close to "detect this entity"
   - there should be an explicit opt-in toggle

6. Raw enrollment assets are not treated as hardened cloud-native assets yet.
   - current AI flow writes enrollment images locally
   - long-term this should move to private object storage with signed access only

## Architectural Decision

### Canonical Ownership

The authoritative owner must be:

- backend control plane for entity lifecycle and policy
- Postgres for entity metadata and embeddings

AI must not be the owner of:

- entity create/delete truth
- embedding persistence truth
- enrollment asset truth

AI should become:

- a snapshot consumer
- a matcher
- a producer of sightings and identity evidence

### Keep Existing Pgvector Table

Important repo-specific note:

This repo already has `KnownEntityEmbedding` with `VectorField`.

That means the safest plan is **not** to replace this with a single vector column on `KnownEntity`.

Why:

- one entity can have multiple embeddings
- different modalities already exist (`face`, `pet_clip`)
- future re-embedding and quality filtering need separate rows
- audit/provenance is cleaner with a side table

So the recommended fix is:

- keep `KnownEntityEmbedding`
- extend it
- do not collapse identity vectors into a single per-entity column unless there is a very strong reason

## Target Workflow

### Registration Flow

1. User calls `register entity` in backend.
2. Backend authenticates user and resolves tenant.
3. Backend enforces role policy:
   - `owner/admin` can create
   - `member/viewer` cannot create
4. Backend validates:
   - category
   - allowed cameras
   - image count/type/size
   - consent flags if applicable
5. Backend creates `KnownEntity` in `PENDING` state.
6. Backend stores uploaded images in private object storage or private managed storage.
7. Backend enqueues embedding job.
8. Worker generates embeddings.
9. Worker stores `KnownEntityEmbedding` rows in Postgres.
10. Worker marks entity:
   - `READY` if minimum quality/embedding requirements are met
   - `FAILED` otherwise
11. Backend emits outbox/config-change event.
12. AI refreshes identity cache using backend snapshot or versioned delta logic.

### Detection Runtime Flow

1. AI startup or refresh loads only entities that are:
   - active
   - `READY`
   - `detection_enabled = true`
   - allowed for the relevant tenant/camera
2. If tenant/camera `entity_detection_enabled = false`, the identity lane is skipped entirely.
3. Matcher uses in-memory vectors only.
4. AI does not query Postgres per frame.
5. AI emits sightings/evidence only.
6. Backend persists last seen / last camera / audit state.

### Delete Flow

1. `owner/admin` requests delete.
2. Backend soft-deletes entity immediately:
   - `status = DELETED`
   - `detection_enabled = false`
3. Backend emits refresh event so AI unloads vectors quickly.
4. Background purge later removes embeddings/assets as per retention policy.

## Data Model Plan

### Existing Table: `KnownEntity`

Keep this as the canonical entity row.

Add fields like:

- `status`
  - `PENDING`
  - `PROCESSING`
  - `READY`
  - `FAILED`
  - `DISABLED`
  - `DELETED`
- `detection_enabled` boolean
- `created_by`
- `updated_by`
- `deleted_at`
- `processing_error`
- `processing_started_at`
- `processing_completed_at`
- `ready_at`
- `consent_status` or `consent_recorded_at` if required for person entities
- `embedding_version`
- `entity_detection_notes` optional

Recommended behavior:

- default `detection_enabled = false` on create
- only allow `detection_enabled = true` when `status = READY`

### Existing Table: `KnownEntityEmbedding`

Keep this table as the canonical pgvector storage.

Add fields like:

- `is_active`
- `quality_score`
- `embedding_model`
- `embedding_version`
- `source_image_uri`
- `source_checksum`
- `generated_by`
- `deleted_at`

Recommended behavior:

- allow multiple embeddings per entity/modality
- mark stale embeddings inactive on re-enrollment rather than hard-deleting immediately

### New Table: `KnownEntityAsset`

Add a dedicated asset table for enrollment images instead of relying on local AI files.

Suggested fields:

- `entity`
- `tenant`
- `asset_type`
  - `enrollment_image`
  - `thumbnail`
- `storage_uri`
- `checksum`
- `content_type`
- `width`
- `height`
- `captured_at` or `uploaded_at`
- `uploaded_by`
- `is_active`
- `metadata`

Purpose:

- private storage reference
- signed access
- auditability
- cloud portability

### Detection Toggle Model

Add explicit toggles at more than one level.

Per entity:

- `KnownEntity.detection_enabled`

Per camera or AI profile:

- `entity_detection_enabled`

Per tenant runtime/policy if needed:

- `identity_runtime_enabled`

Effective enablement should be:

`tenant_identity_enabled AND camera_identity_enabled AND entity.detection_enabled AND entity.status == READY`

## Security Plan

### Role-Based Access

Use stricter RBAC than current `assert_non_viewer`.

Recommended policy:

- `owner/admin`
  - create entity
  - update entity metadata
  - upload/re-upload enrollment assets
  - enable/disable detection
  - delete entity
- `member`
  - read entity list/details if permitted by tenant policy
  - no create/delete by default
- `viewer`
  - read-only or no entity access depending product policy

For this repo, the safest first step is:

- entity create/update/delete/enable-disable => `owner/admin`

### Tenant Isolation

Every entity query must remain tenant-scoped.

This includes:

- registration
- vector writes
- snapshot generation
- sighting updates
- delete/purge

### API Hardening

Protect:

- internal identity snapshot endpoint
- internal identity change endpoints or future refresh endpoints

Current internal auth already exists and should remain required.

Strengthen with:

- service-to-service auth only
- request signing or token validation
- rate limiting on public entity registration endpoints

### Sensitive Data Handling

Do not expose:

- raw vectors
- object storage URIs directly unless signed
- raw enrollment assets publicly

Use:

- private object storage
- short-lived signed URLs
- audit logging for entity create/delete/download actions

### Deletion Policy

Use soft delete first for safety and audit.

Then purge asynchronously based on retention policy.

## Cloud-Native Processing Design

### Processing Pattern

Do not compute embeddings inline in the HTTP request path as the long-term steady state.

Use:

- API request
- durable DB row
- durable storage for images
- async processing job
- status update
- event-driven AI refresh

Why:

- retries
- idempotency
- horizontal scale
- failure recovery
- shorter API latency

### Recommended Job States

Entity states:

- `PENDING`
- `PROCESSING`
- `READY`
- `FAILED`
- `DISABLED`
- `DELETED`

Worker behavior:

- only one active processing job per entity/version
- retries on transient failures
- hard fail on invalid images/embedding quality issues

### Storage Pattern

Store:

- entity metadata in Postgres
- embeddings in Postgres pgvector
- raw images and thumbnails in private object storage

Do not rely on:

- AI local filesystem as canonical image store
- AI local directory as authoritative enrollment asset location

## Detailed Implementation Plan

### Phase 1: Fix Authorization And Entity State Modeling

Goal:

- secure the workflow before changing processing ownership

Tasks:

- change entity create/update/delete/enable-disable permissions from `assert_non_viewer` to `owner/admin`
- add explicit entity lifecycle fields to `KnownEntity`
- add `detection_enabled` to `KnownEntity`
- add audit logging for entity create/update/delete/toggle actions

Repo areas:

- `services/backend/api/models.py`
- `services/backend/api/views.py`
- `services/backend/api/serializers.py`

Verification:

- `member` cannot create or delete entities
- `viewer` cannot mutate entities
- `owner/admin` can create and disable detection

### Phase 2: Move Registration To Backend-Owned Processing

Goal:

- stop making AI the enrollment owner

Tasks:

- backend accepts entity registration request and uploads
- backend stores entity as `PENDING`
- backend stores assets in managed private storage
- backend enqueues embedding generation job
- backend worker generates embeddings and writes `KnownEntityEmbedding`
- backend marks entity `READY` or `FAILED`

Important design note:

- AI enrollment endpoints should become temporary compatibility paths or admin/migration utilities, not the canonical registration flow

Repo areas:

- `services/backend/api/views.py`
- `services/backend/api/models.py`
- new backend worker/service modules for entity processing
- storage integration modules

Verification:

- entity registration succeeds even if AI is down
- failed embedding generation does not create half-ready active entities
- embeddings exist in Postgres without AI having to sync them back

### Phase 3: Make AI A Read-Only Consumer

Goal:

- AI loads canonical vectors but does not own them

Tasks:

- keep `ai_internal_identity_snapshot` as the canonical fetch path, but filter it to active/ready/enabled entities only
- deprecate AI-driven `add_embedding` and `upsert_entity` as the normal enrollment path
- keep AI sighting updates if useful, but treat them as observation-only
- update AI cache reload logic to react to entity change events or version changes

Repo areas:

- `services/backend/ai_integration/views.py`
- `services/ai/src/identity/store.py`
- `services/ai/src/api/server.py`

Verification:

- AI starts and reloads from backend snapshot only
- AI no longer needs to create canonical vectors itself in normal operation
- cache reload unloads disabled/deleted entities

### Phase 4: Add Detection Toggles And Runtime Gating

Goal:

- make entity matching cost and behavior explicitly controllable

Tasks:

- add `KnownEntity.detection_enabled`
- add camera or runtime-level `entity_detection_enabled`
- ensure backend snapshot filters by effective enablement
- ensure AI aggregator/lane skips identity work when disabled

Effective logic:

- if no enabled entities apply to the camera, skip identity lane initialization or matching for that camera
- if tenant/camera identity is off, AI does not load or use those vectors for runtime matching

Repo areas:

- `services/backend/api/models.py`
- `services/backend/ai_integration/views.py`
- `services/ai/src/logic/aggregator.py`
- `services/ai/src/lanes/entity_identity.py`

Verification:

- disabling entity detection removes match attempts
- enabling detection reloads the right entity set only

### Phase 5: Harden Asset Storage And Retrieval

Goal:

- make enrollment assets secure and cloud-ready

Tasks:

- move enrollment images from AI-local storage to private managed storage
- add entity asset metadata table
- serve thumbnails/assets through signed or proxied access
- keep public APIs free from raw storage internals

Repo areas:

- backend storage integration
- entity serializers/views
- AI enrollment/image endpoints if they remain for compatibility

Verification:

- no canonical enrollment asset depends on AI local disk
- assets remain accessible after AI restart

### Phase 6: Optimize Snapshot And Matching

Goal:

- reduce cloud/runtime cost while preserving accuracy

Tasks:

- snapshot only active/ready/enabled entities
- support camera-scoped filtering
- keep only active embeddings in memory
- add entity/embedding versioning for efficient reload
- later add delta-sync if needed, but full snapshot with versioning is enough first

Verification:

- AI memory and reload times scale with active entity set, not total historical rows
- camera-scoped detection reduces unnecessary matching work

## API And Service Contract Plan

### Public Backend API

Recommended API behavior:

- `POST /entities`
  - creates entity in `PENDING`
  - uploads assets
  - returns processing status
- `PATCH /entities/{id}`
  - updates metadata
  - allows toggle of `detection_enabled`
- `DELETE /entities/{id}`
  - soft delete
- optional:
  - `POST /entities/{id}/reenroll`
  - `POST /entities/{id}/disable`
  - `POST /entities/{id}/enable`

### Internal Backend API For AI

Keep or evolve:

- `GET /api/ai/internal/identity/snapshot/`

Recommended response additions:

- `status`
- `detection_enabled`
- `embedding_version`
- `allowed_camera_ids`

Recommended filtering:

- only return entities that are matchable in runtime:
  - `READY`
  - `detection_enabled = true`
  - not deleted
  - active embeddings only

### AI Internal Behavior

AI should:

- fetch snapshot
- build in-memory modality indices
- match only against active vectors
- reload on startup and on change notifications

AI should not:

- own canonical enrollment writes
- persist canonical entity config locally
- accept unauthenticated entity mutation

## Storage And Access Design

### Entity Metadata Access

Source of truth:

- Postgres `KnownEntity`

Read path:

- backend APIs
- internal AI snapshot

### Vector Access

Source of truth:

- Postgres `KnownEntityEmbedding`

Read path:

- backend snapshot builder
- AI in-memory matcher cache

Do not expose vectors in user-facing APIs.

### Image Access

Source of truth:

- object storage plus `KnownEntityAsset`

Read path:

- backend signed URLs or proxy endpoints

## Robustness And Error-Handling Rules

1. Registration must be idempotent at the job level.
2. Duplicate uploads should not create duplicate active entity rows accidentally.
3. Failed embedding jobs must mark the entity `FAILED` with error details.
4. Enabling detection must be rejected unless entity is `READY`.
5. Delete must disable detection immediately before background purge.
6. AI snapshot fetch failure should keep last known in-memory cache temporarily, but never create private truth.
7. Backend remains authoritative for whether an entity exists and is usable.

## Performance And Cost Optimizations

1. Keep multiple embeddings per entity, but only load active embeddings.
2. Use camera scoping already present on `KnownEntity.cameras`.
3. Add per-entity `detection_enabled` to avoid matching everyone by default.
4. Add tenant/camera `entity_detection_enabled` to disable the lane entirely where unused.
5. Use async workers for embedding generation to avoid blocking API and to scale separately.
6. Avoid per-frame backend or Postgres lookups in AI.

## Repo Files Most Likely To Change

Backend:

- `services/backend/api/models.py`
- `services/backend/api/serializers.py`
- `services/backend/api/views.py`
- `services/backend/ai_integration/views.py`
- new backend service/worker modules for entity processing

AI:

- `services/ai/src/identity/store.py`
- `services/ai/src/api/server.py`
- `services/ai/src/logic/aggregator.py`
- `services/ai/src/lanes/entity_identity.py`

Infra:

- worker/deployment config
- storage config
- queue config if added

## Verification Matrix

| Area | What to verify | Pass condition |
| --- | --- | --- |
| RBAC | only `owner/admin` can create/delete/enable/disable entities | `member/viewer` mutation requests are rejected |
| Tenant isolation | cross-tenant entity access is blocked | no foreign-tenant entity mutation or reads |
| Registration | entity enters `PENDING/PROCESSING/READY` correctly | no partial active entity on failure |
| Vector storage | embeddings are written to pgvector rows | active vectors exist in `KnownEntityEmbedding` |
| Toggle behavior | disabled entities are not matched | snapshot excludes disabled/non-ready rows |
| AI runtime | AI uses backend snapshot and in-memory cache only | no per-frame DB access |
| Delete behavior | entity unloads quickly and purges safely later | detection disabled immediately, data purge async |
| Asset security | raw images are not public | access requires backend auth or signed URL |
| Restart safety | AI restart reloads same canonical entity set | no local private truth needed |

## Recommended Migration Order

1. Tighten RBAC on entity create/update/delete/toggle.
2. Add entity lifecycle and detection toggle fields.
3. Add asset metadata table and private storage integration.
4. Build backend-owned embedding worker path.
5. Change registration flow to backend -> worker -> Postgres.
6. Filter AI snapshot to ready/enabled/active entities only.
7. Deprecate AI-owned enrollment as the canonical path.
8. Add tenant/camera runtime gating for entity detection.
9. Add soak, security, and restart verification.

## Agent Reading Order

Read these first:

1. `services/backend/api/models.py`
2. `services/backend/api/views.py`
3. `services/backend/api/serializers.py`
4. `services/backend/ai_integration/views.py`
5. `services/ai/src/identity/store.py`
6. `services/ai/src/api/server.py`
7. `services/ai/src/logic/aggregator.py`
8. `services/ai/src/lanes/entity_identity.py`

## Key Design Corrections

1. Do not add a single vector column to `KnownEntity` unless you intentionally want to throw away support for multiple embeddings and modalities.
2. Do not keep AI as the canonical enrollment writer.
3. Do not leave entity mutation at `non_viewer`; this should be `owner/admin` for secure operation.
4. Do not load every historical entity into AI when runtime only needs `READY + enabled + camera-allowed`.

## Definition Of Done

This plan is complete when:

- backend owns entity registration and vector persistence
- Postgres is the canonical source of truth for entities and embeddings
- AI is a read-only matcher consumer of canonical enabled vectors
- entity create/delete/toggle is protected by `owner/admin` access
- entity detection can be toggled explicitly at entity and runtime scope
- enrollment assets are stored securely and accessed safely
- the workflow is restart-safe, cloud-native, and not dependent on AI-local canonical files
