#!/usr/bin/env python3
"""
run_tdl_detection - NPU-accelerated detection using CVI TDL SDK on SG2002

Takes JSON via stdin or file path via argv[1].
Uses pre-compiled TDL SDK executables.

Working modes:
  - fd: Face Detection using scrfd model ✅
  - hand_cls: Hand Classification (partial) ⚠️
"""
import sys
import os
import json

# Delegate to the canonical inference engine
INFERENCE_ENGINE = "/root/.picoclaw/workspace/skills/vision-npu/run_tdl_inference.py"
PIPELINE_ENGINE = "/root/.picoclaw/workspace/skills/vision-npu/pipeline_analyze.py"

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
    
    import subprocess
    
    if capture or not image_path:
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