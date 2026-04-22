"""
AI Integration URL patterns.

All mounted under ``/api/ai/`` by the project-level urls.py.
"""
from django.urls import path

from . import views

app_name = "ai_integration"

urlpatterns = [
    # ── Proxy endpoints (JWT-protected) ───────────────────────
    path("start/",                            views.ai_start,                      name="ai-start"),
    path("stop/",                             views.ai_stop,                       name="ai-stop"),
    path("cameras/",                          views.ai_cameras,                    name="ai-cameras"),
    path("alerts/",                           views.ai_alerts,                     name="ai-alerts"),
    path("frame/<str:camera_id>/",            views.ai_frame,                      name="ai-frame"),
    path("system/status/",                    views.ai_system_status,              name="ai-system-status"),

    # Entities CRUD
    path("entities/",                         views.ai_entities,                   name="ai-entities"),
    path("entities/<str:entity_id>/",         views.ai_entity_detail,              name="ai-entity-detail"),
    path("entities/<str:entity_id>/images/",  views.ai_entity_images,              name="ai-entity-images"),
    path("entities/enroll_person/",           views.ai_entity_enroll_person,       name="ai-entity-enroll-person"),
    path("entities/enroll_pet/",              views.ai_entity_enroll_pet,          name="ai-entity-enroll-pet"),
    path("entities/enroll_person_from_upload/", views.ai_entity_enroll_person_upload, name="ai-entity-enroll-person-upload"),
    path("entities/enroll_pet_from_upload/",  views.ai_entity_enroll_pet_upload,   name="ai-entity-enroll-pet-upload"),
    path("uploads/enroll_images/",            views.ai_upload_enroll_images,       name="ai-upload-enroll-images"),

    # Webhooks management
    path("webhooks/register/",               views.ai_webhooks_register,          name="ai-webhooks-register"),
    path("webhooks/",                         views.ai_webhooks_list,              name="ai-webhooks-list"),
    path("internal/cameras/snapshot/",       views.ai_internal_cameras_snapshot,  name="ai-internal-cameras-snapshot"),
    path("internal/policy/snapshot/",        views.ai_internal_policy_snapshot,   name="ai-internal-policy-snapshot"),
    path("internal/identity/snapshot/",      views.ai_internal_identity_snapshot, name="ai-internal-identity-snapshot"),
    path("internal/identity/watermark/",     views.ai_internal_identity_watermark, name="ai-internal-identity-watermark"),
    path("internal/webhooks/snapshot/",      views.ai_internal_webhooks_snapshot, name="ai-internal-webhooks-snapshot"),
    path("internal/identity/sync/",          views.ai_internal_sync_identity,     name="ai-internal-sync-identity"),
    path("internal/webhooks/sync/",          views.ai_internal_sync_webhooks,     name="ai-internal-sync-webhooks"),
    path("internal/runtime/sync/",           views.ai_internal_sync_runtime,      name="ai-internal-sync-runtime"),

    # Evidence / images (streamed through Django)
    path("evidence/<str:camera_id>/<str:filename>", views.ai_evidence,            name="ai-evidence"),
    path("enroll_images/<str:entity_id>/<str:filename>", views.ai_enroll_image,   name="ai-enroll-image"),

    # ── Webhook receiver (token-protected, no JWT) ────────────
    path("webhook/receive/",                  views.ai_webhook_receive,            name="ai-webhook-receive"),
]
