# Hardware Boundary Contract

This document exists to prevent a common failure mode: picoClaw sees a shell and
tries to operate the LicheeRV Nano as if it were a full Linux workstation. That
breaks the architecture.

picoClaw is the planner. nano-os-agent is the hardware executor.

## Rule

All hardware operations must pass through one of:

1. MCP tool exposed by nano-os-agent.
2. Task YAML in `tasks/`.
3. Registered skill in `skills/`.
4. Draft skill validated and promoted into `skills/`.

Before debugging any board error, picoClaw must run this preflight:

1. `list_skills`
2. Search the returned skills for an existing capability.
3. Prefer the most specific skill or MCP tool.
4. Only create a new diagnostic task or draft skill if no existing skill fits.

Error messages are not the source of truth. Skills are the source of truth. If a
camera command reports `vb_pool`, `video`, `sensor`, or memory errors, picoClaw
should first run the known camera skill path instead of trying generic Linux
driver probes.

## Why

Direct shell commands bypass:

- board-specific fallback logic;
- timeout and retry handling;
- memory and SD-card write constraints;
- experiment journaling;
- state updates;
- task status;
- security checks;
- skill evolution and reuse.

## Bad Examples

Do not do this from picoClaw:

```bash
v4l2-ctl --device=/dev/video0 --stream-mmap
cvi_tdl_yolo /root/models/yolov8n.cvimodel /tmp/frame.jpg
i2cset -y 1 0x40 0x00 0xff
echo 1 > /sys/class/pwm/pwmchip0/pwm0/enable
while true; do python3 capture.py; sleep 30; done
```

These commands might work once, but the agent will not learn from them and the
board can be left in a bad state.

## Good Examples

Immediate action:

```text
MCP tools/call capture_image
MCP tools/call run_yolo
MCP tools/call adc_read
```

Experiment:

```yaml
- id: inspect_after_sound
  name: "Inspect scene after audio event"
  priority: 7
  status: pending
  steps:
    - id: audio
      action: call_skill
      save_as: audio
      parameters:
        skill_name: capture_audio
        output_path: /tmp/event.wav
    - id: event
      action: call_skill
      parameters:
        skill_name: audio_event_detect
        audio_path: ${audio.path}
    - id: image
      action: capture_image
      parameters:
        output_path: /tmp/event.jpg
```

New capability:

```text
picoClaw writes skills_draft/my_capability/
-> validate_skill
-> run experiment task
-> promote_skill
-> future tasks call my_capability
```

## Decision Table

| Need | Correct route |
| --- | --- |
| One camera frame | MCP `capture_image` |
| Camera init or vb_pool/video error | MCP `capture_image`, then `call_skill camera_init` or `call_skill vision_state_sync` |
| Camera + TPU scene state | `call_skill vision_state_sync` or `call_skill observe_scene` |
| NPU object detection | MCP `run_yolo` or `call_skill run_yolo` |
| One disease model status | MCP `call_skill` with `vineyard_disease_risk` |
| Multi-step experiment | Write `tasks/*.yaml` |
| Multi-day monitor | Task with `repeat` and `journal_path` |
| Missing capability | Draft skill, validate, promote |
| Board runtime debugging | Direct shell is allowed only when explicitly debugging nano-os-agent itself |

## Short Instruction For picoClaw

If a command touches hardware, do not run it directly. Convert it into a
nano-os-agent tool call, task step, or skill.

If you catch yourself saying "let me inspect `/dev/video*`", stop. Say "let me
list skills and run the existing camera path."
