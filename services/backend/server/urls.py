from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from api.views import (
    TenantViewSet, MembershipViewSet, CameraViewSet, IncidentViewSet,
    DetectionViewSet, AlertViewSet, AuditLogViewSet, ProfileViewSet, auth_context, InvitationViewSet,
    dashboard_summary, KnownEntityViewSet,
    community_activity,
    notification_settings, notification_test, notification_register_device,
    notifications_list, notifications_mark_read, notifications_unread_count,
    notifications_broadcast, notifications_test_websocket, notifications_test_incident, notifications_transport_status,
    ai_webcam_state,
    debug_system,
    streams_list, streams_detail, streams_snapshot, streams_mjpeg, streams_signed_token, streams_health,
)

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from api.auth_views import RegisterView

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")
router.register(r"memberships", MembershipViewSet, basename="membership")
router.register(r"cameras", CameraViewSet, basename="camera")
router.register(r"incidents", IncidentViewSet, basename="incident")
router.register(r"detections", DetectionViewSet, basename="detection")
router.register(r"alerts", AlertViewSet, basename="alert")
router.register(r"audit", AuditLogViewSet, basename="audit")
router.register(r"profile", ProfileViewSet, basename="profile")
router.register(r"invitations", InvitationViewSet, basename="invitation")
router.register(r"entities", KnownEntityViewSet, basename="entity")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    # keep your JWT endpoints here if you've added them
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# !AUTH
urlpatterns += [
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/context/", auth_context),
    path("api/dashboard/summary/", dashboard_summary, name="dashboard-summary"),
    path("api/community/activity/", community_activity, name="community-activity"),
]

# Notifications (§4 & §5)
urlpatterns += [
    path("api/notifications/settings/", notification_settings, name="notification-settings"),
    path("api/notifications/test/", notification_test, name="notification-test"),
    path("api/notifications/register_device/", notification_register_device, name="notification-register-device"),
    # Real-time notification endpoints
    path("api/notifications/", notifications_list, name="notifications-list"),
    path("api/notifications/mark-read/", notifications_mark_read, name="notifications-mark-read"),
    path("api/notifications/unread-count/", notifications_unread_count, name="notifications-unread-count"),
    path("api/notifications/transport-status/", notifications_transport_status, name="notifications-transport-status"),
    path("api/notifications/broadcast/", notifications_broadcast, name="notifications-broadcast"),
    path("api/notifications/test-websocket/", notifications_test_websocket, name="notifications-test-websocket"),
    path("api/notifications/test-incident/", notifications_test_incident, name="notifications-test-incident"),
    path("api/ai/webcam-state/", ai_webcam_state, name="ai-webcam-state"),
]
# Debug (§7)
urlpatterns += [
    path("api/debug/system/", debug_system, name="debug-system"),
]
# Streams (§B — WebRTC/HLS URL endpoints)
urlpatterns += [
    path("api/streams/", streams_list, name="streams-list"),
    path("api/streams/<int:camera_id>/", streams_detail, name="streams-detail"),
    path("api/streams/<int:camera_id>/snapshot/", streams_snapshot, name="streams-snapshot"),
    path("api/streams/<int:camera_id>/mjpeg/", streams_mjpeg, name="streams-mjpeg"),
    path("api/streams/<int:camera_id>/signed_stream_token/", streams_signed_token, name="streams-signed-token"),
    path("api/streams/health/", streams_health, name="streams-health"),
]
# AI Integration (proxy + webhook)
urlpatterns += [
    path("api/ai/", include("ai_integration.urls")),
]
