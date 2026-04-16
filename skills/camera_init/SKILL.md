---
name: camera_init
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 30
parameters:
  - name: method
    type: string
    default: "auto"
returns:
  - sensor_bound
  - video_device
  - method_used
  - status
---
# Camera Sensor Initialization
Initialize the CSI camera sensor on LicheeRV Nano.
Tries multiple methods: sensor_test binary, manual I2C probe, driver reload.
PLACEHOLDER: The actual sensor_test binary path may vary per installation.
