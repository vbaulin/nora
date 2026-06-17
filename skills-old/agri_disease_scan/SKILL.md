---
name: agri_disease_scan
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
---
# Agricultural Disease Detection (TPU)
Uses a specialized NPU model to detect common vine diseases (e.g., Mildew, Botrytis).

### Inputs
*   `SKILL_MODEL_PATH`: Path to the agri-tuned .cvimodel
*   `SKILL_IMAGE_PATH`: Path to capture (Default: /tmp/capture.jpg)

### Use Case
Early detection of outbreaks in vineyards, allowing for targeted treatment instead of blanket spraying.
