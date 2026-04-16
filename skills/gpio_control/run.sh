#!/bin/sh
# gpio_control/run.sh — GPIO read/write via sysfs
# Environment inputs: SKILL_PIN, SKILL_DIRECTION, SKILL_VALUE

PIN="${SKILL_PIN:-504}"
DIR="${SKILL_DIRECTION:-in}"
VAL="${SKILL_VALUE:-}"
GPIO_PATH="/sys/class/gpio/gpio${PIN}"

# Export pin if not already exported
if [ ! -d "$GPIO_PATH" ]; then
    echo "$PIN" > /sys/class/gpio/export 2>/dev/null
    sleep 0.1
fi

if [ ! -d "$GPIO_PATH" ]; then
    echo '{"status": "error", "error": "pin export failed", "pin": "'"$PIN"'"}'
    exit 0
fi

# Set direction
echo "$DIR" > "${GPIO_PATH}/direction" 2>/dev/null

if [ "$DIR" = "out" ] && [ -n "$VAL" ]; then
    # Write value
    echo "$VAL" > "${GPIO_PATH}/value" 2>/dev/null
    ACTUAL=$(cat "${GPIO_PATH}/value" 2>/dev/null || echo "error")
    echo '{"status": "ok", "pin": "'"$PIN"'", "direction": "out", "value": "'"$ACTUAL"'"}'
else
    # Read value
    ACTUAL=$(cat "${GPIO_PATH}/value" 2>/dev/null || echo "error")
    echo '{"status": "ok", "pin": "'"$PIN"'", "direction": "in", "value": "'"$ACTUAL"'"}'
fi
