---
name: validate_skill
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 30
parameters:
  - name: candidate_path
    type: string
  - name: require_command
    type: boolean
    default: true
returns:
  - status
  - checks
---
# validate_skill
Static validation gate for picoClaw-created draft skills before promotion.
