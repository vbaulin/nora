---
name: tpu_pose
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
---
# TPU Pose Estimation
Detects human body keypoints (17 points) using native NPU acceleration.

### Inputs
*   `SKILL_MODEL_PATH`: Path to the pose .cvimodel (e.g., yolov8_pose.cvimodel)
*   `SKILL_IMAGE_PATH`: Path to the image (Default: /tmp/capture.jpg)

### Use Case
Detecting gestures, fall detection, or counting repetitive physical movements.
