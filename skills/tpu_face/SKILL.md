---
name: tpu_face
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
---
# TPU Face Detection
High-speed face and landmark detection using the native NPU.

### Inputs
*   `SKILL_MODEL_PATH`: Path to RetinaFace .cvimodel
*   `SKILL_IMAGE_PATH`: Path to image (Default: /tmp/capture.jpg)

### Use Case
Identifying human presence, estimating focus/attention, or preparing crops for face recognition.
