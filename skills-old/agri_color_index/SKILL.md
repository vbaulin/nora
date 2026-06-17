---
name: agri_color_index
exec_type: python
command: run.py
input_format: stdin
output_format: json
timeout: 30
---
# Ripeness & Color Analysis
Calculates color histograms and mean HSL values to track grape ripening.

### Logic
Processes `/tmp/capture.jpg` to identify color clusters corresponding to sugar levels (e.g., transition from green to deep purple).

### Outputs
Returns a JSON object with `mean_hue`, `saturation_index`, and `ripeness_estimate`.
