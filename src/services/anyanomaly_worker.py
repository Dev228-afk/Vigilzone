"""
AnyAnomaly subprocess worker — child process entrypoint.

Runs in a separate process to isolate AnyAnomaly dependencies and prevent
OOM/crash from affecting the main RTSP ingest loop.

IPC protocol (multiprocessing Queue):
  Request:  {job_id, camera_id, ts_utc, prompt_text, frames_b64_list}
  Response: {job_id, score, extra_debug, error}

Entrypoint is EXPLICIT — ``entry_script`` must be set in config.
If missing or not found → lane is disabled (no guessing).
"""

import sys
import os
import json
import time
import base64
import traceback
import logging
import tempfile
import subprocess
from pathlib import Path
from multiprocessing import Queue
from typing import Dict, Any, Optional, List

import numpy as np
import cv2


# ── Logging to STDOUT (avoids PowerShell NativeCommandError noise) ────
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [AnyAnomalyWorker] %(levelname)s %(message)s"
))
logger = logging.getLogger("AnyAnomalyWorker")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.propagate = False


class AnyAnomalyEngine:
    """
    Adapter for the official SkiddieAhn/Paper-AnyAnomaly repo.
    Requires ``entry_script`` in config — NO guessing.
    """

    def __init__(self, repo_dir: str, python_exe: str,
                 entry_script: str,
                 entry_args_template: str,
                 prompt_template: str, events: List[str],
                 max_clip_sec: float = 4.0, clip_fps: int = 4,
                 sensitivity: float = 0.6):
        self.repo_dir = Path(repo_dir).resolve()
        self.python_exe = python_exe
        self._entry_script_name = entry_script  # relative to repo_dir
        self._entry_args_template = entry_args_template
        self.prompt_template = prompt_template
        self.events = events
        self.max_clip_sec = max_clip_sec
        self.clip_fps = clip_fps
        self.sensitivity = sensitivity
        self.enabled = False
        self._entry_script: Optional[str] = None

    def initialize(self) -> bool:
        """Validate that repo_dir and entry_script exist."""
        if not self.repo_dir.exists():
            logger.warning(f"AnyAnomaly repo_dir not found: {self.repo_dir}")
            return False

        if not Path(self.python_exe).exists():
            self.python_exe = sys.executable
            logger.warning(f"Configured python_exe not found, using {self.python_exe}")

        if not self._entry_script_name:
            logger.warning(
                "entry_script not set in config — AnyAnomaly lane DISABLED. "
                "Set models.anyanomaly.entry_script in models.yaml."
            )
            return False

        script_path = self.repo_dir / self._entry_script_name
        if not script_path.exists():
            logger.warning(
                f"entry_script not found: {script_path} — lane DISABLED. "
                f"Available .py files in repo: "
                f"{[p.name for p in self.repo_dir.glob('*.py')]}"
            )
            return False

        self._entry_script = str(script_path)
        self.enabled = True
        logger.info(f"AnyAnomaly entry_script validated: {script_path}")
        return True

    def run_inference(self, frames_bgr: List[np.ndarray],
                      prompt_text: str) -> Dict[str, Any]:
        """
        Run AnyAnomaly inference on a clip of frames.
        Returns {"score": float, "debug": dict}.
        """
        if not self.enabled or not self._entry_script:
            return {"score": 0.0, "debug": {"error": "engine_not_initialized"}}

        # Save frames to a temp directory as numbered images
        with tempfile.TemporaryDirectory(prefix="anyanomaly_") as tmpdir:
            frame_paths = []
            for i, frame in enumerate(frames_bgr):
                fpath = os.path.join(tmpdir, f"frame_{i:04d}.jpg")
                cv2.imwrite(fpath, frame)
                frame_paths.append(fpath)

            # Build the command — pass frames dir + prompt via args
            cmd = [
                self.python_exe,
                self._entry_script,
                "--input_dir", tmpdir,
                "--prompt", prompt_text,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(self.repo_dir),
                )

                stdout = result.stdout.strip()
                stderr = result.stderr.strip()

                if result.returncode != 0:
                    logger.warning(f"AnyAnomaly script returned {result.returncode}: {stderr[:500]}")
                    # Try to extract a score from output anyway
                    score = self._parse_score(stdout)
                    return {
                        "score": score,
                        "debug": {
                            "returncode": result.returncode,
                            "stderr_tail": stderr[-200:] if stderr else "",
                        },
                    }

                score = self._parse_score(stdout)
                return {
                    "score": score,
                    "debug": {
                        "returncode": 0,
                        "raw_output": stdout[-200:] if stdout else "",
                    },
                }

            except subprocess.TimeoutExpired:
                logger.error("AnyAnomaly inference timed out (30s)")
                return {"score": 0.0, "debug": {"error": "timeout"}}
            except Exception as e:
                logger.error(f"AnyAnomaly subprocess error: {e}")
                return {"score": 0.0, "debug": {"error": str(e)}}

    def _parse_score(self, output: str) -> float:
        """Try to extract anomaly score from script output."""
        if not output:
            return 0.0
        # Try JSON first
        try:
            data = json.loads(output)
            if isinstance(data, dict):
                for key in ("score", "anomaly_score", "anomaly", "result"):
                    if key in data:
                        return float(data[key])
            elif isinstance(data, (int, float)):
                return float(data)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find a float in the last line
        lines = output.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            try:
                val = float(line)
                if 0.0 <= val <= 1.0:
                    return val
            except ValueError:
                # Try to find a number after common prefixes
                for prefix in ("score:", "anomaly:", "result:", "="):
                    if prefix in line.lower():
                        parts = line.lower().split(prefix)
                        if len(parts) > 1:
                            try:
                                val = float(parts[-1].strip().split()[0])
                                return min(max(val, 0.0), 1.0)
                            except (ValueError, IndexError):
                                pass
        return 0.0


