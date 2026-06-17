---
name: audio_interaction
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
parameters:
  - name: action
    type: string
    default: record
  - name: duration
    type: string
    default: 3
  - name: output_path
    type: string
    default: /tmp/record.wav
---
# Audio Interaction Skill
Handles audio recording and microphone configuration for the LicheeRV Nano.

## Usage
- **Record**: `action=record duration=5`
- **Stop**: `action=stop`
