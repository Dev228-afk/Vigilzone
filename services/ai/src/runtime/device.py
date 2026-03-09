"""
Centralized device selection — single source of truth for torch device
and ONNX Runtime providers across all lanes and subsystems.

torch CUDA and ORT CUDA are probed **independently**.
  • ``torch_gpu``  — True when ``torch.cuda.is_available()``
  • ``ort_cuda``   — True when ORT CUDAExecutionProvider actually works

Either may be True while the other is False. e.g. torch may be CPU-only
while onnxruntime-gpu is installed → InsightFace can still use ORT CUDA.

Usage:
    from src.runtime.device import select_device, DeviceInfo
    dev = select_device(models_cfg)
    # dev.torch_device  →  "cuda:0" or "cpu"
    # dev.ort_providers →  ["CUDAExecutionProvider", "CPUExecutionProvider"] or ["CPUExecutionProvider"]
    # dev.torch_gpu     →  True / False  (torch CUDA available)
    # dev.ort_cuda      →  True / False  (ORT CUDA available)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from ..common.log import setup_logger

logger = setup_logger("DeviceSelect")

# Module-level singleton — populated on first call to select_device()
_cached: DeviceInfo | None = None
_ort_cuda_probed: bool | None = None  # None = not tested yet
_nvidia_dlls_patched: bool = False


# ======================================================================
# NVIDIA DLL path patching  (MUST run before any ORT / CUDA import)
# ======================================================================
def _patch_nvidia_dll_paths() -> List[str]:
    """
    Discover all ``nvidia/*/bin`` directories inside ``site-packages``
    (from the ``nvidia-cudnn-cu12``, ``nvidia-cublas-cu12`` etc. pip
    packages) and prepend them to ``os.environ["PATH"]`` so that ORT and
    cuDNN DLLs are found at runtime.

    Also calls ``os.add_dll_directory()`` on Python ≥ 3.8 / Windows so
    that ``ctypes`` and ``LoadLibrary`` searches work.

    Returns the list of directories added.
    """
    global _nvidia_dlls_patched
    if _nvidia_dlls_patched:
        return []

    added: List[str] = []

    # Locate site-packages/nvidia
    try:
        import nvidia  # type: ignore
        nvidia_root = Path(nvidia.__path__[0])  # …/site-packages/nvidia
    except (ImportError, AttributeError, IndexError):
        # nvidia meta-package not installed → nothing to patch
        _nvidia_dlls_patched = True
        return added

    # Walk each sub-package looking for a ``bin/`` with DLLs
    if nvidia_root.is_dir():
        for sub in sorted(nvidia_root.iterdir()):
            bin_dir = sub / "bin"
            if bin_dir.is_dir() and any(bin_dir.glob("*.dll")):
                dir_str = str(bin_dir)
                if dir_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = dir_str + os.pathsep + os.environ.get("PATH", "")
                    added.append(dir_str)
                # Python ≥ 3.8 on Windows: register for LoadLibrary
                if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(dir_str)
                    except OSError:
                        pass

    if added:
        logger.info(f"Patched DLL search path with {len(added)} NVIDIA dirs")

    _nvidia_dlls_patched = True
    return added


# Run the PATH patch immediately on module import — before any ORT import
_patch_nvidia_dll_paths()


# ======================================================================
# ORT CUDA probe (subprocess, safe against hard crashes)
# ======================================================================
def _probe_ort_cuda() -> bool:
    """
    Verify that ORT CUDAExecutionProvider actually works by running a
    tiny ONNX session in a **subprocess**.

    Why subprocess?  ORT loads cuDNN lazily; if the DLLs are absent the
    C runtime calls ``abort()`` (exit code 0xC0000409), which kills the
    entire process and cannot be caught by Python ``try/except``.
    A subprocess isolates that crash.

    The subprocess inherits our patched PATH so cuDNN DLLs are visible.
    """
    global _ort_cuda_probed
    if _ort_cuda_probed is not None:
        return _ort_cuda_probed

    import subprocess, textwrap

    probe_script = textwrap.dedent("""\
        import sys, os
        # Patch NVIDIA DLL paths inside the subprocess too
        try:
            import nvidia
            from pathlib import Path
            nvidia_root = Path(nvidia.__path__[0])
            for sub in sorted(nvidia_root.iterdir()):
                bin_dir = sub / "bin"
                if bin_dir.is_dir():
                    d = str(bin_dir)
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try: os.add_dll_directory(d)
                        except OSError: pass
        except Exception:
            pass

        try:
            import onnxruntime as ort, numpy as np
            # Minimal ONNX graph: identity op on a 1-element float tensor
            import onnx
            from onnx import helper, TensorProto
            X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [1])
            Y = helper.make_tensor_value_info('Y', TensorProto.FLOAT, [1])
            node = helper.make_node('Identity', ['X'], ['Y'])
            graph = helper.make_graph([node], 'probe', [X], [Y])
            model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 11)])
            model.ir_version = 8
            raw = model.SerializeToString()
            sess = ort.InferenceSession(raw, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
            out = sess.run(None, {'X': np.array([1.0], dtype=np.float32)})
            actual = sess.get_providers()
            if 'CUDAExecutionProvider' in actual:
                print('OK')
                sys.exit(0)
            else:
                print('FALLBACK')
                sys.exit(1)
        except Exception as e:
            print(f'ERR:{e}')
            sys.exit(1)
    """)

    try:
        result = subprocess.run(
            [sys.executable, "-c", probe_script],
            capture_output=True, text=True, timeout=30,
            env=os.environ.copy(),  # inherit patched PATH
        )
        ok = result.returncode == 0 and "OK" in result.stdout
        if ok:
            logger.info("ORT CUDA probe: CUDAExecutionProvider works ✓")
        else:
            stdout = result.stdout.strip()[:300]
            stderr = result.stderr.strip()[:300]
            logger.warning(f"ORT CUDA probe failed (rc={result.returncode}): {stdout} | {stderr}")
        _ort_cuda_probed = ok
        return ok
    except Exception as e:
        logger.warning(f"ORT CUDA probe exception: {e}")
        _ort_cuda_probed = False
        return False


@dataclass(frozen=True)
class DeviceInfo:
    torch_device: str          # "cuda:0" or "cpu"
    ort_providers: List[str]   # ordered list for onnxruntime sessions
    torch_gpu: bool            # True iff torch.cuda.is_available()
    ort_cuda: bool             # True iff ORT has CUDAExecutionProvider
    gpu_usable: bool           # True iff EITHER torch_gpu OR ort_cuda
    torch_version: str
    cuda_available: bool       # alias for torch_gpu (back-compat)
    device_name: str           # GPU name or "N/A"
    ort_version: str
    ort_available_providers: List[str]


def select_device(config: Dict[str, Any], *, force_refresh: bool = False) -> DeviceInfo:
    """
    Determine the best device given config["device"] (auto | cuda | cpu).

    **Decoupled logic**:
      • ``torch_device`` depends only on ``torch.cuda.is_available()``.
      • ``ort_providers`` depends only on whether ``CUDAExecutionProvider``
        appears in ``ort.get_available_providers()``.
      They are set independently — one can be GPU while the other is CPU.

    Returns a ``DeviceInfo`` that every lane / subsystem should use.
    Results are cached per-process (singleton).
    """
    global _cached
    if _cached is not None and not force_refresh:
        return _cached

    device_pref: str = config.get("device", "auto")

    # ── Torch ──────────────────────────────────────────────────────
    torch_version = "N/A"
    torch_gpu = False
    device_name = "N/A"
    try:
        import torch
        torch_version = torch.__version__
        torch_gpu = torch.cuda.is_available()
        if torch_gpu:
            device_name = torch.cuda.get_device_name(0)
    except ImportError:
        logger.warning("PyTorch not installed — torch GPU unavailable")

    # ── ONNX Runtime ───────────────────────────────────────────────
    ort_version = "N/A"
    ort_available: List[str] = []
    try:
        import onnxruntime as ort
        ort_version = ort.__version__
        ort_available = ort.get_available_providers()
    except ImportError:
        logger.warning("onnxruntime not installed")

    ort_cuda_ok = "CUDAExecutionProvider" in ort_available

    # Probe that ORT CUDA actually works (cuDNN present, etc.)
    # get_available_providers() may report CUDA even when cuDNN DLLs are
    # missing, which causes a hard C-level crash on session creation.
    if ort_cuda_ok:
        ort_cuda_ok = _probe_ort_cuda()
        if not ort_cuda_ok:
            logger.warning(
                "ORT lists CUDAExecutionProvider but it crashed during probe "
                "(likely missing cuDNN DLLs). Falling back to CPUExecutionProvider."
            )

    # ── Apply user preference — DECOUPLED ─────────────────────────
    if device_pref == "cpu":
        torch_device = "cpu"
        ort_providers: List[str] = ["CPUExecutionProvider"]
        # Force both flags off
        torch_gpu = False
        ort_cuda_ok = False
    elif device_pref in ("cuda", "auto"):
        # Torch side — independent
        torch_device = "cuda:0" if torch_gpu else "cpu"
        # ORT side — independent
        if ort_cuda_ok:
            ort_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            ort_providers = ["CPUExecutionProvider"]
    else:
        # Assume raw device string (e.g. "cuda:1")
        torch_device = device_pref
        if ort_cuda_ok:
            ort_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            ort_providers = ["CPUExecutionProvider"]

    # gpu_usable = at least one backend has CUDA
    gpu_usable = torch_gpu or ort_cuda_ok

    # ── Advisory warnings ──────────────────────────────────────────
    if torch_gpu and not ort_cuda_ok:
        logger.warning(
            "torch.cuda is available but ORT lacks CUDAExecutionProvider. "
            "Install onnxruntime-gpu for ORT GPU acceleration."
        )
    if ort_cuda_ok and not torch_gpu:
        logger.info(
            "ORT has CUDAExecutionProvider but torch is CPU-only. "
            "Ultralytics lanes will run on CPU; ORT-based models (InsightFace) "
            "will use GPU. Install CUDA-enabled PyTorch for full GPU."
        )
    if not torch_gpu and not ort_cuda_ok:
        logger.info(
            "No GPU backend detected — running fully on CPU. "
            "Install CUDA-enabled PyTorch and/or onnxruntime-gpu for GPU."
        )

    info = DeviceInfo(
        torch_device=torch_device,
        ort_providers=ort_providers,
        torch_gpu=torch_gpu,
        ort_cuda=ort_cuda_ok,
        gpu_usable=gpu_usable,
        torch_version=torch_version,
        cuda_available=torch_gpu,   # back-compat alias
        device_name=device_name,
        ort_version=ort_version,
        ort_available_providers=ort_available,
    )

    logger.info(
        f"Device selected — torch: {torch_device} (gpu={torch_gpu}), "
        f"ORT: {ort_providers} (cuda={ort_cuda_ok})"
    )

    _cached = info
    return info
