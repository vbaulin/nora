---
name: monitor_summary
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 30
parameters:
  - name: journal_path
    type: string
    default: /tmp/monitors/grape_growth.jsonl
  - name: tail
    type: integer
    default: 200
returns:
  - status
  - count
  - trends
---
# monitor_summary
Summarizes long-running JSONL monitoring journals into compact trend evidence.
