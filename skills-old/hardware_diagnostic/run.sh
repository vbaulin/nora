#!/bin/sh

# Diagnostic script for LicheeRV Nano SDK
# Checks for libraries and SDR firmware

echo "{"
echo "  \"status\": \"ok\","
echo "  \"libraries\": {"

for lib in libcvikernel.so libcvimath.so libcviruntime.so; do
    if [ -f "/lib/$lib" ] || [ -f "/lib64/$lib" ]; then
        echo "    \"$lib\": \"found\","
    else
        echo "    \"$lib\": \"missing\","
    fi
done
echo "    \"check\": \"complete\""
echo "  },"

echo "  \"firmware\": ["
if [ -d "/mnt/cfg/param" ]; then
    ls /mnt/cfg/param | grep -E "cvi_sdr|bin" | sed 's/^/"/;s/$/",/' | sed '$ s/,$//'
fi
echo "  ]"
echo "}"
