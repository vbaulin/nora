---
name: run_yolo
exec_type: shell
command: python3 ./run.py
input_format: stdin
output_format: json
timeout: 60
parameters:
  - name: model_path
    type: string
    default: "/root/models/yolov8n_coco_320.cvimodel"
  - name: image_path
    type: string
    default: "/tmp/capture.jpg"
  - name: threshold
    type: float
    default: 0.5
---
# YOLO Object Detection (Maix-Python)
Runs YOLO inference on a camera frame. 
Uses ION heap memory (buff_num=2) to avoid CMA conflicts.
Returns detected objects and saves the source frame.
