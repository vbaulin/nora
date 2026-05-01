#!/bin/sh

CANDIDATE="${SKILL_CANDIDATE_PATH}"
TARGET_NAME="${SKILL_TARGET_NAME}"
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ -z "$CANDIDATE" ] || [ -z "$TARGET_NAME" ]; then
  echo '{"status":"error","message":"candidate_path and target_name are required"}'
  exit 1
fi

case "$TARGET_NAME" in
  *[!A-Za-z0-9_-]*|"")
    echo '{"status":"error","message":"target_name must be alphanumeric/underscore/hyphen"}'
    exit 1
    ;;
esac

if [ ! -d "$CANDIDATE" ] || [ ! -f "$CANDIDATE/SKILL.md" ]; then
  echo '{"status":"error","message":"candidate skill directory or SKILL.md missing"}'
  exit 1
fi

TARGET="${BASE_DIR}/${TARGET_NAME}"
if [ -e "$TARGET" ]; then
  echo "{\"status\":\"error\",\"message\":\"target already exists\",\"target_path\":\"$TARGET\"}"
  exit 1
fi

mkdir -p "$TARGET"
cp -R "$CANDIDATE"/. "$TARGET"/
find "$TARGET" -name '*.sh' -exec chmod 755 {} \; 2>/dev/null
find "$TARGET" -name '*.py' -exec chmod 755 {} \; 2>/dev/null

echo "{\"status\":\"success\",\"target_path\":\"$TARGET\",\"target_name\":\"$TARGET_NAME\"}"
