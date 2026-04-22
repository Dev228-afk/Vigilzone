# PostgreSQL Single-Source-Of-Truth Migration Plan

## Purpose

This document is the detailed migration handoff for moving the system from mixed truth sources to a targeted architecture where PostgreSQL is the canonical source of truth for mutable business and runtime configuration.

It is specifically aimed at solving the current issues where configuration and runtime state are split across:

- Django models backed by SQLite in local mode and PostgreSQL only when `DATABASE_URL` is present
- AI YAML config files
- AI local JSON files
- runtime-generated MediaMTX state
- hardcoded model and profile defaults in code

The goal is not "put everything in Postgres." The goal is:

- put mutable business and service configuration in Postgres
- keep secrets and deployment artifacts out of Postgres
- enforce one canonical owner for every mutable data domain
- remove per-service private truths such as `cameras_runtime.json` and `webhooks.json`
- make MediaMTX a DB-driven low-latency relay, not a runtime sidecar with private state
- make all add, update, and delete operations go through a proper data access layer with explicit getter and setter methods

This document is a companion to the broader architecture plan. It is narrower and more concrete: it focuses on schema ownership, CRUD access, bootstrap/DDL, backfill, cutover, and service integration.

## Executive Directive

By the end of this migration:

1. PostgreSQL is the only canonical source of truth for mutable business and configuration data.
2. Redis remains a projection/cache only.
3. No service stores its own mutable configuration as local YAML or JSON and treats that as authoritative.
4. Runtime services may cache configuration, but cached copies must be disposable and rebuildable from Postgres.
5. All writes to canonical truth go through owned service-layer setters, not scattered direct ORM calls and not ad hoc file mutation.
6. Table creation is owned by migrations, not by service startup logic.
7. First-time seed and sidecar row creation is explicit and idempotent.
8. MediaMTX relay intent, path ownership, and relay policy are stored in Postgres as desired state and reconciled automatically.

## Important Architectural Clarification

Single source of truth does not mean every service should perform arbitrary direct writes to every Postgres table.

The correct model is:

- Postgres is the canonical store.
- Ownership of write paths is still bounded.
- Backend control-plane services own canonical write operations for most config and business entities.
- Other services either:
  - read from Postgres directly using read-only roles and stable views, or
  - read from a config/control API backed by Postgres, or
  - read from Redis projections that are derived from Postgres.

What must disappear is "service-local truth," not "bounded service ownership."

## Relay Decision

This migration plan now assumes MediaMTX remains in the target architecture as the canonical relay layer for live ingest.

That changes the design in an important way:

- MediaMTX is not optional glue.
- MediaMTX becomes the single relay owner for camera sessions.
- Django preview and AI ingest should converge on relay outputs instead of opening the same upstream camera independently.
- PostgreSQL must own desired relay state so MediaMTX can be rebuilt automatically after restarts.

Low-latency implication:

- the default relay mode should be pass-through or remux, not transcode
- transcoding should only happen for sources that require bridging or normalization
- the canonical DB model must distinguish `relay-only` from `transcode-required`

## Current-State Inventory

### Current Truth Sources

| Current source | Location | Problem | Target state |
| --- | --- | --- | --- |
| Backend business data | `services/backend/api/models.py` and current DB | locally defaults to SQLite; not enforced as canonical for all services | PostgreSQL canonical store |
| Backend DB engine selection | `services/backend/server/settings.py` | SQLite fallback creates split behavior between local and cloud | local and prod both use PostgreSQL by end state |
| AI camera config | `services/ai/configs/cameras.yaml` | mutable runtime intent lives in a file owned by AI service | camera config tables in Postgres |
| AI zones config | `services/ai/configs/zones.yaml` | zone truth split from backend camera state | camera zone tables in Postgres |
| AI policy config | `services/ai/configs/policy.yaml` | routing/policy truth split from backend | policy tables in Postgres |
| AI model runtime toggles | `services/ai/configs/models.yaml` | some values are business config, some are deployment config; currently mixed | split between Postgres config and env/file deployment artifacts |
| AI runtime camera registry | `services/ai/data/cameras_runtime.json` | AI owns mutable camera runtime truth locally | Postgres registration/runtime state tables |
| AI webhook registry | `services/ai/data/webhooks.json` | webhook truth is local to AI process | Postgres webhook tables |
| MediaMTX desired path state | runtime only | path truth is ephemeral and must be reconciled manually | Postgres desired-state tables plus reconciler |
| Hardcoded profile defaults | `services/backend/api/models.py` | defaults become code truth instead of data truth | seeded defaults and policy templates in Postgres |
| Hardcoded camera defaults | `services/backend/api/models.py` | threshold/lane defaults mixed into model definitions | seeded camera policy/profile defaults in Postgres |

### Current Hardcoded Or File-Based Values That Must Be Reviewed

These are the highest-value current config sources to migrate or classify:

- `Profile` defaults:
  - notification booleans
  - instant notification levels
  - retention days
  - alert sensitivity
- `NotificationChannel` defaults:
  - severity threshold
  - email/push enabled flags
- `TenantRuntimeSetting` defaults
- `Camera` defaults:
  - `min_confidence`
  - `min_bbox_area`
  - `k_of_n_k`
  - `k_of_n_n`
  - `cooldown_s`
  - `enabled_lanes`
