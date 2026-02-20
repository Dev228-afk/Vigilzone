# VigilZone AI Module

Real-time CCTV anomaly detection module for Windows 10/11. Part of a larger
surveillance platform. Supports **RTSP cameras** and **live USB/webcam** feeds,
with multiple detection lanes running in parallel per camera.

---

## Features

- **Dual input** – RTSP streams *or* USB/laptop webcam (live_camera)
- **RT-DETR primary detector** via TensorRT FP16 → ONNX GPU → ONNX CPU cascade
- **YOLOv8 fallback** – works instantly with no extra model files
- **Fire / Smoke** dedicated YOLO lane
- **AnyAnomaly** heavy feature-based anomaly detector
- **AnomalyCLIP** lighter CLIP-based anomaly scorer
- **Temporal Verifier** (X3D-S / VideoSwin) for clip-level confirmation
- **K-of-N voting** (default 3/5) + **cooldown** (45 s) + **session deduplication**
- **Evidence** – 5 s pre + 5 s post clip, partial_clip flag when timeout
- **Per-lane Hz scheduling** (detector 2 Hz, anomaly 0.5 Hz, temporal 0.2 Hz)
- **Web UI** with live camera sidebar, severity filters, session_id, lane_votes,
  temporal verifier badges
- **WebSocket** real-time push + REST API

---

## Architecture

```
ai_module/
├── configs/
│   ├── cameras.yaml      # Camera sources, per-lane Hz, evidence settings
│   ├── models.yaml        # Model paths, TensorRT config, thresholds
│   └── zones.yaml         # Polygon zones per camera
├── src/
│   ├── common/            # types, config loader, logging, timeutil
│   ├── ingest/            # OpenCV, FFmpeg, live_camera, DeepStream stub
│   ├── lanes/             # rt_detr, yolov8_fallback, fire_smoke_yolo,
│   │                      #   anyanomaly, anomalyclip, temporal_verifier,
│   │                      #   person_zone, fire_smoke, violence, vad_generic
│   ├── logic/             # aggregator, voting, cooldown, deduper,
│   │                      #   engine_loader, tracker_iou, zones
│   ├── evidence/          # ring buffer (20 s) + exporter (5+5 s)
│   └── api/               # FastAPI server + static Web UI
├── models/                # Drop ONNX / TRT engine files here
├── tools/                 # onnx_to_trt.py conversion script
├── evidence/              # Runtime evidence output (auto-created)
├── alerts/                # JSONL alert logs (auto-created)
├── run.py                 # Entry point
└── requirements.txt
```

---

## Quick Start

### 1. Install PyTorch

```bash
# CPU only
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# CUDA 11.8
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 2. Install dependencies

```bash
cd ai_module
pip install -r requirements.txt
```

### 3. Choose input source

**Live webcam (default)** — no config change needed.
`configs/cameras.yaml` ships with `cam_live` using device index 0.

**RTSP camera** — comment out the live-camera block and uncomment the RTSP
block in `cameras.yaml`:

```yaml
cameras:
  - camera_id: cam1
    rtsp_url: "rtsp://admin:pass@192.168.1.100:554/stream1"
    ingest_backend: opencv
    # ... rest of config
```

### 4. Run

```bash
python run.py
```

### 5. Open the UI

**http://127.0.0.1:8080**

---

## Detection Lanes

| Lane                 | Alert Type                 | Severity | Model                  |
|----------------------|----------------------------|----------|------------------------|
| `rt_detr`            | *dynamic from label*       | varies   | RT-DETR (TRT/ONNX)    |
| `yolov8_fallback`    | *dynamic from label*       | varies   | YOLOv8n               |
| `fire_smoke_yolo`    | FIRE_SMOKE                 | SEVERE   | YOLO fire/smoke        |
| `anyanomaly`         | UNKNOWN_SEVERE_ANOMALY     | HIGH     | AnyAnomaly checkpoint  |
| `anomalyclip`        | UNKNOWN_SEVERE_ANOMALY     | HIGH     | AnomalyCLIP            |
| `temporal_verifier`  | (confirms other alerts)    | —        | X3D-S / VideoSwin      |
| `person_zone`        | INTRUSION_PERSON_IN_ZONE   | MED      | YOLOv8/v12 + IoU track |
| `fire_smoke`         | FIRE_SMOKE                 | SEVERE   | Legacy YOLO            |
| `violence`           | VIOLENCE_FIGHT             | SEVERE   | Motion stub            |
| `vad_generic`        | UNKNOWN_SEVERE_ANOMALY     | HIGH     | Motion stub            |

Lanes marked *stub* use motion-energy heuristics until real model weights are
provided.

---

## Engine Loader (TensorRT / ONNX cascade)

The `engine_loader` module tries in order:
1. **TensorRT FP16** engine (if `tensorrt` installed + `.engine` file exists)
2. **ONNX on GPU** (if `onnxruntime-gpu` installed + `.onnx` file exists)
3. **ONNX on CPU** (if `onnxruntime` installed + `.onnx` file exists)
4. **Stub** — returns empty detections (allows system to run with no models)

### Converting ONNX → TensorRT

```bash
python tools/onnx_to_trt.py \
    --onnx models/rt_detr.onnx \
    --output models/rt_detr_fp16.engine
