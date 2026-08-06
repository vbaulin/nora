---
name: run_yolo
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 60
requires_hardware: true
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
  - name: model_family
    type: string
    default: auto
  - name: backend
    type: string
    default: maix
---
# YOLO Object Detection

Canonical board skill for YOLO object detection through Maix Python.

Maix Python is the primary supported path now. Use this skill for YOLOv8,
YOLOv11, and compatible `.cvimodel` files converted for the SG2002/Maix runtime.
The skill initializes the YOLO model before the camera so NPU/model memory is
reserved before image buffers.

## Inputs

- `model_path`: `.cvimodel` path. Examples:
  - `/root/models/yolov8n_coco_320.cvimodel`
  - `/root/models/yolo11n_coco_320.cvimodel`
  - `/root/models/yolov11n_coco_320.cvimodel`
- `model_family`: `auto`, `yolov8`, or `yolov11`. `auto` tries YOLO11/YOLOv11,
  YOLOv8, then generic YOLO constructors exposed by `maix.nn`.
- `backend`: `maix`, `auto`, or `native`.
  - `maix`: use Maix Python only.
  - `auto`: try Maix Python first, then native CVI/TDL-style binary fallback.
  - `native`: skip Maix and try native binary discovery.
- `image_path`: output path for the captured frame.
- `threshold`: confidence threshold.

## Output

Returns JSON with:

- `status`
- `backend`
- `constructor`
- `model_family`
- `model_path`
- `image_path`
- `detections`
- `count`

## Operational Notes

- This is the route picoClaw should use for YOLO. Do not run `cvi_tdl_yolo`,
  `sample_yolov8`, or direct `.cvimodel` commands from picoClaw shell.
- The camera is opened at 320x240 with `buff_num=2` to reduce memory pressure on
  the LicheeRV Nano.
- `run_tdl_detection` and `run_opencv_detection` remain useful specialized
  fallback/research skills, but they do not replace this canonical YOLO skill.