- AI YAML config:
  - cameras
  - zones
  - policy
  - per-lane enablement and thresholds that are actually business-configurable
- AI JSON config:
  - registered webhooks
  - runtime cameras

### Current Values That Should Not Move To Postgres

Do not move these to Postgres:

- `DATABASE_URL`
- Redis, JetStream, SMTP, FCM, object storage credentials
- JWT secrets, Django secret key, API keys
- local model weight file paths
- TensorRT engine paths
- Python executable paths
- container image tags
- deployment worker counts and infra credentials

These belong in environment variables, secret stores, or deployment manifests, not in canonical business/config tables.

## Migration Rules

### Rule 1: Mutable Product Behavior Goes To Postgres

If a value changes product behavior and can be altered by admin/business operations, it belongs in Postgres.

Examples:

- which camera belongs to which tenant/community
- what zones a camera uses
- which lanes are enabled for a camera
- per-camera thresholds and cooldowns
- user notification preferences
- tenant/community notification routing policy
- AI webhook registrations
- desired MediaMTX stream/path configuration

### Rule 2: Secrets And Deployment Artifacts Stay Out Of Postgres

If a value is a secret or a machine-specific deployment artifact, it should not be moved into Postgres.

Examples:

- passwords
- DSNs
- secret keys
- model filesystem paths
- local executable paths

### Rule 3: Runtime Cache Is Allowed, Runtime Truth Is Not

Services may cache Postgres-derived config in memory or Redis, but:

- caches must be disposable
- cache warm-up must be deterministic
- service restart must not require local JSON/YAML to reconstruct truth

### Rule 4: No Direct ORM Or File Mutation From Views/Workers

All mutable config operations must move behind service-layer methods. Views, subscribers, and workers should call service/repository methods, not scatter direct `Model.objects...` and file writes throughout the codebase.

### Rule 5: Table Creation Is A Migration Concern

Runtime services must not create or alter tables at startup. Schema creation belongs to versioned migrations and bootstrap jobs only.

## Target Ownership Model

### Canonical System Of Record

PostgreSQL owns:

- identity and tenancy state
- camera and community state
- mutable AI/runtime configuration that affects business behavior
- notification preferences and routing policies
- webhook and runtime registration state
- desired ingest/relay state
- outbox and migration metadata
- incident and audit durability

### Derived State

Redis owns:

- route projections
- camera context projections
- ephemeral hot-path caches

MediaMTX owns:

- actual runtime stream sessions only

AI service owns:

- in-memory runtime state only
- no private long-lived config truth

## Target Table Groups

The plan below assumes we evolve the existing Django data model rather than throwing it away. Existing tables should be extended where sensible, and new tables should be added for domains that are currently file-backed or overly denormalized.

### Group A: Core Identity And Tenancy

Keep and evolve:

- `Tenant`
- `Membership`
- `Profile`

Add if needed:

- `Community`
- `CommunityMembership`
- `RolePolicy`

Purpose:

- canonical ownership of who belongs where
- separation of tenant-wide and community-wide routing policy if both are needed

### Group B: Camera And Ingest Configuration

Keep and evolve:

- `Camera`
- `CameraZone`
- `TenantRuntimeSetting`

Add:

- `CameraIngestProfile`
- `CameraAIProfile`
- `CameraEvidenceProfile`
- `CameraAssignmentVersion`
- `IngestDesiredState`
- `MediaMTXDesiredPath`
- `MediaMTXRelayProfile`
- `MediaMTXObservedPathState`
- `CameraRelayBinding`
- `AIRuntimeRegistration`

Purpose:

- replace `cameras.yaml`
- replace `zones.yaml`
- replace runtime camera JSON
- make desired stream ownership explicit

### Group C: Notification And Routing Configuration

Keep and evolve:

- `NotificationChannel`

Add:

- `UserNotificationPreference`
- `TenantNotificationPolicy`
- `CommunityNotificationPolicy`
- `RoutingPolicyTemplate`
- `RoutingPolicyVersion`
- `DeliveryEndpoint`

Purpose:

- remove hardcoded/default routing behavior from code
- make recipient and policy logic fully DB-driven

### Group D: Integration And Webhook Configuration

Add:

- `ServiceWebhook`
- `WebhookSubscription`
- `ServiceEndpointRegistry`
- `IntegrationCredentialRef` if needed for secret references only, not raw secrets

Purpose:

- replace `webhooks.json`
- remove per-service webhook truth

### Group E: Eventing, Projection, And Migration Metadata

Keep and evolve:

- `IncidentEventReceipt`

Add:

- `OutboxEvent`
- `ProjectionWatermark`
- `ProjectionRepairRequest`
- `SchemaBootstrapState`
- `BackfillCheckpoint`

Purpose:

- safe migration
- projector correctness
- repeatable replay/rebuild

## Recommended Table-Level Mapping

