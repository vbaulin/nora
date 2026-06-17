---
name: fast_capture
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
---
# Fast Native Image Capture
Captures a frame using the native Cvitek ISP binaries. Extremely low RAM footprint.

### Inputs
*   `SKILL_OUTPUT`: Path to save the image (Default: /tmp/capture.jpg)
*   `SKILL_WIDTH`: Image width (Default: 1920)
*   `SKILL_HEIGHT`: Image height (Default: 1080)
