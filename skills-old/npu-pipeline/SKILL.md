---
name: npu-pipeline
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 120
parameters:
  - name: rtsp_url
    type: string
    default: "rtsp://127.0.0.1:8554/live"
  - name: model_path
    type: string
    default: "/root/models/yolov8n.cvimodel"
---
# NPU Pipeline (Streaming)
This skill implements the full hardware pipeline:
CSI (Camera) -> VPSS (Resize/Format) -> NPU (Inference) -> RTSP (Streaming).
It is source-based and requires the CVI TDL SDK toolchain for compilation.
