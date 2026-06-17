---
name: system_info
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 15
parameters:
  - name: sections
    type: string
    default: "all"
returns:
  - cpu_temp_c
  - ram_free_mb
  - ram_total_mb
  - disk_free_mb
  - uptime_seconds
  - kernel
  - modules_loaded
  - network_interfaces
---
# System Information Collector
Collects comprehensive system state from LicheeRV Nano for hardware monitoring.
Returns JSON with CPU temperature, RAM usage, disk space, kernel info, and network state.
