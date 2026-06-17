---
name: gpio_control
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
parameters:
  - name: pin
    type: string
    default: "504"
  - name: direction
    type: string
    default: "in"
  - name: value
    type: string
    default: ""
returns:
  - pin
  - direction
  - value
  - status
---
# GPIO Control
Read or write GPIO pins via sysfs on LicheeRV Nano.
Pin numbering follows the SG2002 GPIO map: base 480 + port offset.
Example: GP A24 = 480 + 24 = 504.
Set SKILL_DIRECTION=out and SKILL_VALUE=1 to set pin high.
Set SKILL_DIRECTION=in to read current value.
