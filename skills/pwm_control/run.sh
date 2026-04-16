#!/bin/sh
# pwm_control/run.sh
# Params: SKILL_CHANNEL, SKILL_PERIOD, SKILL_DUTY_CYCLE, SKILL_ENABLE

CH="${SKILL_CHANNEL:-0}"
PERIOD="${SKILL_PERIOD:-1000000}"
DUTY="${SKILL_DUTY_CYCLE:-500000}"
ENABLE="${SKILL_ENABLE:-1}"

CHIP="/sys/class/pwm/pwmchip0"
PWM_DIR="${CHIP}/pwm${CH}"

# 1. Export if needed
if [ ! -d "$PWM_DIR" ]; then
    echo "$CH" > "${CHIP}/export" 2>/dev/null
    sleep 0.1
fi

if [ -d "$PWM_DIR" ]; then
    # 2. Config
    echo "$PERIOD" > "${PWM_DIR}/period" 2>/dev/null
    echo "$DUTY" > "${PWM_DIR}/duty_cycle" 2>/dev/null
    echo "$ENABLE" > "${PWM_DIR}/enable" 2>/dev/null
    echo "{\"channel\": $CH, \"period\": $PERIOD, \"duty_cycle\": $DUTY, \"enabled\": $ENABLE, \"status\": \"success\"}"
else
    echo "{\"error\": \"Failed to export PWM channel $CH\", \"status\": \"failed\"}"
fi
