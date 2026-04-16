import os
import sys
import django
import requests

# Setup Django environment
sys.path.append('c:\\Users\\devan\\OneDrive\\Desktop\\yolov12-cls\\vigilzone-monolith\\services\\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
django.setup()

from api.models import Camera
from api.views import reconcile_all_cameras_to_mediamtx, _get_mediamtx_api_base

api_base = _get_mediamtx_api_base()
print(f"MediaMTX API Base: {api_base}")

def get_paths():
    try:
        resp = requests.get(f"{api_base}/v3/config/paths/list?page=0&itemsPerPage=100", timeout=2)
        if resp.status_code == 200:
            return resp.json().get('items', [])
        return f"Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Request failed: {e}"

print("--- Paths BEFORE reconciliation ---")
print(get_paths())

print("\n--- Running Reconciliation ---")
try:
    summary = reconcile_all_cameras_to_mediamtx()
    print("Summary:", summary)
except Exception as e:
    print(f"Reconciliation crashed: {e}")

print("\n--- Paths AFTER reconciliation ---")
print(get_paths())
