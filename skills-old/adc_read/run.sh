#!/bin/sh
# adc_read/run.sh
# SKILL_CHANNEL is provided by engine

CH="${SKILL_CHANNEL:-0}"
DEV_PATH="/sys/bus/iio/devices/iio:device0/in_voltage${CH}_raw"

if [ -f "$DEV_PATH" ]; then
    VAL=$(cat "$DEV_PATH")
    echo "{\"channel\": $CH, \"raw_value\": $VAL, \"status\": \"success\"}"
else
    echo "{\"error\": \"ADC device not found at $DEV_PATH\", \"status\": \"failed\"}"
fi
