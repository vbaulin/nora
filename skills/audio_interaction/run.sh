#!/bin/sh

# SKILL_AUDIO_INTERACTION_ACTION
# SKILL_AUDIO_INTERACTION_DURATION
# SKILL_AUDIO_INTERACTION_OUTPUT_PATH

ACTION=${SKILL_AUDIO_INTERACTION_ACTION:-record}
DURATION=${SKILL_AUDIO_INTERACTION_DURATION:-3}
OUTPUT_PATH=${SKILL_AUDIO_INTERACTION_OUTPUT_PATH:-/tmp/record.wav}

if [ "$ACTION" = "stop" ]; then
    pkill arecord
    echo "{\"status\": \"stopped\"}"
    exit 0
fi

# Set volume
amixer -Dhw:0 cset name='ADC Capture Volume' 24 > /dev/null 2>&1

# Record
if [ "$DURATION" = "0" ]; then
    arecord -Dhw:0,0 -r 48000 -f S16_LE -t wav "$OUTPUT_PATH" > /dev/null 2>&1 &
    echo "{\"status\": \"recording_background\", \"path\": \"$OUTPUT_PATH\", \"pid\": $!}"
else
    arecord -Dhw:0,0 -d "$DURATION" -r 48000 -f S16_LE -t wav "$OUTPUT_PATH" > /dev/null 2>&1
    echo "{\"status\": \"completed\", \"path\": \"$OUTPUT_PATH\", \"duration\": $DURATION}"
fi
