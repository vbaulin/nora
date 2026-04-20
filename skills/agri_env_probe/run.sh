#!/bin/sh

# Generic I2C Environmental Probe for LicheeRV Nano
# Example: Reading an SHT3x or AHT20 sensor on /dev/i2c-1

BUS="/dev/i2c-1"
ADDR="0x44" # Standard SHT31 address

# Check if i2c-tools are installed
if ! command -v i2cget >/dev/null 2>&1; then
    echo "{\"status\": \"error\", \"message\": \"i2c-tools not found. Run 'apt-get install i2c-tools'\"}"
    exit 1
fi

# Probe the sensor
DATA=$(i2cget -y $BUS $ADDR 0x00 2>/dev/null)

if [ $? -eq 0 ]; then
    echo "{\"status\": \"ok\", \"sensor\": \"i2c-device\", \"raw_data\": \"$DATA\"}"
else
    # Fallback to scanning the bus
    SCAN=$(i2cdetect -y -r 1 | grep -v "  0 1 2 3 4 5 6 7 8 9 a b c d e f" | grep -v "00:" | tr -d '\n')
    echo "{\"status\": \"offline\", \"bus_scan\": \"$SCAN\"}"
fi
