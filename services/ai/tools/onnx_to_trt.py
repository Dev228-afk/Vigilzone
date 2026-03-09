#!/usr/bin/env python3
"""
tools/onnx_to_trt.py
Convert an ONNX model to a TensorRT FP16 engine.

Usage:
    python tools/onnx_to_trt.py --onnx models/rt_detr.onnx --output models/rt_detr_fp16.engine
    python tools/onnx_to_trt.py --onnx models/rt_detr.onnx --output models/rt_detr_fp16.engine --fp32

Requirements:
    - NVIDIA GPU with TensorRT installed
    - tensorrt Python package
"""

import argparse
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("onnx_to_trt")


def convert(onnx_path: str, output_path: str, fp16: bool = True, max_batch: int = 1,
            workspace_gb: float = 4.0):
    """Convert ONNX → TensorRT engine."""
    try:
        import tensorrt as trt  # type: ignore
    except ImportError:
        log.error("tensorrt Python package not installed. Install with:")
        log.error("  pip install tensorrt")
        log.error("Or use trtexec CLI:")
        log.error(f"  trtexec --onnx={onnx_path} --saveEngine={output_path} --fp16")
        sys.exit(1)

    if not os.path.isfile(onnx_path):
        log.error(f"ONNX file not found: {onnx_path}")
        sys.exit(1)

    TRT_LOGGER = trt.Logger(trt.Logger.INFO)

    log.info(f"Building TensorRT engine from: {onnx_path}")
    log.info(f"FP16: {fp16} | Max batch: {max_batch} | Workspace: {workspace_gb} GB")

    builder = trt.Builder(TRT_LOGGER)
    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(network_flags)
    parser = trt.OnnxParser(network, TRT_LOGGER)

    # Parse ONNX
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                log.error(f"ONNX parse error: {parser.get_error(i)}")
            sys.exit(1)

    log.info(f"ONNX parsed successfully. Inputs: {network.num_inputs}, Outputs: {network.num_outputs}")

    # Print input/output info
    for i in range(network.num_inputs):
        inp = network.get_input(i)
        log.info(f"  Input [{i}]: {inp.name} shape={inp.shape} dtype={inp.dtype}")
    for i in range(network.num_outputs):
        out = network.get_output(i)
        log.info(f"  Output [{i}]: {out.name} shape={out.shape} dtype={out.dtype}")

    # Build config
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(workspace_gb * (1 << 30)))

    if fp16 and builder.platform_has_fast_fp16:
        log.info("Enabling FP16 mode")
        config.set_flag(trt.BuilderFlag.FP16)
    elif fp16:
        log.warning("FP16 requested but not supported by this GPU. Using FP32.")

    # Set dynamic batch if needed
    profile = builder.create_optimization_profile()
    for i in range(network.num_inputs):
        inp = network.get_input(i)
        shape = list(inp.shape)
        if shape[0] == -1:  # dynamic batch
            min_shape = [1] + shape[1:]
            opt_shape = [1] + shape[1:]
            max_shape = [max_batch] + shape[1:]
            profile.set_shape(inp.name, min_shape, opt_shape, max_shape)
            log.info(f"  Dynamic batch for '{inp.name}': min={min_shape}, opt={opt_shape}, max={max_shape}")
    config.add_optimization_profile(profile)

    # Build engine
    log.info("Building engine... (this may take several minutes)")
    serialized_engine = builder.build_serialized_network(network, config)

    if serialized_engine is None:
        log.error("Failed to build TensorRT engine!")
        sys.exit(1)

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(serialized_engine)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    log.info(f"Engine saved: {output_path} ({size_mb:.1f} MB)")
    log.info("Done!")


def main():
    parser = argparse.ArgumentParser(description="Convert ONNX model to TensorRT engine")
    parser.add_argument("--onnx", required=True, help="Path to input ONNX model")
    parser.add_argument("--output", required=True, help="Path to output TensorRT engine")
    parser.add_argument("--fp32", action="store_true", help="Disable FP16, use FP32 instead")
    parser.add_argument("--max-batch", type=int, default=1, help="Maximum batch size (default: 1)")
    parser.add_argument("--workspace", type=float, default=4.0, help="Workspace size in GB (default: 4)")
    args = parser.parse_args()

    convert(
        onnx_path=args.onnx,
        output_path=args.output,
        fp16=not args.fp32,
        max_batch=args.max_batch,
        workspace_gb=args.workspace,
    )


if __name__ == "__main__":
    main()
