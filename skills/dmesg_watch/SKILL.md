---
name: dmesg_watch
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
# Reports Cvitek driver and sensor messages from the kernel ring buffer. On a
# host with no such devices there is nothing for it to watch.
requires_hardware: true
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
