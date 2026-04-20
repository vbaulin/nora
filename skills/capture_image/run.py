#!/usr/bin/env python3
"""
capture_image - Fixed 320x240 camera capture via maix library.
Uses ION heap memory (not CMA). Single atomic operation.
"""
import sys
import json
import os
import gc

try:
    from maix import camera, image
except ImportError:
    class MockCamera:
        def __init__(self, *args, **kwargs): pass
        def read(self): return None
    camera = type('Mock', (), {'Camera': MockCamera})()

def main():
    result = {"status": "error", "message": ""}
    cam = None
    img = None
    
    try:
        # Fixed 320x240 as agreed - do NOT change
        width = 320
        height = 240
        output_path = "/tmp/capture.jpg"
        
        # Read params from stdin (JSON)
        try:
            params = json.load(sys.stdin)
            width = int(params.get("width", 320))
            height = int(params.get("height", 240))
            output_path = params.get("output_path", "/tmp/capture.jpg")
        except Exception:
            pass
        
        # CRITICAL: Hardcap to 320x240 for ION heap stability
        width = 320
        height = 240
        
        # Initialize camera with 2 buffers (ION heap, not CMA)
        cam = camera.Camera(width, height, buff_num=2)
        
        # Read frame
        img = cam.read()
        if img is None:
            result["message"] = "camera.read() returned None"
            print(json.dumps(result))
            return
        
        # Save image
        img.save(output_path)
        file_size = os.path.getsize(output_path)
        
        result = {
            "status": "success",
            "path": output_path,
            "width": width,
            "height": height,
            "size": file_size,
            "format": "JPEG"
        }
        print(json.dumps(result))
        
    except Exception as e:
        result["message"] = str(e)
        print(json.dumps(result))
    finally:
        # CRITICAL: Explicit ION heap cleanup
        del cam
        del img
        gc.collect()

if __name__ == "__main__":
    main()
