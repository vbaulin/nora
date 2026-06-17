#!/usr/bin/env python3
import json
import gc
import os
import sys

try:
    import maix
    from maix import nn
except ImportError:
    print(json.dumps({"status": "error", "message": "maix library not found"}))
    sys.exit(1)


def construct_yolo(model_path, model_family):
    candidates = []
    family = (model_family or "auto").lower()
    if family in ("yolo11", "yolov11", "11"):
        candidates = ["YOLO11", "YOLOv11", "YOLO"]
    elif family in ("yolo8", "yolov8", "8"):
        candidates = ["YOLOv8", "YOLO"]
    else:
        candidates = ["YOLO11", "YOLOv11", "YOLOv8", "YOLO"]

    errors = []
    for name in candidates:
        ctor = getattr(nn, name, None)
        if ctor is None:
            continue
        try:
            return ctor(model=model_path), name
        except Exception as exc:
            errors.append(f"{name}(model=...): {exc}")
        try:
            return ctor(model_path), name
        except Exception as exc:
            errors.append(f"{name}(...): {exc}")
    raise RuntimeError("; ".join(errors) or "no Maix YOLO constructor available")


def detect_objects(yolo, img, threshold, iou):
    attempts = [
        lambda: yolo.detect(img, confidence=threshold, iou=iou),
        lambda: yolo.detect(img, conf_th=threshold, iou_th=iou),
        lambda: yolo.detect(img, threshold),
        lambda: yolo.detect(img),
    ]
    errors = []
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def object_box(obj):
    if hasattr(obj, "bbox"):
        box = obj.bbox
        try:
            return [int(v) for v in box]
        except Exception:
            return box
    if all(hasattr(obj, attr) for attr in ("x", "y", "w", "h")):
        return [int(obj.x), int(obj.y), int(obj.x + obj.w), int(obj.y + obj.h)]
    return []


def object_class(obj):
    for attr in ("category", "class_id", "classid", "class_name"):
        if hasattr(obj, attr):
            return getattr(obj, attr)
    return None


def object_score(obj):
    for attr in ("score", "confidence", "prob"):
        if hasattr(obj, attr):
            try:
                return float(getattr(obj, attr))
            except Exception:
                pass
    return 0.0


def main():
    result = {"status": "error", "message": ""}
    cam = None
    img = None
    yolo = None
    
    try:
        # Default params
        width = 320
        height = 240
        model_path = "/root/models/yolov8n_coco_320.cvimodel"
        image_path = "/tmp/capture.jpg"
        threshold = 0.5
        iou = 0.45
        model_family = "auto"
        capture = False
        
        # Read params from stdin
        try:
            params = json.load(sys.stdin)
            width = int(params.get("width", 320))
            height = int(params.get("height", 240))
            model_path = params.get("model_path", model_path)
            image_path = params.get("image_path", image_path)
            threshold = float(params.get("threshold", 0.5))
            iou = float(params.get("iou", params.get("iou_threshold", 0.45)))
            model_family = params.get("model_family", params.get("model_type", "auto"))
            capture = bool(params.get("capture", False))
        except Exception:
            pass

        # Validate model
        if not os.path.exists(model_path):
            print(json.dumps({"status": "error", "message": f"Model not found: {model_path}"}))
            return

        # Initialize YOLO first to reserve model/NPU memory before camera buffers.
        try:
            yolo, constructor = construct_yolo(model_path, model_family)
        except Exception as e:
            print(json.dumps({"status": "error", "message": f"YOLO init failed: {e}"}))
            return

        if not capture and os.path.exists(image_path):
            try:
                img = maix.image.load(image_path)
            except Exception as exc:
                print(json.dumps({
                    "status": "error",
                    "message": f"image load failed: {exc}",
                    "image_path": image_path,
                }))
                return
        else:
            from maix import camera
            # Initialize camera with ION heap only when capture is requested or
            # the requested image does not exist. This avoids re-opening the
            # camera after a successful capture_image step.
            cam = camera.Camera(width, height, buff_num=2)
            img = cam.read()
            if img is None:
                print(json.dumps({"status": "error", "message": "camera.read() returned None"}))
                return
            img.save(image_path)
        
        # Run inference
        objs = detect_objects(yolo, img, threshold, iou)
        
        # Format results
        detections = []
        for obj in objs:
            detections.append({
                "class": object_class(obj),
                "confidence": object_score(obj),
                "score": object_score(obj),
                "box": object_box(obj),
                "box_format": "bbox_or_xyxy"
            })
            
        print(json.dumps({
            "status": "success",
            "backend": "maix_python",
            "constructor": constructor,
            "model_family": model_family,
            "model_path": model_path,
            "image_path": image_path,
            "detections": detections,
            "count": len(detections)
        }))
        
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
    finally:
        # Cleanup
        if cam: del cam
        if img: del img
        if yolo: del yolo
        gc.collect()

if __name__ == "__main__":
    main()
