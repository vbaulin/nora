#!/bin/sh

BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUTPUT_DIR="${SKILL_OUTPUT_DIR:-/tmp/observations}"
LABEL="${SKILL_LABEL:-scene}"
MODEL_PATH="${SKILL_MODEL_PATH:-/root/models/yolov8n_coco_320.cvimodel}"
THRESHOLD="${SKILL_THRESHOLD:-0.5}"
TS="$(date +%Y%m%d_%H%M%S)"
SAFE_LABEL="$(echo "$LABEL" | tr -c 'A-Za-z0-9_-' '_')"
IMAGE_PATH="${OUTPUT_DIR}/${SAFE_LABEL}_${TS}.jpg"
CAPTURE_JSON="/tmp/observe_capture_${TS}.json"
YOLO_JSON="/tmp/observe_yolo_${TS}.json"
COLOR_JSON="/tmp/observe_color_${TS}.json"

mkdir -p "$OUTPUT_DIR"

printf '{"output_path":"%s"}' "$IMAGE_PATH" | python3 "$BASE_DIR/../capture_image/run.py" > "$CAPTURE_JSON" 2>&1
CAPTURE_STATUS=$?

if [ "$CAPTURE_STATUS" -eq 0 ] && grep -q '"status"[[:space:]]*:[[:space:]]*"success"' "$CAPTURE_JSON"; then
  printf '{"image_path":"%s","model_path":"%s","threshold":%s}' "$IMAGE_PATH" "$MODEL_PATH" "$THRESHOLD" | "$BASE_DIR/../run_yolo/run.sh" > "$YOLO_JSON" 2>&1
else
  printf '{"status":"skipped","message":"capture failed"}' > "$YOLO_JSON"
fi

if [ -x "$BASE_DIR/../agri_color_index/run.py" ] || [ -f "$BASE_DIR/../agri_color_index/run.py" ]; then
  printf '{"image_path":"%s"}' "$IMAGE_PATH" | python3 "$BASE_DIR/../agri_color_index/run.py" > "$COLOR_JSON" 2>&1
else
  printf '{"status":"skipped","message":"agri_color_index unavailable"}' > "$COLOR_JSON"
fi

python3 - "$CAPTURE_JSON" "$YOLO_JSON" "$COLOR_JSON" "$IMAGE_PATH" "$LABEL" <<'PY'
import json, sys, time

def load(path):
    try:
        raw = open(path).read()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        return {"status": "error", "message": raw[-400:]}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

capture = load(sys.argv[1])
yolo = load(sys.argv[2])
color = load(sys.argv[3])
ok = capture.get("status") == "success"
print(json.dumps({
    "status": "success" if ok else "error",
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "label": sys.argv[5],
    "image_path": sys.argv[4],
    "capture": capture,
    "yolo": yolo,
    "color": color,
    "object_count": yolo.get("count", 0) if isinstance(yolo, dict) else 0
}))
PY
