"""
Validation script — verifies all AI module components can be imported.
Run this before starting the main application:  python validate.py
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

print("=" * 60)
print("  VigilZone AI Module — Validation")
print("=" * 60)

errors: list[str] = []


def _section(n: int, title: str) -> None:
    print(f"\n{n}. {title}")


def _ok(msg: str) -> None:
    print(f"   ✅ {msg}")


def _fail(msg: str, err=None) -> None:
    detail = f": {err}" if err else ""
    text = f"{msg}{detail}"
    print(f"   ❌ {text}")
    errors.append(text)


def _warn(msg: str) -> None:
    print(f"   ⚠️  {msg}")


# ── 1. Core imports ──────────────────────────────────────────────
_section(1, "Core imports")
try:
    from src.common.types import Observation, Alert          # noqa: F401
    from src.common.config import Config                     # noqa: F401
    from src.common.log import setup_logger                  # noqa: F401
    from src.common.timeutil import now_iso_utc              # noqa: F401
    _ok("common (types, config, log, timeutil)")
except Exception as e:
    _fail("common modules", e)

# ── 2. Ingestion backends ────────────────────────────────────────
_section(2, "Ingestion backends")
try:
    from src.ingest.opencv_reader import OpenCVReader         # noqa: F401
    from src.ingest.ffmpeg_reader import FFmpegReader         # noqa: F401
    from src.ingest.deepstream_stub import DeepStreamStub     # noqa: F401
    from src.ingest.live_camera import LiveCameraReader       # noqa: F401
    _ok("OpenCV, FFmpeg, DeepStream stub, LiveCamera")
except Exception as e:
    _fail("Ingestion backends", e)

# ── 3. Detection lanes ──────────────────────────────────────────
_section(3, "Detection lanes")
import importlib

_lane_imports = {
    "rt_detr":              "src.lanes.rt_detr",
    "yolov8_fallback":      "src.lanes.yolov8_fallback",
    "yolov8_pose":          "src.lanes.yolov8_pose",
    "person_zone":          "src.lanes.person_zone",
    "fire_smoke_yolo":      "src.lanes.fire_smoke_yolo",
    "weapon_yolo":          "src.lanes.weapon_yolo",
    "violence_candidate":   "src.lanes.violence_candidate",
    "fall_candidate":       "src.lanes.fall_candidate",
    "temporal_verifier":    "src.lanes.temporal_verifier",
    "anomalyclip":          "src.lanes.anomalyclip",
    "anyanomaly":           "src.lanes.anyanomaly",
    "entity_identity":      "src.lanes.entity_identity",
    "accident":             "src.lanes.accident",
    "vad_generic":          "src.lanes.vad_generic",
}
ok_lanes, fail_lanes = 0, 0
for name, mod in _lane_imports.items():
    try:
        importlib.import_module(mod)
        ok_lanes += 1
    except Exception as e:
        _fail(f"lane/{name}", e)
        fail_lanes += 1
if ok_lanes:
    _ok(f"{ok_lanes} lanes OK")

# ── 4. Logic components ─────────────────────────────────────────
_section(4, "Logic components")
try:
    from src.logic.voting import KofNVoter                    # noqa: F401
    from src.logic.cooldown import CooldownManager            # noqa: F401
    from src.logic.aggregator import AlertAggregator          # noqa: F401
    from src.logic.tracker_iou import IOUTracker              # noqa: F401
    from src.logic.zones import point_in_polygon              # noqa: F401
    from src.logic.deduper import Deduper                      # noqa: F401
    from src.logic.detection_cache import FrameDetectionCache # noqa: F401
    _ok("voting, cooldown, aggregator, tracker, zones, deduper, cache")
except Exception as e:
    _fail("Logic components", e)

# ── 5. Identity subsystem ───────────────────────────────────────
_section(5, "Identity subsystem")
try:
    from src.identity.face_embedder import FaceEmbedder       # noqa: F401
    from src.identity.matcher import IdentityMatcher           # noqa: F401
    from src.identity.store import EntityStore                 # noqa: F401
    from src.identity.policy import IdentityPolicy             # noqa: F401
    _ok("face_embedder, matcher, store, policy")
except Exception as e:
    _fail("Identity subsystem", e)

# ── 6. Incidents framework ──────────────────────────────────────
_section(6, "Incidents framework")
try:
    from src.incidents.base import IncidentDefinition          # noqa: F401
    from src.incidents.state import IncidentState              # noqa: F401
    from src.incidents.registry import IncidentRegistry        # noqa: F401
    _ok("base (IncidentDefinition), state, registry")
except Exception as e:
    _fail("Incidents framework", e)

# ── 7. Evidence system ──────────────────────────────────────────
_section(7, "Evidence system")
try:
    from src.evidence.ringbuffer import FrameRingBuffer        # noqa: F401
    from src.evidence.exporter import EvidenceExporter          # noqa: F401
    _ok("ringbuffer, exporter")
except Exception as e:
    _fail("Evidence system", e)

# ── 8. API server ───────────────────────────────────────────────
_section(8, "API server")
try:
    from src.api.server import AlertServer                     # noqa: F401
    _ok("FastAPI AlertServer (port 8080)")
except Exception as e:
    _fail("API server", e)

# ── 9. Runtime ──────────────────────────────────────────────────
_section(9, "Runtime")
try:
    from src.runtime.device import select_device               # noqa: F401
    from src.runtime.gpu_scheduler import GPUScheduler         # noqa: F401
    _ok("device, gpu_scheduler")
except Exception as e:
    _fail("Runtime modules", e)

# ── 10. Third-party dependencies ────────────────────────────────
_section(10, "Dependencies")
_deps = {
    "cv2":          ("OpenCV",      lambda m: m.__version__),
    "torch":        ("PyTorch",     lambda m: f"{m.__version__} ({'CUDA' if m.cuda.is_available() else 'CPU'})"),
    "ultralytics":  ("Ultralytics", lambda m: m.__version__),
    "fastapi":      ("FastAPI",     lambda m: m.__version__),
    "yaml":         ("PyYAML",      lambda m: "OK"),
    "numpy":        ("NumPy",       lambda m: m.__version__),
}
for mod_name, (label, ver_fn) in _deps.items():
    try:
        mod = importlib.import_module(mod_name)
        _ok(f"{label}: {ver_fn(mod)}")
    except ImportError:
        _fail(f"{label} not installed")

# ── 11. Configuration files ─────────────────────────────────────
_section(11, "Configuration files")
cfg_dir = _ROOT / "configs"
for name in ("cameras.yaml", "models.yaml", "zones.yaml", "policy.yaml"):
    if (cfg_dir / name).exists():
        _ok(name)
    else:
        _fail(f"{name} missing")

# ── 12. Model weights ──────────────────────────────────────────
_section(12, "Model weights (models/ directory)")
models_dir = _ROOT / "models"
_expected_weights = {
    "yolov8n.pt":          "YOLOv8 fallback / person detector",
    "yolov8n-pose.pt":     "YOLOv8 pose estimation",
    "rtdetr-l.pt":         "RT-DETR legacy fallback",
    "fire_yolov8.pt":      "Fire/smoke detector",
    "weapon_yolov8.pt":    "Weapon detector",
    "rtdetrv2_r101vd_6x_coco_from_paddle.pth": "RTDETRv2 primary detector",
}
for fname, desc in _expected_weights.items():
    if (models_dir / fname).exists():
        _ok(f"{fname} — {desc}")
    else:
        _warn(f"{fname} not found — {desc} (may auto-download)")

# ── Summary ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
if errors:
    print(f"❌ VALIDATION FAILED — {len(errors)} error(s)")
    for e in errors:
        print(f"   • {e}")
    print("\nFix issues above, then re-run:  python validate.py")
    sys.exit(1)
else:
    print("✅ VALIDATION PASSED — all components ready")
    print("\nStart the module:  python run.py")
print("=" * 60)
