# Working with Physical Hardware

Nora is most useful when software must keep observing after everyone has left:
a camera following a sample overnight, a sensor station through bad weather, a
fermenter between laboratory visits, or a machine during normal operation.

Physical autonomy becomes useful only when the result is repeatable. A command
that worked once is not yet an experimental method. Nora therefore treats every
camera, sensor, actuator, and hardware analysis as a named capability with
known inputs, outputs, limits, and evidence.

## What This Gives You

| Without a reusable hardware route | With a Nora skill or task |
|---|---|
| A shell command works on one board and is forgotten | The capability has a name, parameters, units, timeout, and structured result |
| A temporary error stops the observation | Retries and failure behavior are declared once |
| The next researcher cannot reproduce the setup | The method and its validation travel with the experiment |
| A script produces an image but no context | The artifact remains linked to subject, time, task, and outcome |
| A new device requires another ad hoc integration | Discovery, validation, and promotion follow the same path |

The restriction on raw commands is not bureaucracy. It is how a physical action
becomes a scientific capability that can be reused and inspected.

## Example: One Camera Frame Becomes a Method

A direct camera command may depend on sensor initialization, reserved video
memory, exposure state, and board-specific binaries. A `capture_image` skill
can own those details and return:

```json
{
  "status": "success",
  "captured_at": "2026-08-18T09:30:00Z",
  "path": "/tmp/sample_A.jpg",
  "width": 1920,
  "height": 1080,
  "camera": "gc4653",
  "exposure_us": 8000
}
```

The next task can refer to the image path, verify that the file exists, run an
analysis, and store both results in the experiment journal. If capture fails,
the failure remains attached to the same method.

## Four Ways to Use Hardware

Choose the smallest route that matches the work.

| Need | Use |
|---|---|
| One immediate, known operation | An existing MCP tool |
| Several ordered operations | A task YAML |
| A reusable sensor, camera, NPU, or actuator capability | A registered skill |
| Hardware Nora has never seen | Read-only discovery, then a draft skill and validation experiments |

Examples:

- one frame: `capture_image`;
- camera plus object detection: a task that captures, checks, and calls
  `run_yolo`;
- five-minute environmental sampling for a day: a task with `repeat`;
- a new I2C sensor: bus inventory, candidate identification, draft decoder,
  repeated reference checks, then promotion.

## Teach Nora a New Device

An unknown sensor follows a visible sequence:

```text
discover -> identify candidate -> draft -> validate -> repeat -> promote
                                                   |
                                                   +-> revise when checks fail
```

### 1. Discover without changing the device

Start with a read-only inventory. Record bus, address, response stability, and
the board on which the observation was made.

### 2. Identify a candidate

Use markings, existing hardware maps, and source-attributed datasheets. A
candidate part number remains a hypothesis until physical behavior agrees.

### 3. Draft the capability

Declare inputs, output fields, units, time limit, and missing-device behavior.
The implementation may begin in Python or shell when vendor bindings require
it.

### 4. Validate against the physical system

A useful validation checks more than exit status:

- repeated readings under stable conditions;
- plausible range and units;
- comparison with a reference where available;
- artifact dimensions and non-zero size;
- missing or disconnected device behavior;
- memory and execution time; and
- recovery after a temporary failure.

### 5. Promote and recheck

Only the tested version becomes available for unattended tasks. Changed
hardware, firmware, or drift can return the skill to validation without
changing the rest of the experiment.

## Why the LLM Does Not Hold the Hardware Loop

Language models are useful when the next question is open: which measurement
separates two hypotheses, which existing skill matches an unfamiliar request,
or which failed step deserves investigation. They are poor timing loops for a
camera or actuator.

Nora keeps those roles separate:

```text
PicoClaw interprets intent and selects a capability.
nano-os-agent executes the physical method and records the result.
The research engine studies the resulting evidence.
A person confirms consequential changes.
```

This arrangement also works when the network is absent. The board can complete
its declared sampling and journal locally, then communicate later.

## Hardware Routes Included in This Repository

| Hardware or signal | Relevant skills |
|---|---|
| Camera capture and state | `camera_init`, `capture_image`, `capture_video`, `vision_state_sync` |
| NPU vision | `run_yolo`, `tpu_detect`, `tpu_pose`, `tpu_face` |
| Audio | `capture_audio`, `audio_event_detect`, `audio_interaction` |
| Environmental inputs | `sensor_fusion_snapshot`, `agri_env_probe`, `adc_read` |
| GPIO and PWM | `gpio_control`, `pwm_control` |
| Diagnostics | `hardware_diagnostic`, `system_info`, `npu_info` |
| Skill development | `validate_skill`, `promote_skill`, `native_compile` |

Availability depends on the board image and attached devices. A hardware skill
declares that requirement and is skipped on an ordinary laptop or VM.

## Technical Route Reference

PicoClaw should inspect registered skills before operating a board. The
preferred order is:

1. existing MCP tool;
2. existing task;
3. existing skill;
4. new draft followed by validation.

Direct device commands bypass task timing, retries, memory limits, journaling,
state updates, and capability reuse. They remain appropriate when a maintainer
is explicitly debugging Nora itself, not when the system is running a normal
experiment.

| Operation | Normal route |
|---|---|
| Capture one image | MCP `capture_image` |
| Recover camera state | `camera_init` or `vision_state_sync` |
| Run object detection | `run_yolo` |
| Read one environmental snapshot | `sensor_fusion_snapshot` |
| Run a multi-stage observation | Task YAML |
| Run a multi-day monitor | Task with bounded `repeat` and `journal_path` |
| Add unknown hardware | Draft, validate, experiment, promote |

## Continue

- [Run your first observer](docs/proactive-agent/07-run-an-experiment.md)
- [Teach Nora a new instrument](docs/proactive-agent/03-skill-lifecycle.md)
- [Automatic laboratory experiments](docs/applications/automatic-lab-experiments.md)
- [Board installation](INSTALL_BOARD.md)
