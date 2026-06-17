#!/usr/bin/env bash
# Wrapper script for run_opencv_detection skill
# Provides backward compatibility for tasks expecting .sh extension

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/run.py" "$@"