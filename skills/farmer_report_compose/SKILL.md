---
name: farmer-report-compose
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 20
parameters:
  - name: alert
    type: object
  - name: report
    type: object
  - name: plot_path
    type: string
  - name: disease
    type: string
    default: downy_mildew
  - name: field
    type: string
  - name: forecast
    type: object
  - name: fungal_pressure
    type: object
returns:
  - status
  - title
  - message
  - plot_path
---
# farmer-report-compose

Creates a standardized deterministic farmer-facing disease-risk report from
alert policy output and Goidanich report metadata. Use LLM rewriting only after
this skill creates the factual base message.

Required report sections:

1. risk today;
2. general situation;
3. weather-based prediction;
4. fungal pressure in general / this week / last week when available;
5. treatment guidance;
6. evidence with real report/plot paths from code.

Do not invent forecast, fungal-pressure, treatment, or plot values. If a value
is absent from returned JSON, mark it as not available and request the relevant
Vineyard Guard skill.
