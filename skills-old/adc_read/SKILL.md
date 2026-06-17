---
name: adc_read
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 5
parameters:
  - name: channel
    type: string
    default: "0"
---
# ADC Reader
Reads the raw voltage value from the Sophgo SG2002 internal ADC.
Targets /sys/bus/iio/devices/iio:device0/in_voltage\${CHANNEL}_raw.
