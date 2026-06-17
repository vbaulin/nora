#!/bin/sh

# 1. Manual Sync (Priority)
if [ -n "$SKILL_TIMESTAMP" ]; then
    echo "🕒 Setting time to manual timestamp: $SKILL_TIMESTAMP"
    date -s "@$SKILL_TIMESTAMP" > /dev/null 2>&1
    echo "{\"status\": \"success\", \"method\": \"manual\", \"time\": \"$(date)\"}"
    exit 0
fi

# 2. Network Sync (NTP)
echo "🌐 Attempting network time sync..."
if command -v ntpdate > /dev/null; then
    ntpdate -u pool.ntp.org > /dev/null 2>&1
elif command -v chronyc > /dev/null; then
    chronyc makestep > /dev/null 2>&1
fi

# Check if we moved away from 1970
YEAR=$(date +%Y)
if [ "$YEAR" -gt 1970 ]; then
    echo "{\"status\": \"success\", \"method\": \"network\", \"time\": \"$(date)\"}"
else
    echo "{\"status\": \"failed\", \"message\": \"Still in 1970. No network or timestamp provided.\"}"
fi