| Target table | What it stores | Replaces | Write owner |
| --- | --- | --- | --- |
| `tenant` | tenant metadata, plan, lifecycle | current `Tenant` plus hardcoded plan defaults | backend control plane |
| `profile` | user-level preferences | current `Profile` defaults | backend control plane |
| `membership` | tenant role membership | current `Membership` | backend control plane |
| `camera` | identity, assignment, stream identity | current `Camera` | backend control plane |
| `camera_ingest_profile` | upstream source, source kind, sample rates, relay mode, transcode requirement | parts of `Camera`, `cameras.yaml`, runtime JSON | backend control plane |
| `camera_ai_profile` | enabled lanes, thresholds, cooldowns, K-of-N | camera defaults and `cameras.yaml` | backend control plane |
| `camera_evidence_profile` | evidence pre/post clip settings, retention hints | `cameras.yaml` evidence section | backend control plane |
| `camera_zone` | zone polygons and flags | `CameraZone` plus `zones.yaml` | backend control plane |
| `camera_relay_binding` | stable mapping from camera to relay path and relay output identities | implicit runtime naming today | backend control plane |
| `mediamtx_relay_profile` | relay-only vs transcode-required mode, low-latency policy, protocol hints | ad hoc runtime path payload construction | backend control plane |
| `tenant_notification_policy` | tenant-level routing thresholds and policy | code defaults and `policy.yaml` | backend control plane |
| `user_notification_preference` | per-user channel/severity preferences | `Profile` JSON/default booleans | backend control plane |
| `notification_channel` | channel enablement and tenant delivery settings | current `NotificationChannel` | backend control plane |
| `service_webhook` | registered webhooks and event subscriptions | `webhooks.json` | backend control plane or integration service |
| `ai_runtime_registration` | desired and observed AI camera registration state | `cameras_runtime.json` | backend control plane writes desired state; AI updates observed state |
| `mediamtx_desired_path` | desired relay path definitions and source bindings | runtime-only MediaMTX config | backend control plane or ingest reconciler |
| `mediamtx_observed_path_state` | observed relay health, last reconcile result, drift markers, path generation | implicit logs/manual checks today | ingest reconciler |
| `outbox_event` | change publication | none | owner service transaction |
| `projection_watermark` | projector progress | none | projector |

## What To Normalize Vs What To Keep As JSONB

### Normalize

Normalize when:

- the data is queried frequently by key
- the data participates in joins or routing
- the data needs referential integrity
- add/update/delete operations will be common

Normalize:

- memberships
- camera ownership
- zones
- user channel preferences
- webhook subscriptions
- delivery endpoints
- policy version rows

### Keep In JSONB Initially

Use JSONB initially when the shape is flexible and the query pattern is simple:

- some policy rule blobs
- lane-specific advanced thresholds
- evidence export options
- projector metadata

Rule:

- JSONB is allowed for flexible configuration, but only inside Postgres tables that are still canonical.
- JSON files on disk are not acceptable as canonical truth once migration is complete.

## CRUD Access Layer: Getter And Setter Design

### Why A Data Access Layer Is Required

Right now the codebase has multiple direct access styles:

- direct Django ORM calls in views
- `get_or_create` in request handlers
- file reads for YAML config
- file writes for JSON runtime state

That makes it impossible to guarantee a single source of truth, because any caller can invent new side effects. The migration must introduce a narrow set of getters and setters that every mutation path uses.

### Design Rule

Every mutable aggregate gets:

- a repository for reads/writes against Postgres
- a service layer for validation, transactions, side effects, and outbox emission
- typed command objects or serializers for add/update/delete operations

Views, workers, and subscribers must call services, not repositories directly unless they are read-only queries.

### Recommended Python Module Layout

Add modules like:

- `services/backend/api/repositories/tenant_repository.py`
- `services/backend/api/repositories/camera_repository.py`
- `services/backend/api/repositories/notification_repository.py`
- `services/backend/api/repositories/webhook_repository.py`
- `services/backend/api/repositories/runtime_repository.py`
- `services/backend/api/services/tenant_config_service.py`
- `services/backend/api/services/camera_config_service.py`
- `services/backend/api/services/notification_policy_service.py`
- `services/backend/api/services/webhook_registry_service.py`
- `services/backend/api/services/runtime_registration_service.py`
- `services/backend/api/services/bootstrap_service.py`

### Required Getter Methods

At minimum, define getter methods like:

```python
class TenantConfigRepository:
    def get_tenant(self, tenant_id: str) -> TenantDTO: ...
    def get_tenant_runtime_settings(self, tenant_id: str) -> TenantRuntimeDTO: ...
    def get_notification_policy(self, tenant_id: str) -> TenantNotificationPolicyDTO: ...


class CameraConfigRepository:
    def get_camera(self, camera_id: str) -> CameraDTO: ...
    def list_cameras_for_tenant(self, tenant_id: str) -> list[CameraDTO]: ...
    def get_camera_ingest_profile(self, camera_id: str) -> CameraIngestProfileDTO: ...
    def get_camera_ai_profile(self, camera_id: str) -> CameraAIProfileDTO: ...
    def get_camera_zones(self, camera_id: str) -> list[CameraZoneDTO]: ...


class NotificationConfigRepository:
    def get_user_notification_preference(self, user_id: str, tenant_id: str) -> UserNotificationPreferenceDTO: ...
    def get_route_policy(self, tenant_id: str, community_id: str | None) -> RoutingPolicyDTO: ...


class WebhookRepository:
    def list_webhooks(self, tenant_id: str) -> list[WebhookDTO]: ...
    def get_webhook(self, webhook_id: str) -> WebhookDTO: ...


class RuntimeRepository:
    def get_ai_runtime_registration(self, camera_id: str) -> AIRuntimeRegistrationDTO: ...
    def list_desired_mediamtx_paths(self) -> list[MediaMTXPathDTO]: ...
```

