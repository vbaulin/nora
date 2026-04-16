#!/bin/sh
# vision-npu/run.sh — Lean Binary Wrapper
# Usage: SKILL_BINARY_PATH=/path/to/bin SKILL_MODEL_PATH=/path/to/model ./run.sh

BIN="${SKILL_BINARY_PATH:-/usr/bin/cvi_tdl_yolo}"
MODEL="${SKILL_MODEL_PATH:-/root/models/yolov8n.cvimodel}"
IMAGE="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"

# Hardened Library Environment (Universal for LicheeRV Nano)
export SDK_PATCH=/root/libs_patch
export LD_LIBRARY_PATH=$SDK_PATCH/lib:$SDK_PATCH/middleware_v2:$SDK_PATCH/middleware_v2_3rd:$SDK_PATCH/tpu_sdk_libs:$SDK_PATCH:$SDK_PATCH/opencv

if [ ! -x "$BIN" ]; then
    echo "{\"status\":\"error\", \"message\":\"Hardware binary not found at $BIN. Please ensure it is deployed.\"}"
    exit 1
fi

OUT=$($BIN "$MODEL" "$IMAGE" 2>&1)
if [ $? -eq 0 ]; then
    echo "{\"status\":\"ok\", \"detections\":$OUT}"
else
    echo "{\"status\":\"error\", \"message\":\"Hardware failure: $OUT\"}"
fi
