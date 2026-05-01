---
name: observe_scene
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 90
parameters:
  - name: output_dir
    type: string
    default: /tmp/observations
  - name: label
    type: string
    default: scene
  - name: model_path
    type: string
    default: /root/models/yolov8n_coco_320.cvimodel
  - name: threshold
    type: float
    default: 0.5
returns:
  - status
  - image_path
  - yolo
  - color
---
# observe_scene
Composite camera + TPU + color observation.

This is intended for long-running local monitoring tasks where picoClaw should
request one high-level action and let the board collect compact JSON evidence.