### Required Setter Methods

At minimum, define setter methods like:

```python
class TenantConfigService:
    def create_tenant(self, cmd: CreateTenantCommand) -> TenantDTO: ...
    def update_tenant(self, tenant_id: str, cmd: UpdateTenantCommand) -> TenantDTO: ...
    def delete_tenant(self, tenant_id: str, actor_id: str) -> None: ...


class CameraConfigService:
    def create_camera(self, cmd: CreateCameraCommand) -> CameraDTO: ...
    def update_camera(self, camera_id: str, cmd: UpdateCameraCommand) -> CameraDTO: ...
    def delete_camera(self, camera_id: str, actor_id: str) -> None: ...
    def set_camera_ingest_profile(self, camera_id: str, cmd: SetCameraIngestProfileCommand) -> CameraIngestProfileDTO: ...
    def set_camera_ai_profile(self, camera_id: str, cmd: SetCameraAIProfileCommand) -> CameraAIProfileDTO: ...
    def replace_camera_zones(self, camera_id: str, zones: list[ZoneCommand], actor_id: str) -> list[CameraZoneDTO]: ...


class NotificationPolicyService:
    def set_tenant_notification_policy(self, tenant_id: str, cmd: SetTenantNotificationPolicyCommand) -> RoutingPolicyDTO: ...
    def set_user_notification_preference(self, user_id: str, tenant_id: str, cmd: SetUserNotificationPreferenceCommand) -> UserNotificationPreferenceDTO: ...
    def delete_user_notification_preference(self, user_id: str, tenant_id: str, actor_id: str) -> None: ...


class WebhookRegistryService:
    def register_webhook(self, cmd: RegisterWebhookCommand) -> WebhookDTO: ...
    def update_webhook(self, webhook_id: str, cmd: UpdateWebhookCommand) -> WebhookDTO: ...
    def delete_webhook(self, webhook_id: str, actor_id: str) -> None: ...


class RuntimeRegistrationService:
    def register_ai_camera_desired_state(self, camera_id: str, cmd: RegisterAICameraCommand) -> AIRuntimeRegistrationDTO: ...
    def mark_ai_camera_observed_state(self, camera_id: str, cmd: MarkAICameraObservedStateCommand) -> AIRuntimeRegistrationDTO: ...
    def set_desired_mediamtx_path(self, camera_id: str, cmd: SetMediaMTXPathCommand) -> MediaMTXPathDTO: ...
```

### Setter Method Rules

- setters must run inside transactions
- setters must emit outbox events when config changes affect routing or runtime
- setters must validate referential integrity and business invariants
- delete operations should default to soft-delete or deactivation when operationally safer than hard delete
- direct `.save()` in views should be removed over time

### Getter Method Rules

- getters should expose stable DTOs or serializers, not raw ORM internals to other services
- getters for runtime services should support efficient snapshot retrieval
- high-frequency runtime reads should be optimized with caching or Redis projections, but the cache fill still comes from Postgres-backed getters

## Bootstrap And First-Time Table Creation Strategy

### Strong Recommendation

Use Django migrations for table creation.

Do not let runtime services create tables with `CREATE TABLE IF NOT EXISTS` during startup. That pattern causes:

- race conditions
- partial schema drift
- unclear ownership
- broken rollback behavior

### What "First-Time Table Creation Functions" Should Mean Here

Use a two-part strategy:

1. Versioned migrations create schemas, tables, indexes, constraints, and DB functions.
2. Idempotent bootstrap functions create required default rows and sidecar data after tables exist.

That gives you the DB-side deterministic setup you asked for without turning service startup into an uncontrolled migration engine.

### Required Bootstrap Sequence

1. Create PostgreSQL database and extensions.
2. Apply migrations.
3. Create bootstrap functions.
4. Run bootstrap functions or a bootstrap management command.
5. Backfill legacy file/config sources into canonical tables.
6. Enable dual-write.
7. Cut reads over.
8. Remove old sources.

### Recommended Postgres Extensions

Consider enabling:

- `pgcrypto` for UUID generation if needed
- `btree_gin` only if needed later for JSONB search/indexing

Do not add extensions "just in case."

### Recommended Bootstrap Functions

Create DB-side or migration-installed functions like:

```sql
create or replace function ops.bootstrap_system_defaults() returns void;
create or replace function ops.ensure_tenant_defaults(p_tenant_id uuid) returns void;
create or replace function ops.ensure_camera_sidecars(p_camera_id uuid) returns void;
create or replace function routing.bump_policy_version(
    p_tenant_id uuid,
    p_community_id uuid default null
) returns bigint;
create or replace function routing.request_projection_rebuild(
    p_scope_type text,
    p_scope_id uuid,
    p_reason text
) returns void;
```