def _decode_frames(frames_b64: List[str]) -> List[np.ndarray]:
    """Decode base64-encoded JPEG frames to numpy arrays."""
    frames = []
    for b64 in frames_b64:
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            frames.append(img)
    return frames


def worker_loop(request_queue: Queue, response_queue: Queue, config: Dict[str, Any]):
    """
    Main worker loop — runs in a child process.
    Reads requests from request_queue, processes them, writes results to response_queue.
    """
    logger.info("AnyAnomaly worker starting...")

    engine = AnyAnomalyEngine(
        repo_dir=config.get("repo_dir", "third_party/Paper-AnyAnomaly"),
        python_exe=config.get("python_exe", sys.executable),
        entry_script=config.get("entry_script", ""),
        entry_args_template=config.get("entry_args_template", ""),
        prompt_template=config.get("prompt_template", "Detect abnormal events: {events}. Return anomaly score."),
        events=config.get("events", ["fire", "smoke", "violence", "fight", "fall", "weapon", "intrusion"]),
        max_clip_sec=config.get("max_clip_sec", 4.0),
        clip_fps=config.get("clip_fps", 4),
        sensitivity=config.get("sensitivity", 0.6),
    )

    initialized = engine.initialize()
    if not initialized:
        logger.warning("AnyAnomaly engine could not initialize — running in stub mode")

    # Signal ready
    response_queue.put({"type": "status", "enabled": engine.enabled})

    while True:
        try:
            request = request_queue.get(timeout=5.0)
        except Exception:
            continue

        if request is None:  # Poison pill → shutdown
            logger.info("Received shutdown signal")
            break

        job_id = request.get("job_id", "unknown")
        camera_id = request.get("camera_id", "unknown")
        ts_utc = request.get("ts_utc", "")
        prompt_text = request.get("prompt_text", "")
        frames_b64 = request.get("frames_b64_list", [])

        t0 = time.perf_counter()

        try:
            if not engine.enabled:
                # Stub mode — return zero score
                response_queue.put({
                    "type": "result",
                    "job_id": job_id,
                    "camera_id": camera_id,
                    "score": 0.0,
                    "extra_debug": {"stub": True, "reason": "engine_not_available"},
                    "error": None,
                })
                continue

            frames = _decode_frames(frames_b64)
            if not frames:
                response_queue.put({
                    "type": "result",
                    "job_id": job_id,
                    "camera_id": camera_id,
                    "score": 0.0,
                    "extra_debug": {"error": "no_valid_frames"},
                    "error": "no_valid_frames",
                })
                continue

            # Build prompt from template + events
            events_str = ", ".join(engine.events)
            prompt = engine.prompt_template.format(events=events_str)
            if prompt_text:
                prompt = prompt_text  # override if caller provided custom prompt

            result = engine.run_inference(frames, prompt)
            dt = time.perf_counter() - t0

            result["debug"]["inference_ms"] = round(dt * 1000, 1)

            response_queue.put({
                "type": "result",
                "job_id": job_id,
                "camera_id": camera_id,
                "score": result["score"],
                "extra_debug": result["debug"],
                "error": None,
            })

        except Exception as e:
            logger.error(f"Worker error for job {job_id}: {e}\n{traceback.format_exc()}")
            response_queue.put({
                "type": "result",
                "job_id": job_id,
                "camera_id": camera_id,
                "score": 0.0,
                "extra_debug": {"error": str(e)},
                "error": str(e),
            })


if __name__ == "__main__":
    """
    Can be launched directly for testing:
      python -m src.services.anyanomaly_worker --config path/to/models.yaml
    """
    import yaml

    config_path = "configs/models.yaml"
    if len(sys.argv) > 2 and sys.argv[1] == "--config":
        config_path = sys.argv[2]

    with open(config_path) as f:
        full_cfg = yaml.safe_load(f)

    aa_cfg = full_cfg.get("models", {}).get("anyanomaly", {})

    req_q: Queue = Queue()
    res_q: Queue = Queue()

    worker_loop(req_q, res_q, aa_cfg)
