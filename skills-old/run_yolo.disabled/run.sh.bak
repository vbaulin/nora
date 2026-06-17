#!/bin/sh
# run_yolo - YOLO inference via maix.nn on LicheeRV Nano (SG2002)
# Uses ION heap memory (not CMA) via the maix Python library.
#
# NOTE: maix.nn causes SIGSEGV on some firmware versions due to NPU driver conflicts.
# This script catches SIGSEGV and returns an error code so the Go layer can fall back.
#
# Environment inputs: SKILL_IMAGE_PATH, SKILL_MODEL_PATH, SKILL_CONFIDENCE

IMAGE_PATH="${SKILL_IMAGE_PATH:-/tmp/capture.jpg}"
MODEL_PATH="${SKILL_MODEL_PATH:-/root/models/yolov11n_coco_320.cvimodel}"
CONFIDENCE="${SKILL_CONFIDENCE:-0.5}"

python3 << 'PYEOF'
import sys
import json
import gc
import os
import signal

# Catch SIGSEGV from NPU driver
def sigsegv_handler(sig, frame):
    print(json.dumps({"status": "error", "code": "SIGSEGV", "message": "NPU driver crash - maix.nn unstable on this firmware. Use C-based inference."}))
    sys.exit(1)

signal.signal(signal.SIGSEGV, sigsegv_handler)

image_path = os.environ.get("SKILL_IMAGE_PATH", "/tmp/capture.jpg")
model_path = os.environ.get("SKILL_MODEL_PATH", "/root/models/yolov11n_coco_320.cvimodel")
conf_th = float(os.environ.get("SKILL_CONFIDENCE", "0.5"))

result = {"status": "error", "message": ""}
model = None
detections = []

try:
    from maix import nn, image as mi

    # Try YOLO11 first, then YOLOv8
    try:
        model = nn.YOLO11(model_path)
        model_name = "YOLO11"
    except Exception:
        try:
            model = nn.YOLOv8(model_path)
            model_name = "YOLOv8"
        except Exception as e:
            result["message"] = "No working YOLO model: " + str(e)
            print(json.dumps(result))
            sys.exit(1)

    # Run inference on the image
    if os.path.exists(image_path):
        img = mi.load(image_path)
        objs = model.detect(img, conf_th=conf_th)
        for o in objs:
            detections.append({
                "class": str(o.label) if hasattr(o, 'label') else str(o),
                "confidence": float(o.conf) if hasattr(o, 'conf') else 0.0,
                "box": [float(o.x), float(o.y), float(o.w), float(o.h)] if hasattr(o, 'x') else []
            })
        del img
    else:
        result["message"] = "Image file not found: " + image_path
        print(json.dumps(result))
        sys.exit(1)

    result = {
        "status": "success",
        "model": model_name,
        "model_path": model_path,
        "detections": detections,
        "count": len(detections),
        "image_path": image_path,
        "conf_th": conf_th
    }
    print(json.dumps(result))

except Exception as e:
    result["message"] = str(e)
    print(json.dumps(result))
finally:
    del model
    gc.collect()
PYEOF