Purpose of each:

- `bootstrap_system_defaults`: inserts default policy templates and global non-secret defaults
- `ensure_tenant_defaults`: creates required rows such as runtime settings, notification defaults, and policy version rows
- `ensure_camera_sidecars`: creates ingest/AI/evidence profile rows for a new camera
- `bump_policy_version`: increments version when routing-relevant config changes
- `request_projection_rebuild`: makes rebuild requests explicit and auditable

### Management Command For Bootstrap

Add a backend command such as:

`python manage.py bootstrap_postgres_config`

Responsibilities:

- verify required extensions exist
- verify migrations are applied
- call DB bootstrap functions
- create system default rows
- report missing seed data

This command should be safe to run repeatedly.

### First-Time Seed Data That Should Exist In Postgres

Seed values that are currently hardcoded in code should be moved into DB-backed defaults, for example:

- default instant notification levels
- default camera thresholds
- default enabled lanes
- default retention period
- default severity threshold
- default tenant runtime settings

Code should validate the existence of these defaults, not own them permanently.

## Proposed Schema Evolution

### Step 1: Stop Using SQLite As The Long-Term Local Default

Current state:

- backend falls back to SQLite when `DATABASE_URL` is absent

Plan:

- keep SQLite only temporarily while migration scaffolding is built
- add local Docker/Postgres for development
- by migration completion, make PostgreSQL the default local dev path too

Reason:

- if local dev keeps SQLite while production uses Postgres, schema behavior, JSON behavior, transactions, indexes, and locking semantics will continue to diverge

### Step 2: Extend Existing Models Before Creating Entirely New Parallel Models

Prefer:

- extending `Tenant`, `Camera`, `NotificationChannel`, and `TenantRuntimeSetting`
- adding new sidecar models where the current model is too overloaded or missing structure

Do not:

- create a second unrelated `CameraConfig` truth table while still keeping mutable camera config in YAML

### Step 3: Normalize Existing JSON And Defaults Incrementally

Suggested moves:

- `Profile.instant_notification_levels`
  - keep short-term as JSON in Postgres
  - later normalize to a child table if querying becomes complex
- `NotificationChannel.email_recipients` and `fcm_tokens`
  - move toward separate `DeliveryEndpoint` rows
- `Camera.enabled_lanes`
  - move toward `CameraLaneConfig` rows or JSONB sidecar depending query patterns

### Step 4: Add Version Columns Where Change Triggers Rebuilds

Add or standardize:

- `config_version`
- `policy_version`
- `updated_at`
- `updated_by`
- `deleted_at` where soft delete is used

These fields are essential for projector invalidation and service sync.

## Migration Phases

### Phase 0: Inventory And Classification

Goal:

- classify every current mutable value as one of:
  - canonical Postgres config
  - derived projection/cache
  - secret/env
  - deployment artifact

Tasks:

- inventory every YAML/JSON file currently read in production code paths
- inventory every direct ORM write in views, signals, and workers
- inventory every default value in models that represents mutable business behavior
- inventory every `get_or_create` that currently seeds runtime rows implicitly

Deliverable:

- a migration spreadsheet or doc mapping each source to target table/service owner

### Phase 1: Postgres Foundation And Schema Bootstrap

Goal:

- make Postgres the real migration target without changing all runtime readers yet

Tasks:

- add local Postgres service to developer workflow
- create migrations for new tables and extensions
- add bootstrap functions and `bootstrap_postgres_config` management command
- add indexes and constraints early
- add outbox and projection metadata tables

Verification:

- fresh environment can create schema from zero
- bootstrap can run twice without errors
- existing backend tests pass against Postgres

### Phase 2: Repository And Service Layer Introduction

Goal:

- stop new feature work from adding more direct truth paths

Tasks:

- introduce repositories and service-layer getters/setters
- refactor write-heavy endpoints to call service layer
- refactor any `get_or_create` default-seeding from views into explicit service/bootstrap flows
- add DTOs for config snapshots used by AI and workers

Verification:

- code search shows targeted views/workers no longer mutate config tables directly
- service-layer tests cover add/update/delete operations

### Phase 3: Dual-Write Canonical Tables

Goal:

- populate Postgres tables while legacy sources still exist

Tasks:

- when camera config is updated via backend, write both:
  - current path
  - new canonical Postgres tables
- when webhook config changes, write both legacy JSON path and Postgres table temporarily
- when runtime settings change, write canonical tables and continue feeding old readers if needed

Critical rule:

- dual-write is temporary and must be instrumented

Verification:

- compare legacy data snapshots to Postgres rows after each update
- alert on drift between dual-written states

### Phase 4: Backfill Legacy Sources Into Postgres

Goal:

- import existing YAML/JSON/config state into canonical tables

Backfill sources:

- `cameras.yaml`
- `zones.yaml`
- `policy.yaml`
- `cameras_runtime.json`
- `webhooks.json`
- existing backend DB tables that need normalization

Tasks:

- write import scripts or management commands
- stamp imported rows with source metadata and import timestamp
- create reconciliation reports for missing or conflicting entries

Verification:

- row counts and hash/checksum comparisons between source files and target rows
- manual review for cameras, webhooks, and policy mappings

