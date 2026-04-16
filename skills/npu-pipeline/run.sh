#!/bin/sh
# npu-pipeline/run.sh — Lean Binary Wrapper (Streaming)
# Usage: SKILL_BINARY_PATH=/path/to/pipeline SKILL_RTSP_URL=rtsp://... ./run.sh

BIN="${SKILL_BINARY_PATH:-/usr/bin/npu_pipeline}"
URL="${SKILL_RTSP_URL:-rtsp://127.0.0.1:8554/live}"
MODEL="${SKILL_MODEL_PATH:-/root/models/yolov8n.cvimodel}"

# Hardened Library Environment
export SDK_PATCH=/root/libs_patch
export LD_LIBRARY_PATH=$SDK_PATCH/lib:$SDK_PATCH/middleware_v2:$SDK_PATCH/middleware_v2_3rd:$SDK_PATCH/tpu_sdk_libs:$SDK_PATCH:$SDK_PATCH/opencv

if [ ! -x "$BIN" ]; then
    echo "{\"status\":\"error\", \"message\":\"Hardware pipeline binary not found at $BIN.\"}"
    exit 1
fi

# Launch asynchronous stream
nohup "$BIN" "$URL" "$MODEL" > /tmp/npu_pipeline.log 2>&1 &
PID=$!

echo "{\"status\":\"running\", \"pid\":$PID, \"url\":\"$URL\"}"
