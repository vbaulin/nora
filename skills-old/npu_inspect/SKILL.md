---
name: npu_info
exec_type: native
command: npu_inspect
input_format: env
output_format: json
timeout: 10
---
# NPU Information
Checks for Cvitek/Sophgo TPU device and logs driver status.
Useful for verifying that the NPU is ready for inference.
