#!/bin/sh
# yolo_inference/run.sh — NPU Inference Wrapper
# Environment inputs: SKILL_IMAGE_PATH, SKILL_MODEL_PATH, SKILL_THRESHOLD

IMAGE="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"
MODEL="${SKILL_MODEL_PATH:-/root/models/yolov8n.cvimodel}"
THRESH="${SKILL_THRESHOLD:-0.5}"
BIN="/root/yolo_detect"

if [ ! -x "$BIN" ]; then
    echo '{"error": "yolo_detect binary not found at /root/yolo_detect", "status": "failed"}'
    exit 0
fi

if [ ! -f "$MODEL" ]; then
    echo '{"error": "model not found at '"$MODEL"'", "status": "failed"}'
    exit 0
fi

START=$(date +%s%N 2>/dev/null || date +%s)
# Run binary and capture output
# Assumes the binary prints JSON to stdout or can be parsed
# For demo, we simulate a parseable output if the binary isn't fully JSON-native
OUT=$($BIN "$MODEL" "$IMAGE" "$THRESH" 2>&1)
END=$(date +%s%N 2>/dev/null || date +%s)

# Calculate latency
if [ ${#START} -gt 10 ]; then
    LATENCY=$(( (END - START) / 1000000 ))
else
    LATENCY=$(( (END - START) * 1000 ))
fi

# Parsing logic depends on the specific sample_vi_od output format
# Here we return the raw output and a placeholder for structured data
# until the user provides the exact binary output format.
cat <<EOF
{
  "status": "ok",
  "latency_ms": ${LATENCY},
  "raw_output": "$(echo "$OUT" | tr '\n' ' ' | sed 's/"/\\"/g')",
  "model": "${MODEL}",
  "image": "${IMAGE}"
}
EOF