### Phase 5: Read Cutover By Domain

Goal:

- switch readers one domain at a time from legacy sources to Postgres-backed getters

Recommended order:

1. backend runtime settings and notification config
2. camera config and zones
3. AI runtime registration snapshots
4. webhook registry
5. policy/routing config
6. MediaMTX desired path state

Rules:

- use feature flags per domain
- enable dual-read compare before full cutover
- emit mismatch metrics during compare window

Verification:

- each domain reads from Postgres with no behavior regression
- dual-read comparisons show no drift before legacy reader removal

### Phase 6: Remove Service-Local Truth Sources

Goal:

- eliminate private configuration truth in local files and code defaults

Tasks:

- remove production reads from:
  - `cameras.yaml`
  - `zones.yaml`
  - `policy.yaml`
  - `cameras_runtime.json`
  - `webhooks.json`
- leave static templates/examples only for dev bootstrap if needed
- keep `models.yaml` only for system/deployment artifacts or model catalog values that are not mutable business config

Verification:

- production startup works without mutable YAML/JSON state
- changing a camera or webhook in backend updates live service behavior via Postgres-backed flow

### Phase 7: Enforce Single Source Of Truth

Goal:

- prevent regression back to local/private truth

Tasks:

- add startup assertions that required canonical tables exist
- add health checks for Postgres reachability and schema version
- add code review rule: no new mutable config files
- add tests that fail if AI or notification services try to persist canonical config locally
- remove fallback writes to legacy sources

Verification:

- no service depends on local mutable config for normal operation
- operational recovery works from Postgres plus projections only

## Domain-Specific Migration Plan

### Domain 1: Tenants, Memberships, Profiles, And User Preferences

Current state:

- `Tenant`, `Membership`, and `Profile` already exist in backend models
- defaults like instant notification levels and retention behavior are code-owned

Plan:

- keep these tables in Postgres as canonical truth
- add explicit `UserNotificationPreference` if profile is becoming overloaded
- move mutable notification defaults into seed/default-policy rows
- keep code-level enums only for validation, not for authoritative defaults

CRUD requirements:

- `create_tenant`
- `update_tenant`
- `delete_tenant` or `deactivate_tenant`
- `add_membership`
- `update_membership_role`
- `remove_membership`
- `set_user_notification_preference`
- `delete_user_notification_preference`

Verification:

- add/update/delete operations all work through service layer
- notification routing rebuild is triggered when memberships or preferences change

### Domain 2: Cameras, Zones, And Per-Camera AI Config

Current state:

- `Camera` and `CameraZone` exist in backend DB
- extra camera runtime config still exists in `cameras.yaml` and AI local state

Plan:

- extend camera-side tables to fully own:
  - stream identity
  - source type
  - ingest profile
  - AI profile
  - evidence profile
  - zone config
- stop treating `cameras.yaml` as canonical

CRUD requirements:

- `create_camera`
- `update_camera`
- `delete_camera` or `deactivate_camera`
- `set_camera_ingest_profile`
- `set_camera_ai_profile`
- `replace_camera_zones`
- `set_camera_evidence_profile`

Verification:

- camera add/update/delete reflects in AI and ingest reconciliation through canonical state
- no manual YAML edits required for a camera lifecycle change

### Domain 3: Notification Channels And Routing Policy

Current state:

- `NotificationChannel` exists
- policy behavior is split across code defaults, `Profile`, and `policy.yaml`

Plan:

- keep `NotificationChannel` but reduce its overload
- add explicit tables for user notification preferences and policy versions
- move tenant/community policy into canonical rows
- route projection rebuilds from Postgres changes only

CRUD requirements:

- `set_tenant_notification_channel`
- `set_user_notification_preference`
- `set_tenant_notification_policy`
- `set_community_notification_policy`
- `delete_delivery_endpoint`

Verification:

- route projection output is fully reproducible from Postgres
- no hardcoded severity defaults are required in code during runtime

### Domain 4: Webhooks And Integration Registry

Current state:

- AI keeps webhook registry in `webhooks.json`

Plan:

- create `ServiceWebhook` and `WebhookSubscription`
- backend or integration service becomes write owner
- AI reads active webhooks from Postgres-backed snapshot or config API

CRUD requirements:

- `register_webhook`
- `update_webhook`
- `delete_webhook`
- `list_webhooks`

Verification:

- webhook registrations survive AI restart without local JSON
- webhook add/update/delete is visible across services via Postgres-backed flow

### Domain 5: AI Runtime Registration

Current state:

- AI persists registered cameras to `cameras_runtime.json`

Plan:

- desired registration state lives in `AIRuntimeRegistration`
- AI updates observed status and heartbeat fields, not desired ownership fields
- backend remains source of truth for assignment, tenant/community mapping, and policy version

Suggested columns:

- `camera_id`
- `desired_enabled`
- `desired_ingest_backend`
- `desired_sample_hz`
- `desired_policy_version`
- `observed_enabled`
- `observed_ingest_backend`
- `observed_sample_hz`
- `observed_last_seen_at`
- `last_error`

Verification:

- AI restart reconstructs registration from Postgres
- no `cameras_runtime.json` needed in steady state

### Domain 6: MediaMTX Desired State

