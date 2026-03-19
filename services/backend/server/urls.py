from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api.views import (
    TenantViewSet, MembershipViewSet, CameraViewSet, IncidentViewSet,
    DetectionViewSet, AlertViewSet, AuditLogViewSet, ProfileViewSet, auth_context, InvitationViewSet,
    dashboard_summary, KnownEntityViewSet,
    community_activity,
    notification_settings, notification_test, notification_register_device,
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
# !AUTH
urlpatterns += [
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/context/", auth_context),
    path("api/dashboard/summary/", dashboard_summary, name="dashboard-summary"),
    path("api/community/activity/", community_activity, name="community-activity"),
]

# Notifications (§4)
urlpatterns += [
    path("api/notifications/settings/", notification_settings, name="notification-settings"),
    path("api/notifications/test/", notification_test, name="notification-test"),
    path("api/notifications/register_device/", notification_register_device, name="notification-register-device"),
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
