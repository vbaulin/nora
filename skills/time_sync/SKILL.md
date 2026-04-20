---
name: time_sync
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
---
# time_sync
Synchronizes the system clock using NTP (if online) or a provided manual timestamp.
Prevents logs and experiments from being timestamped in 1970.