Current state:

- desired relay path state is reconstructed through backend logic and manual reconcile
- relay behavior is partly inferred at runtime instead of expressed as canonical policy
- preview and AI can still create split ingest ownership outside the relay

Plan:

- add canonical desired-state tables for relay paths, relay mode, and observed relay state
- make MediaMTX the single relay owner for camera sessions in steady state
- store whether a camera is:
  - relay-only
  - remux-required
  - transcode-required
- store canonical stable relay identities:
  - path name
  - input binding
  - preview output identity
  - AI-consumption identity
  - evidence identity if separate
- reconciler compares desired state in Postgres with observed MediaMTX state
- no path definitions remain "only in runtime memory"
- startup rebuild must fully converge from Postgres without manual reconcile

Low-latency design rule:

- default every camera to pass-through/remux relay mode
- only enable FFmpeg/transcode stages where the source type requires normalization
- do not add transcoding to "solve" orchestration problems that should be solved by state ownership

Suggested canonical columns across relay tables:

- `camera_id`
- `stream_path`
- `path_generation`
- `desired_enabled`
- `relay_mode`
- `source_uri`
- `source_kind`
- `transcode_required`
- `preview_consumer_uri`
- `ai_consumer_uri`
- `evidence_consumer_uri`
- `last_reconciled_at`
- `last_observed_state`
- `last_error`
- `drift_detected`

CRUD requirements:

- `set_desired_stream_path`
- `delete_desired_stream_path`
- `list_desired_stream_paths`
- `mark_observed_stream_state`
- `set_relay_profile`
- `bind_camera_to_relay_outputs`
- `mark_reconcile_result`

Verification:

- relay state can be rebuilt solely from Postgres after restart
- no camera requires manual reconcile to become available after backend, AI, or MediaMTX restart
- relay latency stays within target budget when camera is in relay-only/remux mode
- preview and AI consume relay outputs rather than opening duplicate direct sessions

## Service-By-Service Integration Plan

### Backend API Service

Target role:

- primary owner of canonical config writes
- owner of migrations and bootstrap command
- owner of outbox writes for config changes

Required changes:

- replace direct ORM mutations in views with service-layer setters
- replace implicit `get_or_create` bootstrap behavior with explicit bootstrap/service methods
- add config snapshot endpoints for AI if direct DB access is not used

### AI Service

Target role:

- runtime consumer of canonical config
- emitter of incidents and observed runtime status
- not the owner of camera or webhook truth
- relay consumer for inference inputs, not an independent direct camera owner

Required changes:

- replace `Config.load_cameras()` with Postgres-backed or control-API-backed camera snapshot loader
- replace `load_zones()` with DB-backed zone snapshot loader
- replace `load_policy()` with DB-backed policy snapshot loader
- replace local webhook registry persistence with Postgres-backed registry
- replace `cameras_runtime.json` with canonical registration state plus in-memory cache

Important nuance:

- model artifact definitions can remain file/env based
- business-configurable lane enablement and thresholds move to Postgres
- AI should consume relay URIs or relay identities produced by canonical DB state instead of constructing private upstream URLs

### Notification Worker Or Future Notification Service

Target role:

- reads routing projections and canonical preferences
- writes delivery audit state
- never owns private route truth

Required changes:

- no local config files for recipients or policy
- use Postgres for canonical audit/policy and Redis for hot-path route projection

### MediaMTX Reconciler Or Ingest Controller

Target role:

- reads desired stream/path state from Postgres
- writes observed state/heartbeat only
- enforces single relay ownership and path generations
- verifies low-latency relay mode is preserved unless transcode is explicitly required

Required changes:

- no manual private state files
- desired configuration rebuildable from Postgres only
- reconcile logic separated into:
  - desired-state rendering
  - apply step
  - observed-state verification
  - drift repair

### Frontend Preview Path

Target role:

- consume low-latency preview outputs derived from the canonical relay
- not create hidden direct camera sessions in steady state

Required changes:

- replace direct preview session ownership with relay output consumption
- keep any direct-open fallback only as a temporary migration/debug path behind flags

## Removing Hardcoded Defaults Safely

### What To Replace

Current hardcoded defaults should become one of:

1. DB-seeded system defaults
2. tenant/community policy templates
3. camera profile templates
4. explicit required input values

Examples:

- `default_instant_notification_levels()` -> `system_default_notification_policy`
- camera `min_confidence` default -> `camera_profile_template`
- `enabled_lanes` default -> `camera_profile_template`
- retention/default sensitivity -> `tenant_default_profile_policy`

### What Can Stay Hardcoded

Code-level constants that define validation, not mutable truth, can stay in code:

- enum names
- validation bounds
- API schema versions
- canonical status names

Example:

- role names such as `owner/admin/member/viewer` may remain code enums if the product does not require runtime-customizable roles
- but the assignment of users to roles is canonical Postgres data

## First-Time DDL And Seed Rollout Checklist

### DDL Ownership

Use Django migrations to create:

- new tables
- new indexes
- check constraints
- foreign keys
- unique keys
- DB functions
- trigger functions only where clearly justified

### Bootstrap Ownership

Use either:

- a data migration, or
- `bootstrap_postgres_config`

