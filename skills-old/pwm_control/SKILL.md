---
name: pwm_control
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
parameters:
  - name: channel
    type: string
    default: "0"
  - name: period
    type: string
    default: "1000000"
  - name: duty_cycle
    type: string
    default: "500000"
  - name: enable
    type: string
    default: "1"
---
# PWM Controller
Controls the Pulse Width Modulation signals.
Useful for controlling motor speeds or LED brightness.
Targets /sys/class/pwm/pwmchip0/pwm\${CHANNEL}/.
