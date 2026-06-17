#!/bin/sh
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SKILLS_DIR="$(dirname "$BASE_DIR")"

MODEL="${SKILL_MODEL_PATH:-/root/models/yolov8_pose_320.cvimodel}"
IMAGE="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"
THRESHOLD="${SKILL_THRESHOLD:-0.5}"

if [ ! -x "$SKILLS_DIR/run_yolo/run.sh" ]; then
    echo '{"status":"error","message":"run_yolo skill is not available"}'
    exit 1
fi

printf '{"backend":"maix","model_family":"auto","model_path":"%s","image_path":"%s","threshold":%s}' \
    "$MODEL" "$IMAGE" "$THRESHOLD" | "$SKILLS_DIR/run_yolo/run.sh"