to call:

- `ops.bootstrap_system_defaults()`
- `ops.ensure_tenant_defaults(...)`
- `ops.ensure_camera_sidecars(...)`

### Initial Seed Checklist

On first environment bootstrap:

1. Create database and user roles.
2. Apply migrations.
3. Run bootstrap command.
4. Verify seed tables and default rows exist.
5. Run backfill commands from legacy YAML/JSON.
6. Enable shadow reads and drift reporting.

### Readiness Conditions Before Production Cutover

- all canonical tables exist
- bootstrap is idempotent
- backfill reports are clean
- dual-write drift is zero or understood
- AI and backend can both reconstruct required runtime snapshots from Postgres

## Verification Strategy

### Schema Verification

Verify:

- migrations run clean from empty database
- migrations run clean from current production backup clone
- indexes are created as expected
- foreign keys and uniqueness constraints reject bad data

Pass condition:

- fresh bootstrap and upgrade bootstrap both succeed

### CRUD Verification

For each domain, test:

- create
- read
- update
- delete or deactivate
- repeated idempotent create/update where relevant

Pass condition:

- all add/update/delete operations go through service-layer setters and persist correctly

### Source-Of-Truth Verification

Verify:

- no production path reads mutable YAML/JSON after cutover
- no runtime behavior depends on service-local mutable files
- cache rebuilds from Postgres work after process restart

Pass condition:

- Postgres outage is the only truth outage for canonical config; there is no hidden private truth keeping some services "working differently"

### Backfill Verification

Verify:

- imported cameras equal file-defined cameras
- imported zones equal file-defined zones
- imported policies equal file-defined policies
- imported webhooks equal JSON-defined webhooks
- imported runtime registrations equal JSON-defined registrations

Pass condition:

- every legacy record has a canonical row or an explicit documented reason for omission

### Service Integration Verification

Verify:

- backend add/update/delete of camera config appears in AI runtime without YAML edits
- webhook updates survive AI restart without local JSON
- notification config updates trigger route rebuilds
- MediaMTX desired state rebuilds from Postgres after restart

Pass condition:

- each service starts from Postgres-backed truth and converges without operator reconcile steps

## Rollback Strategy

### During Dual-Write Period

Rollback is straightforward:

- keep legacy readers available
- keep backfill export snapshots
- turn off Postgres read flag for the affected domain

### After Domain Cutover

Rollback requires:

- restoring canonical table snapshots or point-in-time recovery if writes were bad
- temporarily re-enabling legacy readers only if the legacy source was kept in sync during the cutover window

Important rule:

- never delete the legacy source before the new domain has passed soak verification

## Recommended Implementation Order

1. Add Postgres-first local development path and bootstrap command.
2. Create new canonical tables and bootstrap functions, including relay-specific tables and versions.
3. Add repositories and service-layer getters/setters.
4. Refactor backend write paths to use service layer.
5. Backfill YAML/JSON and existing DB defaults into canonical tables.
6. Introduce MediaMTX desired-state rows, relay bindings, and reconciler plumbing in shadow mode.
7. Dual-write runtime config updates.
8. Switch backend read paths.
9. Switch AI config reads from file-based loaders to Postgres-backed loaders or config API.
10. Switch MediaMTX desired state to the Postgres-backed reconciler as the steady-state relay control path.
11. Switch preview and AI consumers to canonical relay identities.
12. Switch webhook/runtime registration to Postgres.
13. Remove legacy readers and writers.
14. Enforce no new mutable file-based config.

## Concrete File-Level Impact Areas

Backend files likely to change:

- `services/backend/server/settings.py`
- `services/backend/api/models.py`
- `services/backend/api/views.py`
- `services/backend/api/notification_service.py`
- `services/backend/api/serializers.py`
- `services/backend/api/signals.py`
- `services/backend/ai_integration/incident_ingest.py`
- new repository and service modules under `services/backend/api/`

AI files likely to change:

- `services/ai/src/common/config.py`
- `services/ai/src/api/server.py`
- any AI startup modules that currently load `cameras.yaml`, `zones.yaml`, `policy.yaml`, `cameras_runtime.json`, or `webhooks.json`

Infra/runtime files likely to change:

- `docker-compose.yml`
- backend env examples
- deployment manifests for Postgres connection and migration job startup

## Non-Negotiable Guardrails

1. Do not let runtime services create tables on boot.
2. Do not keep SQLite as a hidden long-term local truth while calling Postgres the canonical store.
3. Do not move secrets into Postgres.
4. Do not let AI keep `cameras_runtime.json` or `webhooks.json` as authoritative after cutover.
5. Do not allow views, subscribers, or workers to keep mutating canonical config with ad hoc ORM writes.
6. Do not treat Redis as a fallback source of truth.

## Definition Of Done

This migration is complete when:

- PostgreSQL is the single canonical source of truth for mutable business and runtime configuration
- no service owns private mutable truth in local YAML or JSON
- add/update/delete operations for config go through service-layer getters/setters backed by Postgres
- schema/bootstrap setup is deterministic and idempotent
- AI, backend, notification, and ingest components all converge from Postgres-backed truth
- legacy file-based config is either removed or downgraded to example-only templates
