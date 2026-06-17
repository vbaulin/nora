# run_yolo_cvi Skill

This skill provides YOLO object detection using CVI TDL (Tensor Detection Library) for the SG2002 NPU on LicheeRV Nano.

## Purpose
Avoid maix.nn SIGSEGV issues by using direct CVI TDL libraries for YOLO inference on the TPU.

## Implementation
This skill loads CVI-compatible .cvimodel files and runs inference using the CVI TDL interface.

## Usage
Input JSON:
```json
{
  "width": 320,
  "height": 240,
  "model_path": "/root/models/yolov8n_coco_320.cvimodel",
  "image_path": "/tmp/capture.jpg",
  "threshold": 0.5
}
```

Output JSON:
```json
{
  "status": "success",
  "image_path": "/tmp/capture.jpg",
  "detections": [
    {
      "class": 0,
      "score": 0.85,
      "box": [100, 100, 50, 50]
    }
  ],
  "count": 1
}
```

## Notes
- Designed to work around maix.nn SIGSEGV issues
- Uses CVI TDL libraries for direct TPU access
- Compatible with .cvimodel files in /root/models/