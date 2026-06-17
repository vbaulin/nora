#!/bin/sh
# vision_state_sync/run.sh — Orchestrate capture and inference

# 1. Capture Image
# The orchestrator handles native capture_image mostly, but we can call it here via CLI if needed
# For now, we assume capture.jpg already exist or we trigger it.
# We'll call the internal tools via the engine's provided mechanism conceptually.

# Since this is a shell skill, we'll try to use ffmpeg/v4l2 directly if engine didn't provide one
IMAGE="/tmp/vision_sync.jpg"

# Try capture
v4l2-ctl --device=/dev/video0 --set-fmt-video=width=640,height=480,pixelformat=MJPG --stream-mmap=3 --stream-to=$IMAGE --stream-count=1 2>/dev/null || \
ffmpeg -y -f v4l2 -video_size 640x480 -i /dev/video0 -frames:v 1 $IMAGE 2>/dev/null

if [ ! -f "$IMAGE" ]; then
    echo '{"error": "capture failed", "status": "failed"}'
    exit 0
fi

# 2. Run Inference
# We call the yolo_inference skill conceptually, but here we run it directly or via engine call
# For shell scripts in skills/, we can't easily call other skills via engine internal API
# unless we go through the MCP port or just run the binary again.

MODEL="/root/models/yolov8n.cvimodel"
BIN="/root/yolo_detect"

if [ -x "$BIN" ] && [ -f "$MODEL" ]; then
    INF_OUT=$($BIN "$MODEL" "$IMAGE" 0.5 2>/dev/null | tr '\n' ' ')
    echo '{"status": "ok", "image": "'"$IMAGE"'", "detections": "'"$INF_OUT"'"}'
else
    echo '{"status": "partial", "image": "'"$IMAGE"'", "error": "npu_binary_missing"}'
fi
