#!/bin/sh

# Defaults
DURATION=${SKILL_DURATION:-5}
OUTPUT_PATH=${SKILL_OUTPUT_PATH:-"/tmp/capture.mp4"}
FPS=${SKILL_FPS:-15}

# Try ffmpeg first (most common for video clips)
# We use low resolution to avoid memory issues
ffmpeg -y -f v4l2 -video_size 320x240 -i /dev/video0 -t $DURATION -r $FPS -c:v libx264 -preset ultrafast -pix_fmt yuv420p $OUTPUT_PATH > /tmp/ffmpeg.log 2>&1

if [ -f "$OUTPUT_PATH" ]; then
    SIZE=$(stat -c%s "$OUTPUT_PATH")
    echo "{\"status\": \"success\", \"path\": \"$OUTPUT_PATH\", \"duration\": $DURATION, \"size\": $SIZE}"
else
    echo "{\"status\": \"error\", \"message\": \"Failed to record video\", \"log\": \"$(cat /tmp/ffmpeg.log)\"}"
    exit 1
fi
exit 0
