---
name: vineyard-model-explainer
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 30
parameters:
  - name: mode
    type: string
    default: explain
  - name: disease
    type: string
    default: both
  - name: question
    type: string
  - name: current_report
    type: object
  - name: product
    type: string
  - name: treatment_history
    type: array
returns:
  - status
  - title
  - message
  - decision_tree
---
# vineyard-model-explainer

Explains Vineyard Guard disease models and treatment decision logic in farmer
language. Use this skill when the farmer asks why a risk/projection looks a
certain way, how Downy or Powdery models work, why current risk differs from a
forecast curve, or asks for a treatment decision tree/checklist.

This skill does not prescribe a product by itself. It explains model signals and
asks for/uses local treatment history, product catalog matches, label dose, water
volume, treated area, canopy state, and scouting result before any treatment is
recorded.

Rules:

- Downy mildew: explain Goidanich daily/accumulated infection lines and Rossi as
  weather-based primary infection support. Current risk and accumulated lines are
  different signals.
- Powdery mildew: explain UC/Gubler-Thomas risk as disease pressure and PMI as
  treatment-timing support. PMI is not disease probability.
- Forecast projections are warning context, not observed disease labels.
- For treatment decisions, always include: current model signal, forecast signal,
  last treatment/product/date, canopy scouting, product label/dose check, and
  confirmation before saving feedback.
