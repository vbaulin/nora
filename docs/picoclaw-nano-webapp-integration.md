# PicoClaw Webapp And nano-os-agent Integration

This document defines the target integration between the PicoClaw webapp and
nano-os-agent. The goal is to make the webapp a control surface for the board
executor, not a separate shell terminal.

## Design Goal

PicoClaw should infer available hardware, expose it in the webapp, and connect
new sensors through nano-os-agent without bypassing the deterministic executor.

The correct control path is:

```text
webapp or Telegram intent
  -> PicoClaw gateway
  -> nano-os-agent MCP tool, task YAML, or skill
  -> hardware driver or safe probe
  -> structured JSON result
  -> journaled evidence
  -> webapp status and user response
```

The incorrect control path is:

```text
webapp or Telegram intent
  -> raw shell probe from PicoClaw
  -> camera/GPIO/I2C/NPU side effects without task evidence
```

## Current Webapp Sections

The launcher exposes `/runtime` as the board runtime page. It is intentionally
split into platform modules and installed apps:

- **Platform: PicoClaw Gateway**: model config, Telegram/Pico channels,
  skills/tools, scheduler/cron jobs, logs, `/ready`, and `/health`.
- **Platform: nano-os-agent**: read-only hardware inventory, task queue,
  running experiment processes, skill validation/promote evidence, hardware
  capability map, experiment journals, and artifacts.
- **Apps**: application modules that activate only when their runtime/config is
  present. Vineyard Guard is active when the private Goidanich checkout exists.
  The response schema already leaves room for other apps, for example AdBlock.

The authenticated API behind this page is:

```text
GET /api/runtime/status
```

For compatibility, the same payload is also available at:

```text
GET /api/vineyard-guard/status
```

The launcher exposes `/nano-os-agent` as a first-class nano-os-agent operation
surface, placed directly after Chat and before Models in the sidebar. It is
intentionally separate from chat: chat is useful for intent parsing and
explanation, while the nano-os-agent tab is the deterministic place to inspect
queued tasks, launch safe one-shot tasks, and review background artifacts such
as daily Vineyard Guard plots.

`/task-runner` remains available as a compatibility route, but the user-facing
navigation should use `/nano-os-agent`.

The authenticated API behind this page is:

```text
GET  /api/task-runner/status
POST /api/task-runner/tasks/run
GET  /api/task-runner/artifact?path=<absolute-allowed-path>
DELETE /api/task-runner/artifact?path=<absolute-allowed-path>
```

The run endpoint accepts only task YAML files under the configured
nano-os-agent task directories. It rejects direct shell tasks and repeated
monitors from the web one-shot route. Long-running monitors remain the
responsibility of the nano-os-agent executor and task journal.

## Automatic Hardware Discovery

Discovery should be conservative and evidence-driven:

1. Start with read-only inventory from nano-os-agent.
2. Enumerate known safe surfaces: `/dev/i2c-*`, `/sys/bus/i2c/devices`,
   `/dev/video*`, `/sys/class/gpio`, `/sys/class/pwm`, ADC entries, USB
   devices, kernel modules, and board-specific state files.
3. Match inventory against known skills such as `scan_i2c`, `capture_image`,
   `run_yolo`, `capture_audio`, `adc_read`, `pwm_control`, and
   `sensor_fusion_snapshot`.
4. For an unknown I2C or sensor candidate, create a nano-os-agent task that
   probes read-only registers first.
5. If the task result is stable, create a draft skill.
6. Validate the draft skill with repeated runs and explicit expected fields.
7. Promote only validated skills into unattended monitors.
8. Surface the new capability in the webapp with its evidence and limitations.

Discovery must never write GPIO, PWM, I2C registers, camera controls, or NPU
state until a skill declares the operation and the task contract records the
evidence.

## Implemented Task Runner Shape

The current Task Runner status payload reports:

- nano-os-agent binary path, ELF format, running state, and whether it is
  executable;
- task inventory from `/root/nano-os-agent/tasks` and
  `/root/.picoclaw/workspace/tasks`;
- recent one-shot runs from `/tmp/nano-task-runner`;
- background PicoClaw cron jobs from
  `/root/.picoclaw/workspace/cron/jobs.json`;
- artifacts from nano-os-agent, Vineyard Guard results, Telegram outbox,
  observations, monitors, and task-runner logs.
- in-page previews for images, Markdown, JSON, text, and logs;
- guarded deletion for files under the allowed artifact directories.

Verified UI screenshot:

![nano-os-agent Task Runner Markdown preview](assets/picoclaw-nano-agent-md-preview.png)

The web runner starts nano-os-agent in one-shot mode:

```text
/root/nano-os-agent/nano-os-agent --once /tmp/nano-task-runner/tasks/<run>.yaml
```

This keeps web-triggered operations journaled and bounded. The normal
nano-os-agent daemon/task loop is not replaced by the webapp.

## Future API Shape

The current `/api/runtime/status` and `/api/task-runner/status` endpoints are
compact. If deeper control is needed, the webapp can later add endpoints that
proxy nano-os-agent state and task submission. Suggested endpoints:

```text
GET  /api/nano/status
GET  /api/nano/hardware
GET  /api/nano/skills
GET  /api/nano/tasks
POST /api/nano/tasks
GET  /api/nano/experiments
GET  /api/nano/artifacts
POST /api/nano/skills/validate
POST /api/nano/skills/promote
```

Each endpoint should return compact structured JSON. Large artifacts should be
linked by path or served through the existing attachment/media mechanism.

## Runtime Contract

PicoClaw may reason about what to try, but nano-os-agent performs the physical
operation. This preserves:

- retries;
- memory limits;
- timeouts;
- journals;
- before/after metrics;
- long-running monitor semantics;
- safe promotion from draft skill to trusted skill.

For hardware questions, the first action is always capability discovery:

```text
list skills/tools
inspect nano-os-agent tasks and current task/artifact state
choose existing capability
run skill/tool/task
answer from structured result
```

If no matching capability exists, PicoClaw should generate a draft task or
draft skill and validate it before calling the hardware operation reliable.

For Telegram and chat, this is enforced by the gateway prompt and finalization
guard. Board, vineyard, hardware, forecast, treatment, plot, scheduler, cron,
camera, sensor, and nano-os-agent requests must execute a relevant tool/skill or
inspect current local state in the same turn. If no current evidence exists,
the gateway should refuse to answer from session memory.

## Board Recovery Implication

The webapp should display enough runtime state to diagnose board recovery
without SSH:

- gateway process running/not running;
- launcher process running/not running;
- `/ready` status;
- configured model count and default model;
- active channels, especially Telegram and Pico;
- nano-os-agent reachable/unreachable;
- mounted skill count and invalid skill warnings;
- current time, timezone, and last time-sync result.

This would have made the recent recovery failure explicit: the launcher and
gateway were rebuilt from different config expectations, and Telegram was
configured but not exported under the new token variable.
