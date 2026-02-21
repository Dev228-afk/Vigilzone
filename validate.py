"""
Validation script to check if all components can be imported
Run this before starting the main application
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("=" * 60)
print("CCTV AI Module - Validation Script")
print("=" * 60)

errors = []

# Test imports
print("\n1. Testing core imports...")
try:
    from src.common.types import Observation, Alert
    from src.common.config import Config
    from src.common.log import setup_logger
    from src.common.timeutil import now_iso_utc
    print("   ✅ Core modules OK")
except Exception as e:
    print(f"   ❌ Core modules FAILED: {e}")
    errors.append(str(e))

print("\n2. Testing ingestion backends...")
try:
    from src.ingest.base import IngestBackend
    from src.ingest.opencv_reader import OpenCVReader
    from src.ingest.ffmpeg_reader import FFmpegReader
    from src.ingest.deepstream_stub import DeepStreamStub
    print("   ✅ Ingestion backends OK")
except Exception as e:
    print(f"   ❌ Ingestion backends FAILED: {e}")
    errors.append(str(e))

print("\n3. Testing detection lanes...")
try:
    from src.lanes.base import BaseLane
    from src.lanes.person_zone import PersonZoneLane
    from src.lanes.fire_smoke import FireSmokeLane
    from src.lanes.violence import ViolenceLane
    from src.lanes.vad_generic import VADGenericLane
    print("   ✅ Detection lanes OK")
except Exception as e:
    print(f"   ❌ Detection lanes FAILED: {e}")
    errors.append(str(e))

print("\n4. Testing logic components...")
try:
    from src.logic.voting import KofNVoter
    from src.logic.cooldown import CooldownManager
    from src.logic.aggregator import AlertAggregator
    from src.logic.tracker_iou import IOUTracker
    from src.logic.zones import point_in_polygon
    print("   ✅ Logic components OK")
except Exception as e:
    print(f"   ❌ Logic components FAILED: {e}")
    errors.append(str(e))

print("\n5. Testing evidence system...")
try:
    from src.evidence.ringbuffer import FrameRingBuffer
    from src.evidence.exporter import EvidenceExporter
    print("   ✅ Evidence system OK")
except Exception as e:
    print(f"   ❌ Evidence system FAILED: {e}")
    errors.append(str(e))

print("\n6. Testing API server...")
try:
    from src.api.server import AlertServer
    print("   ✅ API server OK")
except Exception as e:
    print(f"   ❌ API server FAILED: {e}")
    errors.append(str(e))

print("\n7. Checking dependencies...")
try:
    import cv2
    print(f"   ✅ OpenCV: {cv2.__version__}")
except ImportError as e:
    print(f"   ❌ OpenCV not found")
    errors.append("opencv-python not installed")

try:
    import torch
    cuda_available = torch.cuda.is_available()
    device = "CUDA" if cuda_available else "CPU"
    print(f"   ✅ PyTorch: {torch.__version__} ({device})")
except ImportError:
    print(f"   ❌ PyTorch not found")
    errors.append("torch not installed")

try:
    import ultralytics
    print(f"   ✅ Ultralytics: {ultralytics.__version__}")
except ImportError:
    print(f"   ❌ Ultralytics not found")
    errors.append("ultralytics not installed")

try:
    import fastapi
    print(f"   ✅ FastAPI: {fastapi.__version__}")
except ImportError:
    print(f"   ❌ FastAPI not found")
    errors.append("fastapi not installed")

try:
    import yaml
    print(f"   ✅ PyYAML: OK")
except ImportError:
    print(f"   ❌ PyYAML not found")
    errors.append("pyyaml not installed")

print("\n8. Checking configuration files...")
config_dir = Path(__file__).parent / "configs"
if (config_dir / "cameras.yaml").exists():
    print(f"   ✅ cameras.yaml found")
else:
    print(f"   ❌ cameras.yaml not found")
    errors.append("cameras.yaml missing")

if (config_dir / "zones.yaml").exists():
    print(f"   ✅ zones.yaml found")
else:
    print(f"   ❌ zones.yaml not found")
    errors.append("zones.yaml missing")

if (config_dir / "models.yaml").exists():
    print(f"   ✅ models.yaml found")
else:
    print(f"   ❌ models.yaml not found")
    errors.append("models.yaml missing")

print("\n9. Checking model weights...")
parent_dir = Path(__file__).parent.parent
yolov8n_path = parent_dir / "yolov8n.pt"
if yolov8n_path.exists():
    print(f"   ✅ yolov8n.pt found at {yolov8n_path}")
else:
    print(f"   ⚠️  yolov8n.pt not found (will be auto-downloaded)")

print("\n" + "=" * 60)
if errors:
    print("❌ VALIDATION FAILED")
    print("\nErrors found:")
    for err in errors:
        print(f"  - {err}")
    print("\nPlease install missing dependencies:")
    print("  pip install -r requirements.txt")
    sys.exit(1)
else:
    print("✅ VALIDATION PASSED")
    print("\nAll components are ready!")
    print("You can now run: python -m src.app")
print("=" * 60)
