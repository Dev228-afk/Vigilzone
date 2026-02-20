"""
Engine loader — cascade: TensorRT FP16 → ONNX GPU → ONNX CPU → Ultralytics .pt → Stub

Provides a uniform ``DetectorEngine.infer(frame_bgr) → List[Detection]`` interface
regardless of which backend actually runs.

For the Ultralytics .pt step the loader imports:
    from ultralytics import RTDETR
    model = RTDETR("rtdetr-l.pt")
which is the spec-mandated Phase-1 approach.

Singleton caching: ``load_detector_engine()`` returns the same engine instance
for identical config (keyed on weights path) to avoid duplicate loads.
"""
import time
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..common.log import setup_logger

logger = setup_logger("EngineLoader")

# Singleton cache: weights_key → DetectorEngine
_engine_cache: Dict[str, "DetectorEngine"] = {}

# ---------------------------------------------------------------------------
# Uniform detection result
# ---------------------------------------------------------------------------

class Detection:
    """Single detection result."""
    __slots__ = ("bbox", "score", "label")

    def __init__(self, bbox: List[float], score: float, label: str):
        self.bbox = bbox      # [x1, y1, x2, y2]
        self.score = score
        self.label = label

    def to_dict(self) -> Dict[str, Any]:
        return {"bbox": self.bbox, "score": self.score, "label": self.label}


# ---------------------------------------------------------------------------
# DetectorEngine ABC
# ---------------------------------------------------------------------------

class DetectorEngine:
    """Uniform detector interface regardless of backend."""

    def __init__(self, runtime: str = "none"):
        self.runtime = runtime
        self._logger = setup_logger(f"DetectorEngine-{runtime}")

    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        raise NotImplementedError

    def warmup(self):
        pass


# ---------------------------------------------------------------------------
# TensorRT Engine
# ---------------------------------------------------------------------------

class TensorRTEngine(DetectorEngine):
    """Loads a pre-built TensorRT engine file (.engine)."""

    def __init__(self, engine_path: str, classes: List[str],
                 score_threshold: float = 0.15, input_size: tuple = (640, 640)):
        super().__init__(runtime="tensorrt_fp16")
        self.engine_path = engine_path
        self.classes = classes
        self.score_threshold = score_threshold
        self.input_size = input_size
        self._engine = None
        self._context = None
        self._load()

    def _load(self):
        try:
            import tensorrt as trt                               # noqa
            import pycuda.driver as cuda                         # noqa
            import pycuda.autoinit                               # noqa

            trt_logger = trt.Logger(trt.Logger.WARNING)
            with open(self.engine_path, "rb") as f:
                engine_data = f.read()
            runtime_obj = trt.Runtime(trt_logger)
            self._engine = runtime_obj.deserialize_cuda_engine(engine_data)
            self._context = self._engine.create_execution_context()
            self._logger.info(f"TensorRT engine loaded: {self.engine_path}")
        except Exception as e:
            self._logger.error(f"TensorRT load failed: {e}")
            raise

    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        import cv2
        try:
            import pycuda.driver as cuda                         # noqa

            img = cv2.resize(frame_bgr, self.input_size)
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)[np.newaxis, ...]
            img = np.ascontiguousarray(img)

            # NOTE: Full TRT binding allocation deferred to production engine setup.
            detections: List[Detection] = []
            return detections
        except Exception as e:
            self._logger.error(f"TensorRT infer error: {e}")
            return []


# ---------------------------------------------------------------------------
# ONNX Runtime Engine
# ---------------------------------------------------------------------------

