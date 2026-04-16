---
name: yolo_inference
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
parameters:
  - name: image_path
    type: string
    default: "/tmp/capture.jpg"
  - name: model_path
    type: string
    default: "/root/models/yolov8n.cvimodel"
  - name: threshold
    type: string
    default: "0.5"
returns:
  - detections
  - count
  - latency_ms
---
# YOLO NPU Inference
Runs object detection on a given image using a .cvimodel.
Requires the yolo_detect binary to be deployed on the board.
Outputs a JSON list of detected objects with class and confidence.
