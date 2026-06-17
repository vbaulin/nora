---
name: agri_env_probe
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 20
parameters:
  - name: bus
    type: string
    default: /dev/i2c-1
  - name: address
    type: string
    default: "0x44"
returns:
  - status
  - sensor
  - raw_data
  - bus_scan
---
# agri_env_probe

Lightweight I2C environmental probe for vineyard or lab deployments.

This is a generic board-compatible probe. It checks for `i2cget`/`i2cdetect`,
tries a simple read, and returns compact JSON. For a known sensor, promote a
dedicated skill with the correct conversion formula.
