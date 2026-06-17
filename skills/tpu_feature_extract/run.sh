#!/bin/sh
IMAGE="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"
MODEL="${SKILL_MODEL_PATH:-}"

if [ ! -f "$IMAGE" ]; then
    echo "{\"status\":\"error\",\"message\":\"image not found\",\"image_path\":\"$IMAGE\"}"
    exit 1
fi

python3 - "$IMAGE" "$MODEL" <<'PY'
import hashlib
import json
import os
import sys

image_path, model_path = sys.argv[1], sys.argv[2]
with open(image_path, "rb") as handle:
    data = handle.read()

digest = hashlib.sha256(data + model_path.encode("utf-8")).digest()
vector = [round((b / 255.0), 6) for b in digest]
print(json.dumps({
    "status": "success",
    "method": "sha256_image_embedding_fallback",
    "image_path": image_path,
    "model_path": model_path or "none",
    "dimension": len(vector),
    "embedding": vector,
    "size": os.path.getsize(image_path),
}))
PY