class ONNXEngine(DetectorEngine):
    """Loads an ONNX model via onnxruntime (GPU or CPU)."""

    def __init__(self, onnx_path: str, classes: List[str],
                 score_threshold: float = 0.15, use_gpu: bool = False,
                 input_size: tuple = (640, 640)):
        runtime_str = "onnx_gpu" if use_gpu else "onnx_cpu"
        super().__init__(runtime=runtime_str)
        self.onnx_path = onnx_path
        self.classes = classes
        self.score_threshold = score_threshold
        self.input_size = input_size
        self._session = None
        self._load(use_gpu)

    def _load(self, use_gpu: bool):
        try:
            import onnxruntime as ort
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if use_gpu else ["CPUExecutionProvider"]
            )
            self._session = ort.InferenceSession(self.onnx_path, providers=providers)
            actual = self._session.get_providers()
            self._logger.info(f"ONNX session created ({actual}): {self.onnx_path}")
        except Exception as e:
            self._logger.error(f"ONNX load failed: {e}")
            raise

    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        import cv2
        try:
            img = cv2.resize(frame_bgr, self.input_size)
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)[np.newaxis, ...]
            img = np.ascontiguousarray(img)

            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: img})
            return self._parse_outputs(outputs, frame_bgr.shape[:2])
        except Exception as e:
            self._logger.error(f"ONNX infer error: {e}")
            return []

    def _parse_outputs(self, outputs, orig_shape) -> List[Detection]:
        detections: List[Detection] = []
        try:
            preds = outputs[0]
            if preds.ndim == 3:
                preds = preds[0]
            h_orig, w_orig = orig_shape
            for row in preds:
                box = row[:4]
                scores = row[4:]
                max_idx = int(np.argmax(scores))
                max_score = float(scores[max_idx])
                if max_score < self.score_threshold:
                    continue
                label = self.classes[max_idx] if max_idx < len(self.classes) else f"class_{max_idx}"
                x1 = float(box[0]) * w_orig / self.input_size[0]
                y1 = float(box[1]) * h_orig / self.input_size[1]
                x2 = float(box[2]) * w_orig / self.input_size[0]
                y2 = float(box[3]) * h_orig / self.input_size[1]
                detections.append(Detection([x1, y1, x2, y2], max_score, label))
        except Exception as e:
            self._logger.warning(f"Output parse error: {e}")
        return detections


# ---------------------------------------------------------------------------
# Ultralytics RTDETR Engine  ← Phase-1 default
# ---------------------------------------------------------------------------

class UltralyticsRTDETREngine(DetectorEngine):
    """Uses ``from ultralytics import RTDETR`` as mandated by spec."""

    def __init__(self, weights: str, score_threshold: float = 0.15,
                 device: str = "cpu"):
        super().__init__(runtime="ultralytics_rtdetr_pt")
        self.weights = weights
        self.score_threshold = score_threshold
        self.device = device
        self._model = None
        self._load()

    def _load(self):
        try:
            from ultralytics import RTDETR          # spec-mandated import
            self._model = RTDETR(self.weights)
            self._logger.info(f"Ultralytics RTDETR loaded: {self.weights}")
        except Exception as e:
            self._logger.error(f"Ultralytics RTDETR load failed: {e}")
            raise

    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        if self._model is None:
            return []
        try:
            # Ultralytics requires device= in predict(); .to() alone is insufficient
            ul_device = 0 if self.device.startswith("cuda") else "cpu"
            results = self._model(frame_bgr, conf=self.score_threshold,
                                  device=ul_device, verbose=False)
            detections: List[Detection] = []
            for r in results:
                boxes = r.boxes
                if boxes is None:
                    continue
                for i in range(len(boxes)):
                    xyxy = boxes.xyxy[i].tolist()
                    conf = float(boxes.conf[i])
                    cls_id = int(boxes.cls[i])
                    label = r.names.get(cls_id, f"class_{cls_id}")
                    detections.append(Detection(xyxy, conf, label))
            return detections
        except Exception as e:
            self._logger.error(f"Ultralytics RTDETR infer error: {e}")
            return []


# ---------------------------------------------------------------------------
# Stub Engine (no model, returns empty)
# ---------------------------------------------------------------------------

class StubEngine(DetectorEngine):
    """Placeholder engine when no model file is available."""

    def __init__(self, reason: str = "model file not found"):
        super().__init__(runtime="stub")
        self._logger.warning(f"Using STUB engine: {reason}")

    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        return []


