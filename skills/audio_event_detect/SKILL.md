---
name: audio_event_detect
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 20
parameters:
  - name: audio_path
    type: string
    default: /tmp/capture.wav
  - name: threshold_rms
    type: float
    default: 600
returns:
  - status
  - event_detected
  - rms
  - peak
---
# audio_event_detect
Detects simple environmental audio events from a WAV file using RMS and peak amplitude.
