#!/bin/sh
# run_yolo - Robust YOLO Orchestrator (v6.8.29 Dynamic Discovery)
# Prioritizes native CVI TDL SDK inference to avoid SIGSEGV in maix.nn.

# 1. Parse Input from stdin
INPUT=$(cat)
MODEL_PATH=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('model_path', '/root/models/yolov8n_coco_320.cvimodel'))")
IMAGE_PATH=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('image_path', '/tmp/capture.jpg'))")
THRESHOLD=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('threshold', 0.5))")

# 2. Set Hardware SDK Environment
export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

# 3. Dynamic Binary Discovery (v6.8.29)
# Instead of hardcoded paths, we probe the system
BIN_PATH=""

# A. Try 'which' for PATH-based discovery
BIN_PATH=$(which cvi_tdl_yolo 2>/dev/null || which sample_yolov8 2>/dev/null || which yolo_detect 2>/dev/null)

# B. Try Board-Specific Search Patterns if PATH fails
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

# 4. Execute Native Detection if found
if [ -n "$BIN_PATH" ]; then
    OUT=$("$BIN_PATH" "$MODEL_PATH" "$IMAGE_PATH" "$THRESHOLD" 2>&1)
    if [ $? -eq 0 ]; then
        echo "$OUT" | tee /tmp/yolo_output.txt
        exit 0
    fi
fi

# 5. Fallback to Python maix.nn
# We only reach here if native is missing OR crashed
echo "$INPUT" | python3 ./run.py | tee /tmp/yolo_output.txt
