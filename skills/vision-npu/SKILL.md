---
name: vision-npu
exec_type: native
command: run_yolo
input_format: env
output_format: json
timeout: 60
parameters:
  - name: model_path
    type: string
    default: "/root/models/yolov8n.cvimodel"
  - name: binary_path
    type: string
    default: "/usr/bin/npu_pipeline"
  - name: image_path
    type: string
    default: "/tmp/capture.jpg"
  - name: binary_path
    type: string
    default: "/usr/bin/cvi_tdl_yolo"
---
# Vision NPU (Binary Wrapper)
This skill provides a high-performance wrapper for NPU inference on the LicheeRV Nano.
It executes precompiled hardware binaries (e.g., cvi_tdl_yolo) and manages the library paths for the TPU SDK.
