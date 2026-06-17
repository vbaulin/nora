---
name: audio_share_via_picoclaw
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 10
returns:
  - status
  - message
  - note
---
# audio_share_via_picoclaw

Board-research fallback stub from `skills-old/`.

Use when local board audio capture is unavailable and picoClaw should coordinate
audio sharing from the host-side environment instead of pretending the board
microphone path is healthy.
