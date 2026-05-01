---
name: promote_skill
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
parameters:
  - name: candidate_path
    type: string
  - name: target_name
    type: string
returns:
  - status
  - target_path
---
# promote_skill
Copies a validated draft skill into the active skills directory.
