#!/usr/bin/env python3
import sys
import json
import os
import gc

try:
    from maix import camera, image, nn
except ImportError:
    print(json.dumps({"status": "error", "message": "maix library not found"}))
    sys.exit(1)

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
        
        # Read params from stdin
        try:
            params = json.load(sys.stdin)
            width = int(params.get("width", 320))
            height = int(params.get("height", 240))
            model_path = params.get("model_path", model_path)
            image_path = params.get("image_path", image_path)
            threshold = float(params.get("threshold", 0.5))
        except Exception:
            pass

        # Validate model
        if not os.path.exists(model_path):
            print(json.dumps({"status": "error", "message": f"Model not found: {model_path}"}))
            return

        # Initialize YOLO FIRST (to reserve memory before camera)
        # Using maix.nn.YOLO (standard for Maix-Python)
        try:
            yolo = nn.YOLOv8(model_path)
        except Exception as e:
            # Fallback to general YOLO if v8 is missing
            try:
                yolo = nn.YOLO(model_path)
            except Exception as e2:
                print(json.dumps({"status": "error", "message": f"YOLO init failed: {e2}"}))
                return

        # Initialize camera with ION heap
        cam = camera.Camera(width, height, buff_num=2)
        
        # Read frame
        img = cam.read()
        if img is None:
            print(json.dumps({"status": "error", "message": "camera.read() returned None"}))
            return
        
        # Save raw frame
        img.save(image_path)
        
        # Run inference
        objs = yolo.detect(img, conf_th=threshold)
        
        # Format results
        detections = []
        for obj in objs:
            detections.append({
                "class": obj.class_id,
                "score": obj.score,
                "box": [obj.x, obj.y, obj.w, obj.h]
            })
            
        print(json.dumps({
            "status": "success",
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
