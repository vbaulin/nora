---
name: report-guard
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 10
parameters:
  - name: report
    type: object
  - name: text
    type: string
returns:
  - status
  - valid
  - message
---
# report-guard

Validates a picoClaw vineyard report against Vineyard Guard rules before it is
shown or sent. Use this after `daily-vineyard-briefing mode=standard_report` if
picoClaw rewrites anything.

Hard failures:

- calls risk below 50% high, critical, urgent, or treatment-worthy;
- omits the standardized report sections;
- omits the real plot path when `standard_report` returned one.
