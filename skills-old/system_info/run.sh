#!/bin/sh
# system_info/run.sh — Collect system vitals as JSON
# No dependencies beyond busybox / standard Linux tools

set -e

# CPU temperature (millidegrees → degrees)
TEMP_RAW=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
CPU_TEMP=$((TEMP_RAW / 1000))

# Memory
MEM_TOTAL=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
MEM_FREE=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo 2>/dev/null || awk '/MemFree/{print int($2/1024)}' /proc/meminfo)

# Disk
DISK_FREE=$(df -m / 2>/dev/null | awk 'NR==2{print $4}' || echo 0)

# Uptime
UPTIME=$(awk '{printf "%d", $1}' /proc/uptime)

# Kernel
KERNEL=$(uname -r)

# Modules count
MODULES=$(cat /proc/modules 2>/dev/null | wc -l || echo 0)

# Network interfaces
NET_IFS=$(ip -o addr show 2>/dev/null | awk '{printf "%s:%s ", $2, $4}' || echo "unknown")

# Load average
LOAD=$(cat /proc/loadavg | awk '{print $1}')

cat <<EOF
{
  "cpu_temp_c": ${CPU_TEMP},
  "ram_total_mb": ${MEM_TOTAL},
  "ram_free_mb": ${MEM_FREE},
  "disk_free_mb": ${DISK_FREE},
  "uptime_seconds": ${UPTIME},
  "kernel": "${KERNEL}",
  "modules_loaded": ${MODULES},
  "network_interfaces": "${NET_IFS}",
  "load_avg": "${LOAD}"
}
EOF
