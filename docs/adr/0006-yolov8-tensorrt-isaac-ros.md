# ADR 0006: YOLOv8 via TensorRT served by Isaac ROS

**Status**: accepted · **Date**: 2026-05-21

## Context

Human detection is the primary perception task. Hardware target is Jetson Orin Nano (~40 TOPS INT8). Hard requirement: YOLO. Mission profile (outdoor SAR at altitude) needs ≥15 FPS at 1280×720 to keep up with flight motion.

## Decision

- Model family: **YOLOv8** (Ultralytics, ~30k★). Variants: `yolov8n` for followers, `yolov8s` for leader.
- Optimization: compile to **TensorRT engine** (`.engine`) per-Jetson at first boot.
- Serving: **`isaac_ros_yolov8`** (NVIDIA Isaac ROS) for the Jetson runtime path; Ultralytics-native Python node for x86/CI fallback.
- Weights versioning: Git LFS + SHA256 in `config/models/manifest.yaml`.

## Rationale

- Hard requirement constrains the model family.
- Ultralytics YOLOv8 is the canonical implementation; well-supported export to ONNX → TensorRT.
- Isaac ROS provides a GPU-accelerated ROS 2 node graph (NVIDIA-ISAAC-ROS/isaac_ros_object_detection) — measurably 3× faster than calling Ultralytics from a Python ROS node, hitting 30+ FPS on Orin Nano.
- TensorRT engines are not portable across Jetson generations; build at deploy time, not in CI.

## Consequences

- Two code paths: `yolo_detector_node.py` selects backend by env var (`SWARM_YOLO_BACKEND=isaac_ros|ultralytics`). Same ROS interface.
- Model fine-tuning for aerial SAR is v2.1 work; v2.0.0 ships stock COCO-pretrained `yolov8n` and `yolov8s` and depends on the "person" class.
- `scripts/build/build_yolo_tensorrt.sh` runs at first boot on each Jetson (cached in `/var/lib/orynth/models/`).
- Image input pipeline must be GPU-resident on Jetson (NVMM buffers). Detection output is the ROS 2 message — no images leave the inference graph except the operator-selected H.264 stream.
