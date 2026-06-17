#!/bin/sh

TEMP="unknown"
for t in /sys/class/thermal/thermal_zone*/temp; do
  if [ -f "$t" ]; then
    TEMP="$(cat "$t" 2>/dev/null | head -n 1)"
    break
  fi
done

MEM_AVAIL="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)"
VIDEO_COUNT="$(ls /dev/video* 2>/dev/null | wc -l | tr -d ' ')"
I2C_COUNT="unknown"
if command -v i2cdetect >/dev/null 2>&1; then
  I2C_COUNT="$(i2cdetect -y -r 1 2>/dev/null | grep -Eo '[0-9a-f][0-9a-f]' | wc -l | tr -d ' ')"
fi
RECENT_DMESG="$(dmesg 2>/dev/null | tail -n 5 | tr '\n' ' ' | sed 's/"/'\''/g')"

cat <<EOF
{
  "status": "success",
  "timestamp": "$(date -Iseconds)",
  "temperature_raw": "$TEMP",
  "mem_available_kb": "${MEM_AVAIL:-unknown}",
  "video_device_count": "$VIDEO_COUNT",
  "i2c_device_count": "$I2C_COUNT",
  "recent_dmesg": "$RECENT_DMESG"
}
EOF
