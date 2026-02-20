"""
FastAPI server for alerts, evidence, live frame feed,
upload mode (offline video processing), and /metrics.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import List, Dict, Any, Optional
import asyncio
import json
import uuid
import time
import threading
import shutil
import cv2
import numpy as np
from ..common.log import setup_logger


class AlertServer:
    """
    FastAPI server with WebSocket support for real-time alerts.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 evidence_dir: str = "evidence", static_dir: str = None):
        self.host = host
        self.port = port
        self.evidence_dir = Path(evidence_dir)
        self.static_dir = Path(static_dir) if static_dir else Path(__file__).parent / "static"

        self.app = FastAPI(title="CCTV AI Module v2", version="2.0.0")
        self.logger = setup_logger("AlertServer")

        # WebSocket clients
        self.ws_clients: List[WebSocket] = []

        # Shared state — set by main app
        self.alert_buffer: List[Dict[str, Any]] = []
        self._camera_processors = []   # set externally for live frame
        self._aggregator = None  # live aggregator reference

        # Upload jobs
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._job_alerts: Dict[str, List[Dict[str, Any]]] = {}
        self._upload_dir = Path("uploads")
        self._upload_dir.mkdir(parents=True, exist_ok=True)

        # GPU scheduler + throttle refs (set externally)
        self._gpu_scheduler = None
        self._auto_throttle = None

        # Video processor callback (set by main app)
        self._process_video_fn = None

        # Identity subsystem refs (set externally)
        self._entity_store = None       # EntityStore
        self._face_embedder = None      # FaceEmbedder
        self._pet_embedder = None       # PetEmbedder
        self._identity_matcher = None   # IdentityMatcher
        self._identity_stabilizer = None  # IdentityStabilizer
        self._enrollment_cfg = {}       # identity.enrollment config

        # Doctor report (set externally)
        self._doctor_report = None

        self._setup_routes()

    def set_alert_buffer(self, buffer: List[Dict[str, Any]]):
        self.alert_buffer = buffer

    def set_aggregator(self, aggregator):
        """Set live aggregator reference for real-time alert access."""
        self._aggregator = aggregator

    def set_camera_processors(self, processors):
        """Accept list of CameraProcessor for live frame endpoint."""
        self._camera_processors = processors

    # ------------------------------------------------------------------
    def _setup_routes(self):

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            index_file = self.static_dir / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
            return HTMLResponse(content="<h1>CCTV AI Module v2</h1><p>UI not found</p>")

        @self.app.get("/app.js")
        async def get_app_js():
            js_file = self.static_dir / "app.js"
            if js_file.exists():
                return FileResponse(js_file)
            return HTMLResponse(content="// Not found", media_type="application/javascript")

        @self.app.get("/alerts")
        async def get_alerts(limit: int = 200):
            if self._aggregator:
                return self._aggregator.get_recent_alerts(limit)
            return self.alert_buffer[-limit:] if self.alert_buffer else []

        @self.app.get("/evidence/{camera_id}/{filename}")
        async def get_evidence(camera_id: str, filename: str):
            file_path = self.evidence_dir / camera_id / filename
            if file_path.exists():
                return FileResponse(file_path)
            return {"error": "File not found"}

        @self.app.get("/health")
        async def health():
            count = len(self._aggregator.get_recent_alerts()) if self._aggregator else len(self.alert_buffer)
            return {
                "status": "healthy",
                "alerts_count": count,
                "ws_clients": len(self.ws_clients),
            }

        @self.app.get("/cameras")
        async def cameras():
            """List active cameras with stats."""
            result = []
            for proc in self._camera_processors:
                result.append(proc.get_stats())
            return result

        @self.app.get("/frame/{camera_id}")
        async def get_frame(camera_id: str):
            """Return latest JPEG frame for a camera."""
            for proc in self._camera_processors:
                if proc.camera_id == camera_id:
                    frame, ts = proc.reader.get_latest()
                    if frame is not None:
                        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        return StreamingResponse(
                            iter([buf.tobytes()]),
                            media_type="image/jpeg",
                            headers={"X-Timestamp": ts or ""},
                        )
            return {"error": "Camera not found or no frame available"}

        # ==============================================================
        # UPLOAD MODE (Offline Video Processing) — spec §8
        # ==============================================================
        @self.app.post("/upload_video")
        async def upload_video(file: UploadFile = File(...),
                               force_anyanomaly: bool = False):
            """Upload a video file for offline processing."""
            job_id = str(uuid.uuid4())[:12]
            video_path = self._upload_dir / f"{job_id}_{file.filename}"

            # Save uploaded file
            with open(video_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            self._jobs[job_id] = {
                "job_id": job_id,
                "filename": file.filename,
                "video_path": str(video_path),
                "status": "queued",
                "progress": 0.0,
                "created_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "force_anyanomaly": force_anyanomaly,
                "alerts_count": 0,
                "error": None,
            }
            self._job_alerts[job_id] = []

            # Launch processing in background thread
            thread = threading.Thread(
                target=self._run_upload_job,
                args=(job_id,),
                daemon=True,
            )
            thread.start()

            return {"job_id": job_id, "status": "queued"}

        @self.app.get("/jobs")
        async def list_jobs():
            """List all upload jobs."""
            return list(self._jobs.values())

        @self.app.get("/jobs/{job_id}")
        async def get_job(job_id: str):
            """Get status of a specific upload job."""
            job = self._jobs.get(job_id)
            if not job:
                return {"error": "Job not found"}
            return job

        @self.app.get("/jobs/{job_id}/alerts")
        async def get_job_alerts(job_id: str):
            """Get alerts from a completed upload job."""
            if job_id not in self._jobs:
                return {"error": "Job not found"}
            return self._job_alerts.get(job_id, [])

        # ==============================================================
        # METRICS — spec addendum §5
        # ==============================================================
        @self.app.get("/metrics")
        async def get_metrics():
            """Observability: per-lane avg_ms, p95_ms, runs/min, dropped_count, queue length, per-camera effective_sample_hz."""
            metrics: Dict[str, Any] = {
                "gpu": {},
                "cameras": {},
            }

            # GPU scheduler metrics
            if self._gpu_scheduler:
                metrics["gpu"] = self._gpu_scheduler.get_metrics()

            # Per-camera effective Hz from auto-throttle
            if self._auto_throttle:
                metrics["cameras"] = self._auto_throttle.get_metrics()

            # Camera processor stats
            for proc in self._camera_processors:
                cam_id = proc.camera_id
                if cam_id not in metrics["cameras"]:
                    metrics["cameras"][cam_id] = {}
                metrics["cameras"][cam_id]["stats"] = proc.get_stats()

            return metrics

        # ==============================================================
        # FP DEBUGGING PANEL — spec §4 (fire lane debug)
        # ==============================================================
        @self.app.get("/fire_debug")
        async def fire_debug():
            """Return top N detections from fire lane for FP debugging."""
            result = []
            for proc in self._camera_processors:
                fire_lane = proc.lanes.get("fire_smoke_yolo")
                if fire_lane and hasattr(fire_lane, "last_debug_detections"):
                    result.append({
                        "camera_id": proc.camera_id,
                        "active": getattr(fire_lane, "_active", False),
                        "detections": fire_lane.last_debug_detections,
                    })
            return result

        # ==============================================================
        # IDENTITY ENROLLMENT API (spec §6 + calibration §3)
        # ==============================================================

        def _outlier_reject(embeddings: list, z_threshold: float = 2.5) -> list:
            """Remove outlier embeddings > z_threshold std dev from centroid."""
            if len(embeddings) <= 2:
                return embeddings
            matrix = np.stack(embeddings).astype(np.float32)
            centroid = np.mean(matrix, axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            sims = matrix @ centroid
            mean_sim = float(np.mean(sims))
            std_sim = float(np.std(sims))
            if std_sim < 1e-6:
                return embeddings
            kept = []
            for emb, sim in zip(embeddings, sims):
                z = (mean_sim - float(sim)) / std_sim  # lower sim → higher z
                if z <= z_threshold:
                    kept.append(emb)
            return kept if kept else embeddings  # never discard all

        @self.app.post("/entities/enroll_person")
        async def enroll_person(
            name: str = Form(...),
            role: str = Form("VISITOR"),
            metadata_json: str = Form("{}"),
            files: List[UploadFile] = File(...),
        ):
            """Enroll a person with multiple face images (min_images enforced)."""
            if self._entity_store is None or self._face_embedder is None:
                return {"error": "Identity subsystem not enabled"}

            from ..identity.schema import EntityRecord, EntityCategory

            enroll_cfg = self._enrollment_cfg
            min_images = enroll_cfg.get("min_images", 3)
            max_embeddings = enroll_cfg.get("max_embeddings_per_entity", 10)
            outlier_z = enroll_cfg.get("outlier_reject_z", 2.5)

            embeddings_list = []
            for f in files:
                img_bytes = await f.read()
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                emb = self._face_embedder.embed_from_crop(img)
                if emb is not None:
                    embeddings_list.append(emb)

            if not embeddings_list:
                return {"error": "No detectable face found in any uploaded image"}

            if len(embeddings_list) < min_images:
                return {
                    "error": f"Need at least {min_images} good face images, got {len(embeddings_list)}",
                    "faces_detected": len(embeddings_list),
                }

            # Outlier rejection
            embeddings_list = _outlier_reject(embeddings_list, outlier_z)

            # Cap at max
            embeddings_list = embeddings_list[:max_embeddings]

            entity_id = self._entity_store.generate_id()
            try:
                meta = json.loads(metadata_json)
            except Exception:
                meta = {}

            record = EntityRecord(
                entity_id=entity_id,
                name=name,
                category=EntityCategory.KNOWN_PERSON,
                role=role.upper(),
                metadata=meta,
            )
            # Store each embedding individually (multi-embed)
            self._entity_store.add_entity(record, {})
            for emb in embeddings_list:
                self._entity_store.add_embedding(entity_id, "face", emb)

            # Save enrollment images for audit
            img_dir = self._entity_store.enroll_img_dir / entity_id
            img_dir.mkdir(parents=True, exist_ok=True)
            for i, f in enumerate(files):
                await f.seek(0)
                content = await f.read()
                (img_dir / f"{i}_{f.filename}").write_bytes(content)

            # Rebuild matcher indices
            if self._identity_matcher:
                self._identity_matcher.reload_indices()

            return {"entity_id": entity_id, "name": name, "category": "KNOWN_PERSON",
                    "embeddings_stored": len(embeddings_list),
                    "outlier_rejected": 0}

        @self.app.post("/entities/enroll_pet")
        async def enroll_pet(
            name: str = Form(...),
            metadata_json: str = Form("{}"),
            files: List[UploadFile] = File(...),
        ):
            """Enroll a pet with multiple images (min_images enforced)."""
            if self._entity_store is None or self._pet_embedder is None:
                return {"error": "Identity subsystem not enabled or pet embedder unavailable"}

            from ..identity.schema import EntityRecord, EntityCategory

            enroll_cfg = self._enrollment_cfg
            min_images = enroll_cfg.get("min_images", 3)
            max_embeddings = enroll_cfg.get("max_embeddings_per_entity", 10)
            outlier_z = enroll_cfg.get("outlier_reject_z", 2.5)

            embeddings_list = []
            for f in files:
                img_bytes = await f.read()
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                emb = self._pet_embedder.embed(img)
                if emb is not None:
                    embeddings_list.append(emb)

            if not embeddings_list:
                return {"error": "Could not compute embedding for any uploaded image"}

            if len(embeddings_list) < min_images:
                return {
                    "error": f"Need at least {min_images} good pet images, got {len(embeddings_list)}",
                    "embeddings_detected": len(embeddings_list),
                }

            # Outlier rejection
            embeddings_list = _outlier_reject(embeddings_list, outlier_z)
            embeddings_list = embeddings_list[:max_embeddings]

            entity_id = self._entity_store.generate_id()
            try:
                meta = json.loads(metadata_json)
            except Exception:
                meta = {}

            record = EntityRecord(
                entity_id=entity_id,
                name=name,
                category=EntityCategory.PET,
                role="PET",
                metadata=meta,
            )
            self._entity_store.add_entity(record, {})
            for emb in embeddings_list:
                self._entity_store.add_embedding(entity_id, "pet_clip", emb)

            # Save enrollment images for audit
            img_dir = self._entity_store.enroll_img_dir / entity_id
            img_dir.mkdir(parents=True, exist_ok=True)
            for i, f in enumerate(files):
                await f.seek(0)
                content = await f.read()
                (img_dir / f"{i}_{f.filename}").write_bytes(content)

            if self._identity_matcher:
                self._identity_matcher.reload_indices()

            return {"entity_id": entity_id, "name": name, "category": "PET",
                    "embeddings_stored": len(embeddings_list)}

        @self.app.delete("/entities/{entity_id}")
        async def delete_entity(entity_id: str):
            """Remove an enrolled entity."""
            if self._entity_store is None:
                return {"error": "Identity subsystem not enabled"}
            removed = self._entity_store.remove_entity(entity_id)
            if self._identity_matcher and removed:
                self._identity_matcher.reload_indices()
            return {"removed": removed, "entity_id": entity_id}

        @self.app.get("/entities")
        async def list_entities(category: Optional[str] = Query(None)):
            """List enrolled entities."""
            if self._entity_store is None:
                return {"error": "Identity subsystem not enabled"}
            return self._entity_store.list_entities(category)

        @self.app.post("/identity/reload")
        async def reload_identity():
            """Rebuild in-memory matcher indices from DB."""
            if self._identity_matcher is None:
                return {"error": "Identity matcher not available"}
            self._identity_matcher.reload_indices()
            return {"status": "reloaded"}

        # ==============================================================
        # IDENTITY DEBUG ENDPOINT (spec §6.2)
        # ==============================================================
        @self.app.get("/identity/state")
        async def identity_state(camera_id: str = Query(...)):
            """Return current per-track identity states for a camera."""
            if self._identity_stabilizer is None:
                return {"error": "Identity stabilizer not available"}
            states = self._identity_stabilizer.get_track_states(camera_id)
            return {"camera_id": camera_id, "tracks": states}

        # ==============================================================
        # SYSTEM DIAGNOSTICS (spec §6.3)
        # ==============================================================
        @self.app.get("/system/diagnostics")
        async def system_diagnostics():
            """Return device info, ORT providers, lane status, missing assets."""
            result: Dict[str, Any] = {
                "device": {},
                "lanes": {},
                "missing_assets": [],
            }

            # Device info from doctor report
            if self._doctor_report:
                dev = self._doctor_report.device_info
                result["device"] = {
                    "torch_device": dev.torch_device,
                    "torch_version": dev.torch_version,
                    "torch_gpu": dev.torch_gpu,
                    "ort_cuda": dev.ort_cuda,
                    "gpu_usable": dev.gpu_usable,
                    "device_name": dev.device_name,
                    "ort_version": dev.ort_version,
                    "ort_providers": dev.ort_providers,
                    "ort_available_providers": dev.ort_available_providers,
                }
                result["missing_assets"] = [
                    {"config_key": m.config_key, "path": m.expected_path, "fix": m.fix_hint}
                    for m in self._doctor_report.missing
                ]

            # Lane status from camera processors
            for proc in self._camera_processors:
                cam_id = proc.camera_id
                enabled_cfg = proc.camera_cfg.get("enabled_lanes", [])
                active_lanes = list(proc.lanes.keys())
                disabled = [l for l in enabled_cfg if l not in active_lanes]
                # Collect model.names for lanes that have them (fire_smoke, weapon_yolo)
                lane_model_names: Dict[str, Any] = {}
                for lane_name, lane in proc.lanes.items():
                    if hasattr(lane, "model_names") and lane.model_names:
                        lane_model_names[lane_name] = lane.model_names
                result["lanes"][cam_id] = {
                    "enabled": active_lanes,
                    "disabled": disabled,
                    "model_names": lane_model_names,
                }

            return result

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.ws_clients.append(websocket)
            self.logger.info(f"WS client connected (total: {len(self.ws_clients)})")
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                self.ws_clients.remove(websocket)
                self.logger.info(f"WS client disconnected (remaining: {len(self.ws_clients)})")

    # ------------------------------------------------------------------
    def set_gpu_scheduler(self, scheduler):
        """Attach GPU scheduler for /metrics."""
        self._gpu_scheduler = scheduler

    def set_auto_throttle(self, throttle):
        """Attach auto-throttle for /metrics."""
        self._auto_throttle = throttle

    def set_process_video_fn(self, fn):
        """Set the callback for offline video processing."""
        self._process_video_fn = fn

    def set_doctor_report(self, report):
        """Attach startup doctor report for /system/diagnostics."""
        self._doctor_report = report

    def set_identity_components(self, store, face_embedder, pet_embedder, matcher,
                               stabilizer=None, enrollment_cfg=None):
        """Wire identity subsystem references for enrollment API."""
        self._entity_store = store
        self._face_embedder = face_embedder
        self._pet_embedder = pet_embedder
        self._identity_matcher = matcher
        self._identity_stabilizer = stabilizer
        self._enrollment_cfg = enrollment_cfg or {}

    # ------------------------------------------------------------------
    def _run_upload_job(self, job_id: str):
        """Process an uploaded video file (runs in background thread)."""
        job = self._jobs.get(job_id)
        if not job:
            return

        job["status"] = "processing"
        job["started_at"] = time.time()

        try:
            video_path = job["video_path"]
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                job["status"] = "error"
                job["error"] = "Cannot open video file"
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            job_alerts = []

            if self._process_video_fn:
                # Use main app's processor for full lane pipeline
                alerts = self._process_video_fn(
                    video_path=video_path,
                    job_id=job_id,
                    fps=fps,
                    force_anyanomaly=job.get("force_anyanomaly", False),
                    progress_callback=lambda p: job.__setitem__("progress", p),
                )
                job_alerts = alerts
            else:
                # Basic frame-by-frame stub processing
                frame_idx = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    frame_idx += 1
                    if total_frames > 0:
                        job["progress"] = round(frame_idx / total_frames * 100, 1)
                # No alerts without lane pipeline

            cap.release()

            self._job_alerts[job_id] = [a if isinstance(a, dict) else a for a in job_alerts]
            job["alerts_count"] = len(job_alerts)
            job["status"] = "completed"
            job["finished_at"] = time.time()
            job["progress"] = 100.0

            self.logger.info(f"Upload job {job_id} completed: {len(job_alerts)} alerts")

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["finished_at"] = time.time()
            self.logger.error(f"Upload job {job_id} failed: {e}")

    # ------------------------------------------------------------------
    async def broadcast_alert(self, alert: Dict[str, Any]):
        if not self.ws_clients:
            return
        message = json.dumps(alert)
        disconnected = []
        for client in self.ws_clients:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.append(client)
        for client in disconnected:
            if client in self.ws_clients:
                self.ws_clients.remove(client)

    # ------------------------------------------------------------------
    def run(self):
        import uvicorn
        self.logger.info(f"Starting server on {self.host}:{self.port}")
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
