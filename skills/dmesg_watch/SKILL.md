---
name: dmesg_watch
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
parameters:
  - name: lines
    type: string
    default: "30"
  - name: filter
    type: string
    default: "error|fail|warn|cvi|sensor"
returns:
  - total_matches
  - errors
  - warnings
  - cvitek_messages
  - recent_lines
---
# Dmesg Watcher
Tail kernel ring buffer for errors, warnings, and cvitek-specific messages.
Useful for diagnosing hardware initialization failures and driver issues.
