#!/bin/sh
# npu_info/run.sh — Check NPU status using native tools
# Usage: SKILL_MODEL_PATH=/path/to/model.cvimodel ./run.sh

TPU_DEV="/dev/cvitpu0"
STATUS="missing"
PROBE_INFO=""

# Hardened Library Environment
export SDK_PATCH=/root/libs_patch
export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

if [ -e "$TPU_DEV" ]; then
    STATUS="available"
    # Use cvimodel_tool if a model is provided for probing
    if [ -n "$SKILL_MODEL_PATH" ] && [ -f "$SKILL_MODEL_PATH" ]; then
        PROBE_INFO=$(/usr/bin/cvimodel_tool -i "$SKILL_MODEL_PATH" 2>&1 | grep -E "Chip|Version|Output" | xargs)
    fi
fi

cat <<EOF
{
  "device": "${TPU_DEV}",
  "status": "${STATUS}",
  "probe": "${PROBE_INFO:-N/A}",
  "libs": "${LD_LIBRARY_PATH}"
}
EOF
