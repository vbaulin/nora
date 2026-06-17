#!/bin/sh
# run_yolo - Canonical Maix-Python YOLO orchestrator.
# Maix Python is the primary supported path for YOLOv8/YOLOv11-style
# .cvimodel inference. Native CVI/TDL binaries remain an optional fallback.
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# 1. Parse Input from stdin
INPUT=$(cat)
BACKEND=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('backend', 'maix'))")
MODEL_PATH=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('model_path', '/root/models/yolov8n_coco_320.cvimodel'))")
IMAGE_PATH=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('image_path', '/tmp/capture.jpg'))")
THRESHOLD=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('threshold', 0.5))")

# 2. Maix Python is now the preferred working path.
if [ "$BACKEND" != "native" ]; then
    MAIX_LIB="/usr/lib/python3.11/site-packages/maix/dl_lib"
    OUT=$(echo "$INPUT" | env LD_LIBRARY_PATH="$MAIX_LIB:/usr/lib:/lib:/lib64" python3 "$SCRIPT_DIR/run.py" 2>&1)
    STATUS=$?
    if [ $STATUS -eq 0 ] && echo "$OUT" | grep -q '"status": "success"'; then
        echo "$OUT" | tee /tmp/yolo_output.txt
        exit 0
    fi
    if [ "$BACKEND" = "maix" ]; then
        printf '%s' "$OUT" > /tmp/yolo_output.txt
        python3 - "$STATUS" "$MODEL_PATH" "$IMAGE_PATH" <<'PY'
import json
import sys

status = int(sys.argv[1])
model_path = sys.argv[2]
image_path = sys.argv[3]
raw = open("/tmp/yolo_output.txt", errors="ignore").read()
print(json.dumps({
    "status": "error",
    "backend": "maix_python",
    "returncode": status,
    "signal": "SIGSEGV" if status in (139, -11) or "SIGSEGV" in raw else "",
    "message": raw[-1200:] or "maix yolo failed",
    "model_path": model_path,
    "image_path": image_path,
}))
PY
        exit 0
    fi
fi

# 3. Optional native fallback for explicit backend=native or backend=auto.
export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

BIN_PATH=""
BIN_PATH=$(which cvi_tdl_yolo 2>/dev/null || which sample_yolov8 2>/dev/null || which yolo_detect 2>/dev/null)

if [ -z "$BIN_PATH" ]; then
    for p in "/root/libs_patch/bin/sample_yolov8" \
             "/root/libs_patch/bin/cvi_tdl_yolo" \
             "/usr/bin/sample_yolov8" \
             "/usr/bin/cvi_tdl_yolo" \
             "/root/yolo_detect" \
             "/mnt/system/usr/bin/cvi_tdl_yolo"; do
        if [ -x "$p" ]; then
            BIN_PATH="$p"
            break
        fi
    done
fi

if [ -n "$BIN_PATH" ]; then
    OUT=$("$BIN_PATH" "$MODEL_PATH" "$IMAGE_PATH" "$THRESHOLD" 2>&1)
    if [ $? -eq 0 ]; then
        echo "$OUT" | tee /tmp/yolo_output.txt
        exit 0
    fi
fi

echo "{\"status\":\"error\",\"message\":\"YOLO failed: Maix path failed and no native fallback succeeded\",\"backend\":\"$BACKEND\",\"model_path\":\"$MODEL_PATH\",\"image_path\":\"$IMAGE_PATH\"}"
