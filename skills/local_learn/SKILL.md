---
name: local_learn
exec_type: python
command: train.py
input_format: stdin
output_format: json
timeout: 60
---
# On-Device Local Learning
Trains a simple classifier (KNN/SVM) on TPU-extracted features.

### Inputs (JSON)
*   `samples`: List of feature vectors extracted by `tpu_feature_extract`.
*   `labels`: Corresponding labels for the samples.
*   `save_path`: Path to save the trained "Memory" (Default: /root/learned_model.pkl)

### Use Case
"Autonomous Training": You show the camera a healthy leaf and a diseased leaf multiple times. This skill "learns" the difference on-the-fly without needing a GPU server.
