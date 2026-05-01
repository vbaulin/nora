# Autonomous Task Chains

`nano-os-agent` is designed to be a deterministic hardware executor. `picoClaw` is the high-level planner that can ask the LLM for strategy over WiFi, but the board should not need LLM tokens for repetitive sensing. The strongest architecture is:

```text
picoClaw decides intent once
  -> writes a YAML task
  -> nano-os-agent repeats local actions
  -> JSONL journals accumulate evidence
  -> picoClaw reads summaries or anomalies later
```

This is powerful because long-term observation is mostly patience, not reasoning. A grape cluster does not need a model call every hour; it needs consistent lighting notes, image paths, color indices, object counts, and a compact trend summary.

## Chain Primitives

Tasks support ordinary ordered steps plus long-running repeat blocks:

```yaml
repeat:
  interval_sec: 3600
  max_iterations: 168
  journal_path: /tmp/monitors/grape_growth.jsonl
  continue_on_fail: true
```

Each repeated iteration appends one compact JSON object to the journal. If a camera frame fails once, `continue_on_fail` lets the monitor keep running. This matters outdoors and on small boards where sensors can be temporarily busy.

Steps can also pass values forward:

```yaml
- id: audio
  action: call_skill
  save_as: audio
  parameters:
    skill_name: capture_audio
    output_path: /tmp/event.wav

- id: detect
  action: call_skill
  parameters:
    skill_name: audio_event_detect
    audio_path: ${audio.path}
```

The executor expands `${audio.path}` locally. picoClaw does not need to inspect the first result just to launch the second step.

## Built-In Monitoring Patterns

### Wine Grape Growth

Use `tasks/020_grape_growth_monitor.yaml` as a template. It calls `observe_scene` hourly, stores images under `/tmp/observations/grapes`, and journals compact observations to `/tmp/monitors/grape_growth.jsonl`.

The useful signals are:

- `purple_ratio` and `green_ratio` for ripening.
- `yellow_ratio` and `brown_ratio` for stress or disease hints.
- `ripeness_estimate` as a simple trend index.
- TPU detections and perception atoms for visible clusters or foreign objects.
- Image path and timestamp for later visual audit.

After many samples, `monitor_summary` reduces the journal to first/last/min/max/delta trends. picoClaw can read that summary and decide whether to change interval, lighting, model, or crop target.

### Grass Movement and Color

Use `tasks/021_grass_day_monitor.yaml`. A 15-minute interval is enough to capture light changes, wind movement, drying, watering effects, and color drift during the day.

This task is useful even without perfect semantic detection because color and frame-to-frame changes are strong local signals. A later skill can replace or extend the color analysis with optical flow or region tracking.

### Environmental Event Guard

Use `tasks/022_environment_event_guard.yaml`. It records lightweight system/environment snapshots into `/tmp/monitors/environment_events.jsonl`, then can combine microphone capture with local audio event detection.

Useful events include:

- sudden sound above RMS threshold;
- camera-visible movement after sound;
- temperature/sysfs changes;
- new or missing I2C devices;
- kernel messages indicating camera, TPU, or audio driver issues.

The goal is not to have the LLM watching. The goal is to have the board preserve enough evidence that picoClaw can later ask, "what changed today?"

## Learned Skill Lifecycle

picoClaw may create new skills, but trusted board behavior should have a promotion gate:

```text
skills_draft/my_skill/
  SKILL.md
  run.sh
  bin/my_skill

validate_skill -> promote_skill -> skills/my_skill/
```

`tasks/023_promote_learned_skill.yaml` is a template for this flow.

This keeps creativity and reliability separate. The LLM can experiment in draft space; the executor runs only validated promoted skills in unattended chains.

## Runtime Choice

For this board, compiled code is the preferred mature runtime:

- Use **Go in `main.go`** for deterministic primitives, task execution, safety, journaling, and MCP.
- Use **native C/C++ SDK binaries** for TPU, camera, and zero-copy vision paths.
- Use **compiled Go helper binaries** for CPU-side analysis and summaries when no vendor SDK is needed.
- Use **Python** when the Maix SDK gives the most reliable access today, or when picoClaw is prototyping a learned skill.

The intended path is:

```text
prototype quickly -> validate with repeated experiments -> rewrite as native/compiled helper -> promote
```

That lets the system learn fast without making the final long-running monitor depend on fragile prototype code.