```

Or use trtexec directly:
```bash
trtexec --onnx=models/rt_detr.onnx --saveEngine=models/rt_detr_fp16.engine --fp16
```

---

## Alert Schema (v2)

```json
{
  "ts_utc": "2026-02-12T10:15:30.123Z",
  "camera_id": "cam_live",
  "type": "VIOLENCE_FIGHT",
  "severity": "SEVERE",
  "confidence": 0.87,
  "session_id": "a1b2c3d4e5f67890",
  "label": "fighting",
  "k_of_n": {"k": 3, "n": 5, "hits": 3},
  "cooldown_s": 45,
  "evidence": {
    "keyframe_path": "evidence/cam_live/..._VIOLENCE.jpg",
    "clip_path": "evidence/cam_live/..._VIOLENCE.mp4",
    "partial_clip": false
  },
  "payload": {
    "bboxes": [[100, 150, 200, 300]],
    "lane_votes": [
      {"lane": "rt_detr", "conf": 0.91},
      {"lane": "yolov8_fallback", "conf": 0.85}
    ],
    "temporal_verifier": {
      "ran": true,
      "confirmed": true,
      "score": 0.78
    },
    "zone_name": "lobby",
    "track_id": 42
  },
  "debug": {}
}
```

---

## API Endpoints

| Method  | Path                           | Description                     |
|---------|--------------------------------|---------------------------------|
| GET     | `/`                            | Web UI dashboard                |
| GET     | `/alerts?limit=200`            | Recent alerts (JSON)            |
| GET     | `/cameras`                     | Active camera list + stats      |
| GET     | `/frame/{camera_id}`           | Latest JPEG frame               |
| GET     | `/evidence/{cam_id}/{file}`    | Serve evidence files            |
| GET     | `/health`                      | Health check                    |
| WS      | `/ws`                          | Real-time alert push            |

---

## Configuration

### cameras.yaml

```yaml
cameras:
  - camera_id: cam_live
    source_type: live_camera
    camera_index: 0             # webcam device index
    sample_hz:
      detector_primary: 2
      detector_fallback: 2
      fire_smoke: 2
      anomaly_generic: 0.5
      temporal_verifier: 0.2
    enabled_lanes:
      - rt_detr
      - yolov8_fallback
      - fire_smoke_yolo
      - anyanomaly
      - anomalyclip
      - temporal_verifier
      - person_zone
    cooldown_s: 45
    k_of_n: [3, 5]
    evidence:
      pre_s: 5
      post_s: 5
```

### models.yaml

Contains paths and thresholds for all detectors:
- `tensorrt.enabled` / `tensorrt.fp16`
- `rt_detr.onnx_path` / `rt_detr.trt_engine_path`
- `yolov8.weights` / `yolov8.conf`
- `fire_yolov8.weights`
- `anyanomaly.model_path` / `anyanomaly.sensitivity`
- `anomalyclip.model_path` / `anomalyclip.sensitivity`
- `temporal_verifier.kind` / `temporal_verifier.conf`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Model weights not found" | Drop `.pt`/`.onnx` files in `models/` or parent dir; update `models.yaml` |
| Webcam not detected | Check `camera_index` in `cameras.yaml` (try 0, 1, 2) |
| RTSP connection drops | System auto-reconnects; verify URL/network |
| Port 8080 in use | Change port in `src/app.py` → `AlertServer(port=XXXX)` |
| GPU not detected | Install CUDA PyTorch; set `device: cpu` in `models.yaml` |
| TensorRT not available | System falls back to ONNX → CPU; no action needed |

---

## Entity-Aware Identity Workflow

The system supports enrolling known persons and pets, then automatically
recognising them at runtime to suppress or escalate alerts.

### Runtime Pipeline

```
1. Detector (RT-DETR / YOLOv8) produces persons/animals + track_id
2. Identity lane crops face/pet region → computes embedding
3. IdentityMatcher compares embedding against enrolled vectors (cosine sim)
4. IdentityStabilizer converts noisy per-frame matches into a stable
   identity per track_id using M-of-L voting + lock + decay
5. Aggregator uses entity identity for severity/suppression:
   - UNKNOWN_PERSON in restricted zone → HIGH
   - KNOWN_OWNER / FAMILY           → LOW or suppress (policy-driven)
   - PET (enrolled)                  → suppress pet alerts
6. Alert JSON includes entity{id, name, category, confidence}
   and payload.identity debug stats (best_sim, margin, quality_ok, locked)
```

### Enrollment API

| Endpoint                       | Method           | Description                          |
| ------------------------------ | ---------------- | ------------------------------------ |
| `/entities`                    | GET              | List all enrolled entities           |
| `/entities/enroll_person`      | POST (multipart) | Enroll person with face images       |
| `/entities/enroll_pet`         | POST (multipart) | Enroll pet with images               |
| `/entities/{entity_id}`        | DELETE           | Remove an enrolled entity            |
| `/identity/reload`             | POST             | Rebuild matcher indices after changes |
| `/identity/state?camera_id=X`  | GET              | Per-track identity debug state       |

### UI

The web UI at `http://localhost:8080` has three tabs:

- **Alerts** – real-time and upload alerts with entity badge + identity debug
- **Entities** – list, enroll person/pet, delete enrolled entities
- **Identity Live** – poll per-track identity state for any camera

---

## Adding a New Lane

1. Create `src/lanes/my_lane.py` extending `BaseLane`
2. Register in `LANE_REGISTRY` dict in `src/app.py`
3. Map lane → alert type in `LANE_TO_ALERT_TYPE` in `src/logic/aggregator.py`
4. Add lane name to `enabled_lanes` in `cameras.yaml`

---

## License

MIT
