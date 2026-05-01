---
name: sensor_fusion_snapshot
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 20
---
# sensor_fusion_snapshot
Collects lightweight environmental/system context without waking the LLM:
memory, temperature if exposed by sysfs, video devices, I2C scan availability,
and recent kernel messages.
