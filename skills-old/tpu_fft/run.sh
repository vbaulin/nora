#!/bin/sh

# Template for TPU Math/FFT Skill
# Requires a compiled binary that links libcvimath.so

export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

INPUT=${SKILL_INPUT_FILE:-/tmp/signal.raw}
N=${SKILL_N:-1024}

# Check if the native fft binary exists (to be compiled from Cvitek SDK examples)
if [ -f "./native_fft" ]; then
    ./native_fft "$INPUT" "$N"
else
    echo "{\"status\": \"error\", \"message\": \"Native FFT binary not found. Please compile the C++ example using libcvimath.so\"}"
    exit 1
fi
