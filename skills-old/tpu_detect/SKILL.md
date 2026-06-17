---
name: tpu_detect
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
---
# TPU Native Detection Skill
Executes high-speed YOLOv8 detection using the Cvitek TDL SDK.

### Prerequisites
*   Native binary `sample_yolov8` or `cvi_tdl_yolo` in `/root/libs_patch/bin/` or `/usr/bin/`.
*   `.cvimodel` file at `SKILL_MODEL_PATH`.

### Inputs (Env)
*   `SKILL_MODEL_PATH`: Path to the .cvimodel (Default: /root/models/yolov8n_coco_320.cvimodel)
*   `SKILL_IMAGE_PATH`: Path to the image to analyze (Default: /tmp/capture.jpg)
*   `SKILL_THRESHOLD`: Detection threshold (Default: 0.5)

### Logic
Sets `LD_LIBRARY_PATH` to include the verified CVI SDK paths and executes the native binary for sub-100ms inference.
