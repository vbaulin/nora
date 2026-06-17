#!/usr/bin/env python3
"""
run_tdl_detection - NPU-accelerated detection using CVI TDL SDK on SG2002

Takes JSON via stdin or file path via argv[1].
Uses pre-compiled TDL SDK executables.

Working modes:
  - fd: Face Detection using scrfd model ✅
  - hand_cls: Hand Classification (partial) ⚠️
"""
import os
import json
import subprocess
import sys


def first_existing(candidates):
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.dirname(SCRIPT_DIR)

# Delegate to the canonical inference engine when it exists. Older board
# research used "vision-npu"; this repo uses "vision_npu", so check both.
INFERENCE_ENGINE = first_existing([
    os.environ.get("SKILL_TDL_INFERENCE_ENGINE", ""),
    os.path.join(SKILLS_DIR, "vision_npu", "run_tdl_inference.py"),
    os.path.join(SKILLS_DIR, "vision-npu", "run_tdl_inference.py"),
    "/root/.picoclaw/workspace/skills/vision_npu/run_tdl_inference.py",
    "/root/.picoclaw/workspace/skills/vision-npu/run_tdl_inference.py",
])
PIPELINE_ENGINE = first_existing([
    os.environ.get("SKILL_TDL_PIPELINE_ENGINE", ""),
    os.path.join(SKILLS_DIR, "vision_npu", "pipeline_analyze.py"),
    os.path.join(SKILLS_DIR, "vision-npu", "pipeline_analyze.py"),
    "/root/.picoclaw/workspace/skills/vision_npu/pipeline_analyze.py",
    "/root/.picoclaw/workspace/skills/vision-npu/pipeline_analyze.py",
])

def main():
    params = {}
    try:
        params = json.load(sys.stdin)
    except:
        if len(sys.argv) > 1:
            try:
                with open(sys.argv[1]) as f:
                    params = json.load(f)
            except:
                params = {"image_path": sys.argv[1]}
    
    mode = params.get("mode", "fd")
    image_path = params.get("image_path", params.get("image"))
    capture = params.get("capture", False)
    
    if capture or not image_path:
        if not PIPELINE_ENGINE:
            print(json.dumps({
                "status": "error",
                "message": "TDL pipeline engine not found",
                "searched": "vision_npu/pipeline_analyze.py and legacy vision-npu paths",
                "mode": mode,
            }))
            return
        input_data = json.dumps({"capture_source": 1, "mode": mode, "image_path": image_path})
        result = subprocess.run(
            [sys.executable, PIPELINE_ENGINE],
            input=input_data, capture_output=True, text=True, timeout=60
        )
        try:
            print(json.loads(result.stdout))
        except:
            print(json.dumps({"status": "error", "message": result.stdout[:500]}))
    else:
        if not INFERENCE_ENGINE:
            print(json.dumps({
                "status": "error",
                "message": "TDL inference engine not found",
                "searched": "vision_npu/run_tdl_inference.py and legacy vision-npu paths",
                "mode": mode,
                "image_path": image_path,
            }))
            return
        input_data = json.dumps({"mode": mode, "image_path": image_path})
        result = subprocess.run(
            [sys.executable, INFERENCE_ENGINE],
            input=input_data, capture_output=True, text=True, timeout=35
        )
        try:
            print(json.loads(result.stdout))
        except:
            print(json.dumps({"status": "error", "message": result.stdout[:500]}))

if __name__ == "__main__":
    main()
