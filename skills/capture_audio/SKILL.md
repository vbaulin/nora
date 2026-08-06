---
name: capture_audio
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
requires_hardware: true
---
# capture_audio
Captures audio using arecord from the onboard cv182xa_adc hardware.
