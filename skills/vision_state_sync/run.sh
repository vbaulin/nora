#!/bin/sh
# vision_state_sync - current camera -> Maix YOLO skill chain.
# This deliberately avoids v4l2/ffmpeg/direct NPU commands.

BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SKILLS_DIR="$(dirname "$BASE_DIR")"
IMAGE="${SKILL_IMAGE_PATH:-/tmp/vision_sync.jpg}"
MODEL="${SKILL_MODEL_PATH:-/root/models/yolov8n_coco_320.cvimodel}"
THRESHOLD="${SKILL_THRESHOLD:-0.5}"
FAMILY="${SKILL_MODEL_FAMILY:-auto}"

CAPTURE_JSON="/tmp/vision_state_capture_$$.json"
YOLO_JSON="/tmp/vision_state_yolo_$$.json"

cleanup() {
    rm -f "$CAPTURE_JSON" "$YOLO_JSON"
}
trap cleanup EXIT

if [ ! -x "$SKILLS_DIR/capture_image/run.py" ]; then
    echo '{"status":"error","message":"capture_image skill runner missing"}'
    exit 1
fi
if [ ! -x "$SKILLS_DIR/run_yolo/run.sh" ]; then
    echo '{"status":"error","message":"run_yolo skill runner missing"}'
    exit 1
fi

printf '{"output_path":"%s"}' "$IMAGE" | python3 "$SKILLS_DIR/capture_image/run.py" > "$CAPTURE_JSON" 2>&1

CAPTURE_STATUS=$(python3 - "$CAPTURE_JSON" <<'PY'
import json, sys
raw = open(sys.argv[1], errors="ignore").read()
start, end = raw.find("{"), raw.rfind("}")
if start >= 0 and end > start:
    try:
        print(json.loads(raw[start:end+1]).get("status", "error"))
    except Exception:
        print("error")
else:
    print("error")
PY
)

if [ "$CAPTURE_STATUS" != "success" ]; then
    python3 - "$CAPTURE_JSON" <<'PY'
import json, sys
raw = open(sys.argv[1], errors="ignore").read()
print(json.dumps({"status": "error", "stage": "capture", "message": raw[-1000:]}))
PY
    exit 0
fi

printf '{"image_path":"%s","model_path":"%s","threshold":%s,"model_family":"%s","backend":"maix","capture":false}' \
    "$IMAGE" "$MODEL" "$THRESHOLD" "$FAMILY" | "$SKILLS_DIR/run_yolo/run.sh" > "$YOLO_JSON" 2>&1

python3 - "$CAPTURE_JSON" "$YOLO_JSON" "$IMAGE" <<'PY'
import json
import sys

def load(path):
    raw = open(path, errors="ignore").read()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end+1])
        except Exception:
            pass
    return {"status": "error", "message": raw[-1000:]}

capture = load(sys.argv[1])
yolo = load(sys.argv[2])
status = "success" if capture.get("status") == "success" and yolo.get("status") == "success" else "partial"
print(json.dumps({
    "status": status,
    "image_path": sys.argv[3],
    "capture": capture,
    "yolo": yolo,
    "object_count": yolo.get("count", 0) if isinstance(yolo, dict) else 0,
}))
PY
