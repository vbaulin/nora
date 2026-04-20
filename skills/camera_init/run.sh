#!/bin/sh
# camera_init/run.sh — Initialize CSI camera sensor
# Environment inputs: SKILL_METHOD (auto|sensor_test|manual)
# PLACEHOLDER: Update paths when actual binaries are deployed

METHOD="${SKILL_METHOD:-auto}"
SENSOR_BOUND=false
VIDEO_DEV="none"
METHOD_USED="none"

check_sensor() {
    if grep -q 'DevID' /proc/cvitek/vi 2>/dev/null; then
        SENSOR_BOUND=true
        return 0
    fi
    return 1
}

check_video() {
    if [ -e /dev/video0 ]; then
        VIDEO_DEV="/dev/video0"
    fi
}

# Already bound?
if check_sensor; then
    check_video
    METHOD_USED="already_bound"
    echo '{"sensor_bound": true, "video_device": "'"$VIDEO_DEV"'", "method_used": "already_bound", "status": "ok"}'
    exit 0
fi

# Method 1: sensor_test binary
if [ "$METHOD" = "auto" ] || [ "$METHOD" = "sensor_test" ]; then
    SENSOR_BIN=""
    for p in /root/sensor_test /usr/bin/sensor_test /opt/bin/sensor_test; do
        if [ -x "$p" ]; then
            SENSOR_BIN="$p"
            break
        fi
    done
    if [ -n "$SENSOR_BIN" ]; then
        $SENSOR_BIN 2>&1 || true
        sleep 1
        if check_sensor; then
            check_video
            echo '{"sensor_bound": true, "video_device": "'"$VIDEO_DEV"'", "method_used": "sensor_test", "status": "ok"}'
            exit 0
        fi
    fi
fi

# Method 2: Check if driver just needs time
sleep 2
if check_sensor; then
    check_video
    echo '{"sensor_bound": true, "video_device": "'"$VIDEO_DEV"'", "method_used": "delayed_check", "status": "ok"}'
    exit 0
fi

# Failed
check_video
echo '{"sensor_bound": false, "video_device": "'"$VIDEO_DEV"'", "method_used": "'"$METHOD"'", "status": "error", "error": "sensor_test binary not found or sensor init failed"}'
