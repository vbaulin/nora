# Machine Health Monitor

Camera plus microphone can monitor machines surprisingly well: status lights, gauges, motion, startup sequence, vibration-like audio, and visible anomalies.

## What It Observes

- Fan, pump, belt, or motor running state.
- Indicator LED colors and blink patterns.
- Analog gauge needle positions.
- Startup and shutdown sequences.
- Audio signature drift.
- Unusual vibration, scraping, clicks, or impacts.
- New warning text or visual state changes.

## Why It Is Powerful

The board learns "normal" for one specific machine in one specific place. That local baseline is more useful than a generic model. picoClaw only wakes when the machine deviates.

## Chain

```text
learn baseline for several days
-> periodic image/audio snapshot
-> compare against normal state
-> classify off / idle / running / error
-> journal anomaly score
-> alert only on persistent deviation
```

## Useful Skills

- `machine_state_classifier`: off/idle/running/error.
- `indicator_led_reader`: LED status decoding.
- `analog_gauge_reader`: needle angle estimation.
- `audio_signature_drift`: current sound vs baseline.
- `startup_sequence_verify`: expected transition checks.
- `maintenance_event_detect`: unusual vibration/noise pattern.
- `baseline_learn`: normal ranges by time and state.

## Example Real Change

After a week, the board learns a pump's normal audio RMS and LED pattern. One morning the LED is normal but the audio signature shifts. picoClaw creates a `pump_cavitation_candidate` monitor and raises the capture frequency around startup.

