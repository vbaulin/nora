---
name: tpu_feature_extract
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
---
# TPU Feature Extractor
Converts an image into a high-dimensional mathematical vector (Embedding).

### Inputs
*   `SKILL_IMAGE_PATH`: Path to image (Default: /tmp/capture.jpg)
*   `SKILL_MODEL_PATH`: Path to an embedding model (e.g., mobilenet_v2_embedding.cvimodel)

### Logic
Uses the TPU to run a truncated neural network. Instead of a "Class Label," it returns the raw output of the last hidden layer. This is the "Digital Signature" of the object.
