# nano-os-agent: Deterministic Executor for Autonomous Scientific Experiments

![Nano-os-agent](images/Nano-os-Agent.jpg)

**nano-os-agent** turns a low-cost [LicheeRV Nano board](https://wiki.sipeed.com/hardware/en/lichee/RV_Nano/1_intro.html) (~$10) into a patient autonomous experiment station. It is the deterministic body for **[picoClaw](https://picoclaw.io/)**: Ultra-light-weight AI agent adapted for such board. This tool makes a separation of stochastic intelligence from deterministic execution. PicoClaw decides goals and asks for reasoning over WiFi, while nano-os-agent runs camera, TPU, microphone, sensors, skills, retries, journals, and long-term monitoring on the board. PicoClaw uses OS-level tools to orchestrate nano-os-agent, providing robust execution with built-in fault tolerance and automated recovery.

The central claim is simple: AI should design or revise experiments, not babysit the hardware loop. It gives intent once. With about 1 W power consumption the board can act for minutes, hours, or days, recording real-world evidence and registering the skill only when all real-world checks and experiments are passed. The original picoClaw gate was patched in such a way that before replying to user the board always checks the skills and runs real experiments and not replying from memory.

It is designed to be universal. The same runtime can monitor a vineyard, count Petri dish colonies, run microscope timelapse observations, detect reaction endpoints, build field datasets, or verify robotic actions. The useful abstraction is not "camera + mic + TPU"; it is a small scientific agent running a closed evidence loop:

```text
observe -> perturb -> measure -> learn -> summarize
```

The current end-to-end reference deployment is Vineyard Guard: a field board that runs disease-risk models, weather forecasts, Telegram notifications, Supabase synchronization, and farmer feedback capture. That application is intentionally visible in this repository because it exercises the whole stack under real timing, network, and operational constraints.

The same executor can also watch grapes ripen, detect grass stress, run lab protocols, verify robot actions, collect datasets, and promote new skills from local evidence.
It can also run bounded active-inference-style loops: maintain a small belief state, choose the next local action, observe the result, and update the belief without waking the LLM.

![LicheeRV Nano Hardware Interface](images/LicheeRV%20Nano.jpg)

![Typical Workflow](images/grapes-experiment.jpg)

## Why This Matters

Most AI hardware projects fail at the boundary between language and physics. The model can plan, but real experiments have driver quirks, memory pressure, camera initialization, NPU model formats, audio contention, flaky sensors, changing illumination, slow biological dynamics, and strict timing requirements.

nano-os-agent makes that boundary boring:

- **picoClaw is the brain**: asks questions, designs experiments, writes or improves skills, uses the LLM when reasoning is worth the WiFi/token cost.
- **nano-os-agent is the field executor**: runs deterministic chains, handles retries, records evidence, exposes MCP tools, and keeps working without supervision.
- **Skills are the evolving hands**: camera, TPU, microphone, GPIO, I2C, color analysis, event detection, learned classifiers, and future board-specific abilities.
- **Journals are memory**: every experiment creates before/after metrics and compact JSONL evidence that picoClaw can read later.

The Vineyard Guard deployment is the working example of this split under field
conditions. picoClaw asks for a daily risk update or neighbour refresh;
nano-os-agent runs a locked skill/task; and the adjacent Goidanich project
handles Supabase agents, feedback events, model deltas, released shared models,
and SQLite risk rows. See
[picoClaw, nano-os-agent, and Goidanich coordination](PICOCLAW_GOIDANICH_COORDINATION.md).

## Hardware Boundary Contract

picoClaw should never treat the board as a full Linux machine and start poking
camera, TPU, GPIO, I2C, PWM, or audio devices directly. Hardware access goes
through nano-os-agent:

```text
picoClaw intent
  -> MCP tool or task YAML
  -> nano-os-agent skill/native handler
  -> hardware
  -> JSON result + experiment journal
```

Bad pattern:

```text
picoClaw shell -> v4l2-ctl / cvi_tdl_yolo / i2cset / sysfs PWM write
```

Good pattern:

```text
picoClaw -> call MCP capture_image
picoClaw -> write task calling run_yolo
picoClaw -> create/validate/promote a skill
```

This keeps retries, timeouts, memory pressure, state, safety policy, and
experiment evidence in one deterministic place.

For the short version that should be loaded into picoClaw itself, use
[PICOCLAW_ORCHESTRATOR_PROMPT.md](PICOCLAW_ORCHESTRATOR_PROMPT.md).

## Application Atlas

Each application is a different way to use the same core loop: local sensing, local action, compact evidence, and occasional high-level reasoning. Vineyard Guard is listed first because it is the current complete reference deployment; the runtime itself is not limited to agriculture.

- [Autonomous vineyard and plant research](docs/applications/vineyard-plant-research.md) - phenology, ripeness, leaf stress, wetness, and growth trends.
- [Vineyard disease risk models](docs/applications/vineyard-disease-risk-models.md) - Goidanich, Rossi, powdery mildew priors, personalized risk, and farmer feedback.
- [Vineyard Guard runtime](VINEYARD_GUARD.md) - the field-board application layer: daily reports, Telegram policy, Supabase sync, product catalog, and farm-health hardware routing.
- [picoClaw, nano-os-agent, and Goidanich coordination](PICOCLAW_GOIDANICH_COORDINATION.md) - smooth task/skill control for cron jobs, neighbour refresh, and federated learning.
- [PicoClaw gateway board sync](docs/picoclaw-gateway-board-sync.md) - rebuild and deploy the PicoClaw launcher/gateway pair without fragmenting skills.
- [PicoClaw webapp and nano-os-agent integration](docs/picoclaw-nano-webapp-integration.md) - `/runtime` UI for platform modules, installed apps, hardware discovery, tasks, skills, journals, Telegram, and Vineyard Guard state.
- [Grass and field motion intelligence](docs/applications/grass-field-motion.md) - wind proxy, water stress, mowing events, and day/night color changes.
- [Automatic lab experiment runner](docs/applications/automatic-lab-experiments.md) - timed sample observation, reaction endpoints, liquid levels, germination, and protocol search.
- [Microscope timelapse station](docs/applications/microscope-timelapse.md) - focus checks, illumination normalization, segmentation, growth curves, and anomaly-triggered sampling.
- [Wine fermentation monitor](docs/applications/wine-fermentation-monitor.md) - alcohol-conversion proxies, pH/temperature trends, bubbling, turbidity, and batch knowledge graphs.
- [Petri dish colony counting](docs/applications/petri-colony-counting.md) - colony count, growth curves, contamination cues, inhibition zones, and treatment/control comparison.
- [Closed-loop robot manipulation](docs/applications/robot-manipulation.md) - visual servoing, actuation verification, safe retries, and local reflex loops.
- [Active inference tasks](docs/applications/active-inference-tasks.md) - belief updates, action scoring, local policy loops, and preferred observations.
- [Environmental event sentinel](docs/applications/environmental-event-sentinel.md) - audio triggers, visual confirmation, storm cues, I2C/system snapshots, and evidence packs.
- [Machine health monitor](docs/applications/machine-health-monitor.md) - status LEDs, gauges, startup checks, audio drift, and machine-specific baselines.
- [Automatic dataset builder](docs/applications/automatic-dataset-builder.md) - hard negatives, uncertainty capture, local labels, and model/skill evaluation.
- [Scientific reflexes](docs/applications/scientific-reflexes.md) - baseline learning, anomaly scoring, adaptive intervals, change points, and daily summaries.
- [Self-improving field/lab observer](docs/applications/self-improving-field-lab-observer.md) - the full loop where the board becomes specialized to its place.

## Agentic Architecture

```mermaid
flowchart LR
    U["User / Goal"] --> P["picoClaw<br/>planner + LLM gateway"]
    P -->|"writes task YAML<br/>or calls MCP tool"| N["nano-os-agent<br/>deterministic Go executor"]
    N --> C["Camera<br/>CSI / Maix / SDK"]
    N --> T["TPU / NPU<br/>Maix Python + cvimodel"]
    N --> M["Microphone<br/>audio events"]
    N --> S["Sensors<br/>I2C / ADC / PWM / system"]
    N --> K["Skills<br/>native + compiled + adapters"]
    K --> J["JSONL journals<br/>experiments + monitors"]
    J --> P
    P -->|"learns, patches,<br/>promotes skills"| K
```

The important loop is not "LLM calls shell forever." It is **intent -> deterministic chain -> evidence -> better skill**.

## What Runs Locally

```mermaid
flowchart TD
    Task["tasks/*.yaml"] --> Executor["nano-os-agent"]
    Executor --> Step1["step: capture image"]
    Step1 --> Step2["step: run TPU detection"]
    Step2 --> Step3["step: color / event analysis"]
    Step3 --> Step4["repeat every N seconds"]
    Step4 --> Journal["/tmp/monitors/*.jsonl"]
    Journal --> Summary["monitor_summary"]
    Summary --> Brain["picoClaw reads compact result"]
```

Task steps can:

- call any skill with `call_skill`;
- repeat locally with `repeat.interval_sec`;
- write one JSON object per observation to a journal;
- continue through temporary failures;
- pass outputs to later steps using `${step_id.field}`;
- finish with a summary instead of thousands of chat turns.

Example:

```yaml
- id: grape_growth_monitor
  name: "Wine Grape Growth and Ripeness Monitor"
  priority: 6
  status: pending
  steps:
    - id: observe_grapes
      action: call_skill
      save_as: grapes
      parameters:
        skill_name: observe_scene
        label: grapes
        output_dir: /tmp/observations/grapes
      expect: {status: success}
      repeat:
        interval_sec: 3600
        max_iterations: 168
        journal_path: /tmp/monitors/grape_growth.jsonl
        continue_on_fail: true

    - id: summarize_grapes
      action: call_skill
      parameters:
        skill_name: monitor_summary
        journal_path: /tmp/monitors/grape_growth.jsonl
      expect: {status: success}
```

That one task can observe for a week. picoClaw does not need to spend tokens every hour.

## A Real Change Example

Imagine the board is installed near a grape row.

1. picoClaw writes `grape_growth_monitor` and marks it `pending`.
2. nano-os-agent captures one frame every hour.
3. `observe_scene` runs camera capture, TPU detection, and color analysis.
4. The board journals compact rows like:

```json
{
  "timestamp": "2026-05-01T09:00:00+0200",
  "label": "grapes",
  "image_path": "/tmp/observations/grapes/grapes_20260501_090000.jpg",
  "object_count": 4,
  "color": {
    "green_ratio": 0.41,
    "purple_ratio": 0.12,
    "ripeness_estimate": 0.22,
    "stress_estimate": 0.08
  }
}
```

1. After two days, `monitor_summary` reports that `yellow_ratio` and `brown_ratio` are rising quickly while visible cluster count is dropping.
2. picoClaw asks the LLM once: "This trend may indicate leaf stress or bad framing. What should we test?"
3. picoClaw creates a draft skill: `leaf_stress_score`.
4. nano-os-agent validates it with `validate_skill`, runs an experiment, and promotes it with `promote_skill` only if it works.
5. The running monitor is updated to include the new skill.

The board has made a real change: it moved from generic observation to a new domain-specific measurement, without changing the core Go executor and without asking the LLM to watch every frame.

## Skill Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Draft: picoClaw creates skill
    Draft --> Validate: validate_skill
    Validate --> Draft: schema or safety fail
    Validate --> Experiment: run task N times
    Experiment --> Draft: metrics fail
    Experiment --> Evidence: metrics pass
    Evidence --> Promote: journal + artifacts stored
    Promote --> Active: promote_skill
    Active --> Monitor: used in long chains
    Monitor --> Revalidate: drift or error
    Revalidate --> Active: still valid
    Revalidate --> Draft: needs revision
    Active --> Retired: superseded or unsafe
    Retired --> [*]
```

This separation is deliberate:

- Draft skills can be creative and imperfect.
- Promoted skills are trusted by unattended monitors.
- Evidence and artifacts survive promotion so the decision is auditable.
- Active skills can be revalidated or retired when hardware, models, or field conditions change.
- The Go executor stays small and reliable.

Runtime preference:

1. **Go in `main.go`** for deterministic primitives, MCP, task execution, safety, and journaling.
2. **C/C++ SDK binaries** for camera, TPU, and zero-copy vision.
3. **Compiled Go helper binaries** for CPU-side analysis and summaries.
4. **Python adapters** when the Maix/vendor stack exposes a working binding there first, or when picoClaw is prototyping.

The intended path is:

```text
prototype quickly -> validate with repeated experiments -> rewrite as compiled helper -> promote
```

## Hardware Capabilities

The LicheeRV Nano gives the agent a compact but serious sensor/compute stack:

- **Camera**: CSI MIPI capture, frame journaling, color indices, visual change detection.
- **TPU/NPU**: INT8 `.cvimodel` inference through the Maix Python `run_yolo`
  skill, with CVI/TDL paths kept as fallback/research routes.
- **Microphone**: audio capture and local event detection.
- **System probes**: memory, thermal, video devices, dmesg, I2C, ADC, PWM, GPIO.
- **MCP server**: picoClaw can call board tools directly.
- **File-driven autonomy**: tasks and skills can be created, validated, and promoted locally.

## MCP Tools Exposed to picoClaw

Typical tools:

- `capture_image` - capture a CSI frame.
- `capture_audio` - record a short WAV sample.
- `capture_video` - record a short video clip.
- `run_yolo` - run Maix Python YOLOv8/YOLOv11 `.cvimodel` detection and attach perception atoms when possible.
- `analyze_image` - convert detections into structured perception atoms.
- `scan_i2c` - scan an I2C bus.
- `probe_cvitek` - inspect camera/NPU related board state.
- `adc_read` - read SARADC values.
- `pwm_control` - control PWM channels.
- `time_sync` - synchronize or inspect board time.
- `call_skill` - call any registered skill by name.
- `get_visual_truth`, `get_experiments`, `get_hypotheses` - read compact state.

## Built-In Monitoring Templates

The repository includes long-running templates marked `status: template` so they do not start accidentally:

- [tasks/020_grape_growth_monitor.yaml](tasks/020_grape_growth_monitor.yaml) - grape color, ripeness, stress, and visible object trend.
- [tasks/021_grass_day_monitor.yaml](tasks/021_grass_day_monitor.yaml) - grass movement and color throughout the day.
- [tasks/022_environment_event_guard.yaml](tasks/022_environment_event_guard.yaml) - microphone/system/environment event journal.
- [tasks/023_promote_learned_skill.yaml](tasks/023_promote_learned_skill.yaml) - validate and promote a picoClaw-created skill.

## Why The Deterministic Executor Is The Must

An LLM is excellent at asking "what should we try next?" It is poor at being a reliable camera driver, process supervisor, file logger, retry loop, and week-long sensor operator.

nano-os-agent gives picoClaw a body with reflexes:

- It can fail locally and recover locally.
- It can collect evidence while the LLM is offline.
- It can reduce thousands of samples to one trend summary.
- It can promote learned skills without recompiling the executor.
- It can turn a cheap board into a domain-specific observer over time.

That is the agentic jump: not a chatbot attached to hardware, but a hardware organism that can be given missions.

## Build

Cross-compile for the SG2002 board:

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nano-os-agent main.go
```

Run on the board:

```bash
/root/nano-os-agent
```

The agent scans `tasks/*.yaml`, exposes MCP on `0.0.0.0:9600`, writes state to `state.json`, and appends experiment evidence to the configured journal.

For board setup, library paths, and CMA notes, see [INSTALL_BOARD.md](INSTALL_BOARD.md).

For the PicoClaw launcher/gateway rebuild used by the board webapp and
Telegram runtime, see
[PicoClaw gateway board sync](docs/picoclaw-gateway-board-sync.md).

## Stability Notes

- Prefer `/tmp` for transient images, audio, and monitor journals to reduce SD-card wear.
- Promote compiled Go/C/C++ skills for hot loops and long-term monitors.
- Keep Python skills where they are the most reliable available adapter, especially for Maix SDK bindings.
- Use `status: template` for example tasks that should not launch automatically.
- Use `monitor_summary` to give picoClaw compact trend evidence instead of raw logs.
