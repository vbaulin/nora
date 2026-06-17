#!/bin/sh

export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

OUT=${SKILL_OUTPUT:-/tmp/capture.jpg}
W=${SKILL_WIDTH:-1920}
H=${SKILL_HEIGHT:-1080}

# Try standard Cvitek sensor test binary
if [ -f "/root/sensor_test" ]; then
    /root/sensor_test -c 0 -o "$OUT" -w "$W" -h "$H" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "{\"status\": \"ok\", \"path\": \"$OUT\"}"
        exit 0
    fi
fi

# Fallback to sample_vi
if [ -f "/usr/bin/sample_vi" ]; then
    /usr/bin/sample_vi "$OUT" >/dev/null 2>&1
    echo "{\"status\": \"ok\", \"path\": \"$OUT\"}"
    exit 0
fi

echo "{\"status\": \"error\", \"message\": \"No native capture binary found\"}"
exit 1
