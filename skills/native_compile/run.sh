#!/bin/sh

# Set Gold Standard Environment for Compiling
export TOOLCHAIN=/root/licheerv-toolchain/riscv64-linux-musl-x86_64/bin
export PATH=$PATH:$TOOLCHAIN
export LD_LIBRARY_PATH=/root/libs_patch/tpu_sdk_libs:/root/libs_patch/lib:/root/libs_patch/middleware_v2:/root/libs_patch/middleware_v2_3rd:/root/libs_patch:/root/libs_patch/opencv:/lib:/lib64

SOURCE=${SKILL_SOURCE_FILE:-/tmp/skill.cpp}
OUTPUT=${SKILL_OUTPUT_BIN:-/tmp/skill.bin}
LIBS=${SKILL_LIBS:-"-lcvi_tdl -lcvi_ive_tpu -lcviruntime"}

if [ ! -f "$SOURCE" ]; then
    echo "{\"status\": \"error\", \"message\": \"Source file $SOURCE not found\"}"
    exit 1
fi

# Determine compiler (g++ for C++)
COMPILER="g++"
if [ ! -x "$TOOLCHAIN/$COMPILER" ]; then
    # Fallback to system g++ if toolchain path differs
    COMPILER=$(command -v g++)
fi

if [ -z "$COMPILER" ]; then
    echo "{\"status\": \"error\", \"message\": \"No C++ compiler found in toolchain or system PATH\"}"
    exit 1
fi

# Compile with Gold Standard flags
# -I for headers, -L for libraries
$COMPILER "$SOURCE" -o "$OUTPUT" \
    -I/root/opencv-mobile-4.10.0-licheerv-nano/include/opencv4/ \
    -I/root/libs_patch/include \
    -L/root/libs_patch/lib -L/root/libs_patch/tpu_sdk_libs -L/root/libs_patch/middleware_v2 \
    $LIBS \
    -lpthread -ldl

if [ $? -eq 0 ]; then
    echo "{\"status\": \"ok\", \"binary\": \"$OUTPUT\"}"
else
    echo "{\"status\": \"error\", \"message\": \"Compilation failed\"}"
    exit 1
fi
