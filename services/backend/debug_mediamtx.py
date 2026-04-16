import os
import sys
import django

# Setup Django environment
sys.path.append('c:\\Users\\devan\\OneDrive\\Desktop\\yolov12-cls\\vigilzone-monolith\\services\\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
django.setup()

from api.models import Camera
from api.views import reconcile_all_cameras_to_mediamtx

print("--- Starting MediaMTX Manual Reconciliation Debug ---")
cameras = Camera.objects.exclude(rtsp_url__isnull=True).exclude(rtsp_url__exact="")
print(f"Found {len(cameras)} cameras to reconcile.")
for cam in cameras:
    print(f" - Camera ID {cam.id}: {cam.name} -> {cam.rtsp_url}")

try:
    summary = reconcile_all_cameras_to_mediamtx()
    print("Reconciliation Summary:", summary)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("Reconciliation failed with error:", e)
