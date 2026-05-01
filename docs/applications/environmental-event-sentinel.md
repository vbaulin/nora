# Environmental Event Sentinel

The board can sit quietly, collect low-rate context, and wake higher-level reasoning only when something changes.

## What It Observes

- Sudden audio events.
- Scene change after sound.
- Wet-surface or storm cues.
- Temperature/sysfs trends.
- I2C sensor availability or readings.
- Camera, TPU, or audio driver warnings.
- Human, animal, or machine movement.

## Why It Is Powerful

Most of the day is boring. The board should not spend tokens describing boring. It should keep compact local context and send picoClaw an evidence pack when an event matters.

## Chain

```text
periodic low-cost system snapshot
+ microphone trigger
-> capture image after event
-> run TPU/object detection
-> collect I2C/system metrics
-> append event JSONL
-> debounce repeated alerts
```

## Useful Skills

- `audio_event_detect`: RMS/peak/spectral trigger.
- `scene_change_after_sound`: visual confirmation.
- `sensor_fusion_snapshot`: memory, thermal, video, I2C, dmesg.
- `storm_event_logger`: sound + light drop + wetness cues.
- `event_debounce`: avoids repeated alerts for same event.
- `evidence_pack`: bundles image, audio, metrics, and summary.

## Example Real Change

The sentinel hears repeated impacts at night and captures frames showing no animal but a swinging loose object. picoClaw creates a specific `swinging_object_event` skill from the saved evidence. The monitor stops alerting on harmless swings and only reports novel events.

