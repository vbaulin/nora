#!/usr/bin/env bash
# Wrapper for run_tdl_detection skill
# Properly sets LD_LIBRARY_PATH and delegates to the Python inference engine

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export LD_LIBRARY_PATH="/root/cvitek-tdl-sdk-sg200x/lib:/root/cvitek-tdl-sdk-sg200x/sample/3rd/middleware/v2/lib:/root/cvitek-tdl-sdk-sg200x/sample/3rd/middleware/v2/lib/3rd:/root/libs_patch/middleware_v2_3rd/lib:/root/libs_patch/opencv:$LD_LIBRARY_PATH"

exec python3 "$SCRIPT_DIR/run.py"