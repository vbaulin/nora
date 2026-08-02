---
title: Run and Extend an Experiment
summary: Build the executor, verify the board, execute a read-only task, and convert it into a monitor.
order: 7
eyebrow: Chapter 7
---

# Run and Extend an Experiment

This chapter joins the previous abstractions into one operational path. The
first task is intentionally read-only.

## Build

On a development machine with Go 1.21 or later:

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 \
  go build -o nano-os-agent main.go
```

Copy the binary and repository runtime to the configured LicheeRV Nano using
the board installation and synchronization procedures in
[INSTALL_BOARD.md](https://github.com/vbaulin/nora/blob/main/INSTALL_BOARD.md).

## Verify the services

On the board:

```bash
wget -qO- http://127.0.0.1:18790/health
wget -qO- http://127.0.0.1:18790/ready
/opt/picoclaw/picoclaw skills list
```

`/health` shows that the gateway process responds. `/ready` verifies that the
runtime can serve requests. The skills list shows the routes PicoClaw should
inspect before answering board questions.

The web interface exposes the same evidence at:

```text
http://BOARD_IP:18800/runtime
http://BOARD_IP:18800/nano-os-agent
```

## Execute a one-shot task

Save this as `/tmp/tutorial_system_snapshot.yaml`:

```yaml
- id: tutorial_system_snapshot
  name: "Tutorial system snapshot"
  priority: 1
  status: pending
  steps:
    - id: read_system
      action: call_skill
      save_as: system
      parameters:
        skill_name: system_info
      expect:
        ram_total_mb: ">=1"
      timeout: 15
      on_fail: block
```

Run and inspect it:

```bash
/root/nano-os-agent/nano-os-agent \
  --once /tmp/tutorial_system_snapshot.yaml

tail -1 /root/nano-os-agent/experiments.jsonl 2>/dev/null \
  || tail -1 /tmp/experiments.jsonl
```

Confirm the task ID, step counts, verdict, duration, and before/after metrics.
Do not evaluate success from prose alone.

## Extend it into a monitor

Replace the one-shot system skill with a sensor or scene-observation skill and
add a bounded repeat block:

```yaml
repeat:
  interval_sec: 600
  max_iterations: 144
  journal_path: /tmp/monitors/tutorial_observation.jsonl
  continue_on_fail: true
```

Keep the task at `status: template` in version control. Create a pending copy
only when the board, sensor, interval, storage budget, and stop condition are
confirmed.

## Add a proactive condition

An application adapter can ingest the released monitor summary and define a
rule such as:

```text
if focus_score falls below the calibrated limit twice:
    propose one focus inspection
    attach the representative frame
    wait for confirmation
```

The adapter should not rerun the complete experiment merely to answer a chat
question when a fresh released artifact already exists.

## Cross-domain examples

- **Microscope:** detect focus drift, then propose a focus check before the next
  high-value sample interval.
- **Fermentation:** detect a change in temperature or bubbling trend, then ask
  whether a manual sample or operation occurred.
- **Machine health:** detect LED/audio drift, then request one bounded physical
  inspection.
- **Environmental sensor:** validate identity and ranges, establish a baseline,
  then change the sampling interval only after a declared trigger.

Next: [see how Vineyard Guard implements the adapter layer](08-vineyard-guard.md).