# ---------------------------------------------------------------------------
# Public loader function
# ---------------------------------------------------------------------------

def load_detector_engine(models_cfg: Dict[str, Any]) -> DetectorEngine:
    """
    Load the best available RT-DETR engine using the spec cascade:
        1. TensorRT FP16 engine
        2. ONNX GPU
        3. ONNX CPU
        4. Ultralytics .pt   ← Phase-1 default
        5. Stub               ← if nothing works

    Reads from models_cfg dict (device, tensorrt, models.rt_detr).

    **Singleton**: returns the same engine if already loaded with identical weights.
    """
    rt_detr_cfg = models_cfg.get("models", {}).get("rt_detr", {})
    weights_pt = rt_detr_cfg.get("weights", "rtdetr-l.pt")

    # ── Singleton check ──
    cache_key = str(Path(weights_pt).resolve()) if Path(weights_pt).is_absolute() else weights_pt
    if cache_key in _engine_cache:
        logger.info(f"Reusing cached engine for {cache_key}")
        return _engine_cache[cache_key]
    device_pref = models_cfg.get("device", "auto")
    trt_cfg = models_cfg.get("tensorrt", {})
    rt_detr_cfg = models_cfg.get("models", {}).get("rt_detr", {})

    classes = rt_detr_cfg.get("classes", ["person"])
    score_threshold = rt_detr_cfg.get("score_threshold", 0.15)
    trt_engine_path = rt_detr_cfg.get("trt_engine_path", "")
    onnx_path = rt_detr_cfg.get("onnx_path", "")
    weights_pt = rt_detr_cfg.get("weights", "rtdetr-l.pt")

    # Determine CUDA availability — use centralized device selection
    cuda_available = False
    device_str = "cpu"
    try:
        from ..runtime.device import select_device
        dev = select_device(models_cfg)
        cuda_available = dev.torch_gpu
        device_str = dev.torch_device
    except Exception:
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_str = "cuda"
            if device_pref == "cpu":
                cuda_available = False
                device_str = "cpu"
        except ImportError:
            pass

    # 1. Try TensorRT
    if trt_cfg.get("enabled", False) and cuda_available and Path(trt_engine_path).exists():
        try:
            engine = TensorRTEngine(trt_engine_path, classes, score_threshold)
            logger.info(f"✅ Loaded TensorRT FP16 engine: {trt_engine_path}")
            _engine_cache[cache_key] = engine
            return engine
        except Exception as e:
            logger.warning(f"TensorRT load failed, falling back: {e}")

    # 2. Try ONNX GPU
    if cuda_available and onnx_path and Path(onnx_path).exists():
        try:
            engine = ONNXEngine(onnx_path, classes, score_threshold, use_gpu=True)
            logger.info(f"✅ Loaded ONNX (GPU): {onnx_path}")
            _engine_cache[cache_key] = engine
            return engine
        except Exception as e:
            logger.warning(f"ONNX GPU load failed, falling back: {e}")

    # 3. Try ONNX CPU
    if onnx_path and Path(onnx_path).exists():
        try:
            engine = ONNXEngine(onnx_path, classes, score_threshold, use_gpu=False)
            logger.info(f"✅ Loaded ONNX (CPU): {onnx_path}")
            _engine_cache[cache_key] = engine
            return engine
        except Exception as e:
            logger.warning(f"ONNX CPU load failed: {e}")

    # 4. Try Ultralytics .pt (Phase-1 default)
    try:
        engine = UltralyticsRTDETREngine(weights_pt, score_threshold, device_str)
        logger.info(f"✅ Loaded Ultralytics RTDETR (.pt): {weights_pt}")
        _engine_cache[cache_key] = engine
        return engine
    except Exception as e:
        logger.warning(f"Ultralytics RTDETR load failed: {e}")

    # 5. Stub
    reason = "All RT-DETR backends failed — detector_primary disabled"
    logger.warning(f"⚠️  {reason}")
    return StubEngine(reason)
