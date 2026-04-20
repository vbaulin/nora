#!/bin/sh

# Set the hardware SDK environment verified for LicheeRV Nano
export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

MODEL=${SKILL_MODEL_PATH:-/root/models/yolov8n_coco_320.cvimodel}
IMAGE=${SKILL_IMAGE_PATH:-/tmp/capture.jpg}
THRESH=${SKILL_THRESHOLD:-0.5}

# Find the best binary
BIN_PATH=""
for p in /root/libs_patch/bin/sample_yolov8 /root/libs_patch/bin/cvi_tdl_yolo /usr/bin/sample_yolov8 /usr/bin/cvi_tdl_yolo; do
    if [ -f "$p" ]; then
        BIN_PATH="$p"
        break
    fi
done

if [ -z "$BIN_PATH" ]; then
    echo "{\"status\": \"error\", \"message\": \"Native YOLO binary not found in SDK paths\"}"
    exit 1
fi

# Execute native detection
# Note: Sophgo binaries typically output results to stdout which we parse in Go
"$BIN_PATH" "$MODEL" "$IMAGE" "$THRESH"
