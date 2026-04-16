---
name: vision_state_sync
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 90
---
# Vision State Synchronizer
High-level skill that orchestrates a full vision cycle:
1. Capture image from CSI camera.
2. Run NPU YOLO inference.
3. Update the engine state with detected objects.
Returns a summary of "Visual Truth" for the engine.
