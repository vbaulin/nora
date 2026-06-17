#!/bin/sh
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SKILLS_DIR="$(dirname "$BASE_DIR")"

MODEL="${SKILL_MODEL_PATH:-/root/models/agri_disease_yolo_320.cvimodel}"
IMAGE="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"
THRESHOLD="${SKILL_THRESHOLD:-0.4}"
FAMILY="${SKILL_MODEL_FAMILY:-auto}"

if [ ! -x "$SKILLS_DIR/run_yolo/run.sh" ]; then
    echo '{"status":"error","message":"run_yolo skill is not available"}'
    exit 1
fi

printf '{"backend":"maix","model_family":"%s","model_path":"%s","image_path":"%s","threshold":%s}' \
    "$FAMILY" "$MODEL" "$IMAGE" "$THRESHOLD" | "$SKILLS_DIR/run_yolo/run.sh"
