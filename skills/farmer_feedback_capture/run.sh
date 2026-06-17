#!/bin/sh
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$BASE_DIR/run.py"
