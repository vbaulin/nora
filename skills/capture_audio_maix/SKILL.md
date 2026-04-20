---
name: capture_audio_maix
exec_type: python
command: python3 run.py
input_format: env
output_format: json
timeout: 30
parameters:
  - name: duration
    type: int
    default: 5
  - name: output_path
    type: string
    default: "/tmp/audio.wav"
---
# Description
Captures audio via maix.audio library without blocking the hardware.
Compatible with PicoClaw running in the background.
