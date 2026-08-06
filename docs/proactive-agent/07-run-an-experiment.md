---
title: Run and Extend an Experiment
summary: Start on a laptop, move to hardware, turn one reading into a monitor, and let the board research what it recorded.
order: 7
eyebrow: Chapter 7
---

# Run and Extend an Experiment

This chapter is the operational path from nothing to a board that studies its
own measurements. Everything up to hardware runs on a laptop with Python 3
alone. No board, no install, no keys.

## Part 1 — On your laptop

### Run one analysis

From the repository root, ask a question about a file you make yourself:

```bash
mkdir -p /tmp/nora-lab && python3 - <<'PY'
import json, datetime as dt
now = dt.datetime.now(dt.timezone.utc)
rows = [
    {
        "timestamp": (now - dt.timedelta(hours=(36 - i))).isoformat(),
        "weight_g": round(200 + (0 if i < 18 else 14) + (i % 3) * 0.4, 2),
    }
    for i in range(36)
]
open("/tmp/nora-lab/scale.jsonl", "w").write("\n".join(json.dumps(r) for r in rows))
PY
printf '%s' '{"mode":"investigate","state_dir":"/tmp/nora-lab/state","analysis":"level_shift","subject":"scale","params":{"source":{"kind":"journal","path":"/tmp/nora-lab/scale.jsonl"},"key":"weight_g"}}' | ./skills/research_agent/run.sh
```

The verdict is `material_unresolved`: the second half of the record sits about
14 g above the first, far beyond the within-half spread. The finding names its
own limitation — a level shift is a change in the record, not an explanation
for it.

### Let it find the question itself

Point a cycle at the directory instead of naming an analysis:

```bash
printf '%s' '{"mode":"cycle","state_dir":"/tmp/nora-lab/state","journal_dirs":"/tmp/nora-lab"}' | ./skills/research_agent/run.sh
```

`raised` shows the question the scan wrote for itself. Run the command a second
time: `raised` and `investigated` are both empty. A question it already knows is
not news, and a question it could not close is re-checked on an interval —
every six hours by default — rather than re-derived every cycle.

### Read the state

```bash
printf '%s' '{"mode":"questions","state_dir":"/tmp/nora-lab/state"}' | ./skills/research_agent/run.sh
printf '%s' '{"mode":"reportable","state_dir":"/tmp/nora-lab/state"}' | ./skills/research_agent/run.sh
```

`reportable` is the list an adapter would deliver to a human. Everything else
stays on the board.

## Part 2 — On the board

### Build

On a development machine with Go 1.21 or later:

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent main.go
```

Copy the binary and repository runtime to the configured LicheeRV Nano using
[INSTALL_BOARD.md](https://github.com/vbaulin/nora/blob/main/INSTALL_BOARD.md).

### Verify the services

```bash
wget -qO- http://127.0.0.1:18790/health
wget -qO- http://127.0.0.1:18790/ready
/opt/picoclaw/picoclaw skills list
```

`/health` shows that the gateway process responds, `/ready` that the runtime can
serve requests, and the skills list shows the routes to inspect before
answering any board question. The same evidence is served at
`http://BOARD_IP:18800/runtime` and `http://BOARD_IP:18800/nano-os-agent`.

### Execute a read-only task

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
/root/nano-os-agent/nano-os-agent --once /tmp/tutorial_system_snapshot.yaml
tail -1 /root/nano-os-agent/experiments.jsonl 2>/dev/null || tail -1 /tmp/experiments.jsonl
```

Confirm the task ID, step counts, verdict, duration, and before/after metrics.
Do not evaluate success from prose alone.

### Extend it into a monitor

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

### Let the board research the monitor

The journal your monitor writes is already a valid research input. Install the
cycle task:

```bash
cp tasks/029_autonomous_research_cycle.yaml /root/nano-os-agent/tasks/
```

It calls `research_agent mode=cycle` every fifteen minutes against
`/tmp/monitors`, bounded to three questions and twenty seconds, and appends
each finding to the same `experiments.jsonl` the executor uses. Findings are
therefore visible through the existing routes:

```bash
printf '%s' '{"mode":"reportable"}' | /root/nano-os-agent/skills/research_agent/run.sh
grep autonomous_research /root/nano-os-agent/experiments.jsonl | tail -3
```

### Deliver a finding to a human

The engine never sends messages. An adapter reads `reportable`, phrases the
finding in the operator's language, and asks. Vineyard Guard does this through
the Telegram outbox; a bench rig might print to a dashboard or open an issue.
The rule is the same everywhere: state the numbers, order the options by cost,
and accept "nothing for now" as an answer.

## Cross-domain examples

- **Microscope:** detect focus drift, then propose a focus check before the
  next high-value sample interval.
- **Fermentation:** detect a level shift in temperature or bubbling, then ask
  whether a manual operation occurred.
- **Machine health:** detect LED or audio drift, then request one bounded
  physical inspection.
- **Environmental sensor:** validate identity and ranges, establish a baseline,
  and change the sampling interval only after a declared trigger.

Each of these is the same engine with different parameters. The next chapter
shows how a domain declares them.

Next: [adapt it to your own domain](08-vineyard-guard.md).
