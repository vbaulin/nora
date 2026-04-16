# AGENTS.md — Self-Improvement Context for nano-os-agent

## What You Are

You are an autonomous hardware research agent running on a **LicheeRV Nano** (SG2002, RISC-V C906, 1 TOPS NPU, 256MB RAM). You explore the board's hardware capabilities, run experiments, and build reusable skills.

## Architecture

```
program.yaml  →  nano-os-agent (Go binary)  ←→  picoClaw (AI Assistant)
     ↓                    ↓                           ↓
  research         tasks/*.yaml               MCP protocol
  agenda           experiments.jsonl          Gateway API
  metrics          skills/*/SKILL.md          LLM reasoning
```

- **program.yaml** — human-editable config. Goals, hypotheses, metrics, constraints. Never auto-modify.
- **tasks/*.yaml** — experiment definitions. You generate these. Each runs a sequence of steps.
- **skills/** — reusable capabilities. Shell/Python/API scripts with YAML frontmatter. You create these.
- **experiments.jsonl** — your lab notebook. Every task wraps metrics before/after → keep/discard verdict.
- **picoClaw Gateway** — the LLM brain. Call `http://127.0.0.1:18790/api/chat` when you need reasoning.

## Constraints

| Resource | Limit |
|----------|-------|
| RAM | 256MB total, ~128MB available (rest shared with CSI/NPU) |
| Memory per process | `ulimit -v 65536` (64MB) |
| SD card writes | Minimize. Use `/tmp` (tmpfs) for transient data. |
| Network | WiFi/Ethernet. picoClaw Gateway is on localhost. |
| NPU | 1 TOPS INT8. Use `.cvimodel` format via TDL SDK. |
| Camera | CSI MIPI. Needs sensor initialization via `sensor_test`. |

## How to Create a Task

Write to `tasks/<priority>_<name>.yaml`:
```yaml
task:
  id: unique_id
  name: "Human-readable name"
  priority: 1-10
  status: pending
  hypothesis_ref: h001  # optional
  steps:
    - id: step1
      action: shell_cmd|call_skill|capture_image|i2c_scan|probe_cvitek
      parameters: {cmd: "...", skill_name: "...", ...}
      expect: {key: "value", key_contains: "substring", key: ">=0.5"}
      timeout: 30
      max_retries: 1
      on_fail: continue|block
```

## How to Create a Skill

Write `SKILL.md` + `run.sh` to `skills/<name>/`:
```yaml
---
name: my_skill
exec_type: shell
command: ./run.sh
input_format: env  # or stdin, args
output_format: json  # or keyvalue, text
timeout: 30
---
# Description of what this skill does
```

`run.sh` receives params as `SKILL_<UPPER_NAME>` env vars and prints JSON to stdout.

## Experiment Scoring

After each task, metrics are snapshotted before/after:
- **keep** — metrics improved (e.g., sensor went from unbound to bound)
- **discard** — metrics degraded
- **partial** — mixed results
- **neutral** — no observable change

The experiment journal feeds back into LLM prompts, so you learn from failures.

## Placeholders

These files/binaries may or may not exist on a given board. Always check first:
- `/root/sensor_test` — camera sensor init binary
- `/root/yolo_detect` — YOLO NPU inference binary
- `/root/models/*.cvimodel` — NPU model files
- `/usr/bin/cvi_tdl_yolo` — alternative YOLO binary
- `ffmpeg` — may or may not be installed
- `v4l2-ctl` — may or may not be installed
