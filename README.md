<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="nora turns a scientific question into observation, local investigation, and a useful human decision">
</p>

<p align="center">
  <a href="go.mod"><img alt="Go 1.21" src="https://img.shields.io/badge/Go-1.21-0b1410?style=flat-square&logo=go&logoColor=72d99b"></a>
  <a href="https://wiki.sipeed.com/hardware/en/lichee/RV_Nano/1_intro.html"><img alt="RISC-V SG2002" src="https://img.shields.io/badge/RISC--V-SG2002-0b1410?style=flat-square&logo=riscv&logoColor=72d99b"></a>
  <a href="https://vbaulin.github.io/nora/"><img alt="Interactive tutorial" src="https://img.shields.io/badge/tutorial-build_your_first_observer-173e2a?style=flat-square"></a>
  <a href="docs/applications/automatic-lab-experiments.md"><img alt="Application examples" src="https://img.shields.io/badge/examples-field_%2B_lab-173e2a?style=flat-square"></a>
</p>

# A small computer that can run an experiment, notice what changed, and investigate why

**nora** gives cameras, sensors, scientific models, and small edge computers a
shared way to work. You describe what to observe and what a valid result looks
like. Nora performs the measurements, keeps the images and numbers, looks for
patterns while the instrument is idle, and contacts a person when a decision
needs human knowledge.

The result is more than remote monitoring. A Nora installation can:

- keep an experiment running for hours, weeks, or a growing season without an
  LLM supervising every sample;
- discover that a signal shifted, saturated, disappeared, or began to precede
  another observation;
- connect a finding to the exact measurements and artifacts that produced it;
- learn a new sensor or analysis method through tested, reusable skills;
- ask one specific question through chat or Telegram, then incorporate the
  confirmed answer into the next investigation; and
- run on a 256 MB RISC-V board, a laptop, or a cloud VM.

[Start the guided tutorial](https://vbaulin.github.io/nora/) or
[run the sixty-second data experiment](#try-the-research-engine-in-sixty-seconds).

## What You Get

| Included | What it gives you |
|---|---|
| **Experiment runner** | YAML experiments with ordered steps, time limits, retries, expected results, and local repetition. |
| **Instrument skills** | Reusable camera, audio, I2C, ADC, GPIO, NPU, environmental sensing, and analysis capabilities. |
| **Local research engine** | Bounded analyses that inspect journals for shifts, disagreements, gaps, saturation, lead-lag relationships, and failed assumptions. |
| **Evidence notebook** | Timestamped measurements, images, task outcomes, model identity, and human corrections that remain connected to their source. |
| **Proactive companion** | A sparse observe-investigate-ask loop for chat or Telegram. It can start a conversation from new evidence instead of waiting for a prompt. |
| **Skill workshop** | Draft, validate, test, promote, and later recheck a newly learned hardware or software capability. |
| **Web control surface** | PicoClaw pages for chat, models, runtime health, tasks, skills, journals, and rendered artifacts. |
| **Application examples** | Microscope imaging, fermentation, machine health, environmental observation, dataset construction, and Vineyard Guard. |

## Why This Matters

Continuous observation is still expensive. A microscope cannot be watched all
night, a field specialist cannot visit every plot each morning, and a small
laboratory may not have staff to inspect every image or maintain a custom cloud
pipeline. Cheap sensors help collect data, but they do not decide which change
deserves attention or preserve how that conclusion was reached.

Nora addresses four practical constraints.

| Constraint | Nora's contribution |
|---|---|
| **Expert time is scarce** | Routine sampling and first-pass investigation happen locally. People receive a focused question or finding, not a stream of telemetry. |
| **Scientific automation is costly to integrate** | One task format and one skill interface connect cameras, sensors, models, and analysis scripts. A validated capability can be reused by the next experiment. |
| **Connectivity and data ownership vary** | Measurements and raw media can remain on the instrument. Network services are optional additions rather than prerequisites for the local loop. |
| **Generative explanations are not measurements** | Hardware work is executed by a deterministic runtime. Claims remain linked to current files, structured results, and explicit checks. |

This design is useful in community laboratories, rural monitoring, teaching,
small research groups, long-running field studies, and other settings where
attention and connectivity are limited. It does not replace a scientist,
technician, grower, or safety controller. It extends their reach by preparing
better evidence and asking narrower questions.

## What Autonomy Looks Like

Imagine a microscope recording crystal growth every ten minutes.

```text
09:00  A task captures an image and records focus, illumination, and edge speed.
15:20  The local engine detects a persistent change in edge speed.
15:21  It checks whether focus or illumination changed at the same time.
15:22  The change survives the local comparison, so one proposal is created.
15:23  The researcher receives:
       "Sample A changed growth regime at 15:10. Focus remained stable.
        Run a two-hour high-frequency sequence? Ref: EXP-17"
15:31  The researcher confirms. Nora queues the declared task and records why.
17:35  Images, measurements, and the task outcome are available for review.
```

No language model held the camera loop. No threshold crossing was silently
turned into a scientific fact. The machine did the repetitive work; the person
made the consequential choice.

<p align="center">
  <img src="assets/readme/research-loop.svg" width="100%" alt="Stored signals become locally tested questions, findings, and selective human decisions">
</p>

## Try the Research Engine in Sixty Seconds

The research engine uses standard-library Python. This example runs on a
laptop without a board, account, or external service.

```bash
git clone https://github.com/vbaulin/nora.git
cd nora

mkdir -p /tmp/nora-demo/monitors
python3 - <<'PY'
import datetime as dt
import json
import random

random.seed(1)
now = dt.datetime.now(dt.timezone.utc)
rows = [
    {
        "timestamp": (now - dt.timedelta(minutes=(48 - i) * 30)).isoformat(),
        "lux": min(100.0, round(random.gauss(86, 15), 1)),
        "temp_c": round(21 + random.gauss(0, 0.4), 2),
    }
    for i in range(48)
]
open("/tmp/nora-demo/monitors/light_probe.jsonl", "w").write(
    "\n".join(json.dumps(row) for row in rows)
)
PY

printf '%s' '{"mode":"cycle","state_dir":"/tmp/nora-demo/state","journal_dirs":"/tmp/nora-demo/monitors"}' \
  | ./skills/research_agent/run.sh
```

The synthetic light channel repeatedly reaches its upper limit. Nora finds
that pattern without a rule naming `lux`:

```json
{
  "status": "success",
  "raised": ["lux piles up against 100 instead of passing it"],
  "investigated": [{
    "subject": "light_probe",
    "analysis": "ceiling_saturation",
    "sample_size": 48,
    "verdict": "material_unresolved"
  }]
}
```

The temperature channel varies normally, so it produces no finding. Silence
is a normal result when the evidence does not support an interruption.

## Connect It to the Physical World

Nora's Go executor runs the experiment close to the instrument. PicoClaw adds
language, channel routing, and a web interface. The research engine studies
what the executor recorded. Application packs give those observations meaning
for a particular laboratory, machine, environment, or field.

<p align="center">
  <img src="assets/readme/evidence-loop.svg" width="100%" alt="A question becomes a local task, physical observation, evidence, investigation, and human decision">
</p>

| Part | Human-facing role |
|---|---|
| **PicoClaw** | Understand a request, find the right capability, show current evidence, and communicate through the web, chat, or Telegram. |
| **nano-os-agent** | Run the declared experiment and keep the physical loop stable when nobody is connected. |
| **Research engine** | Compare recorded series, test candidate patterns, remember rejected leads, and rank unresolved findings. |
| **Application pack** | Add field names, units, scientific questions, models, and confirmation rules for one use case. |

The same executable builds for the board, common cloud architectures, and a
development machine:

```bash
GOOS=linux GOARCH=riscv64 CGO_ENABLED=0 go build -o nora main.go  # LicheeRV Nano
GOOS=linux GOARCH=amd64   CGO_ENABLED=0 go build -o nora main.go  # x86-64 VM
GOOS=linux GOARCH=arm64   CGO_ENABLED=0 go build -o nora main.go  # ARM VM or Pi
go build -o nora main.go                                      # current machine
```

Skills that need physical devices declare that requirement. On a laptop or VM
they are skipped with an explanation; data and software experiments continue
to work.

## Your First Physical Experiment

A task states what should happen and what success means:

```yaml
- id: environmental_snapshot
  name: "Environmental snapshot"
  priority: 1
  status: pending
  steps:
    - id: read_environment
      action: call_skill
      parameters:
        skill_name: sensor_fusion_snapshot
      expect:
        status: success
      timeout: 20
      max_retries: 1
      on_fail: block
```

```bash
/root/nano-os-agent/nano-os-agent --once environmental_snapshot.yaml
tail -1 /root/nano-os-agent/experiments.jsonl
```

Add a `repeat` block to turn the reading into a bounded monitor. Add a later
step to capture an image after a sound event. Reference an earlier output with
`${step_id.field}` to keep data flow inside the experiment rather than inside
chat history.

The [guided tutorial](https://vbaulin.github.io/nora/) starts on a laptop,
moves to a board, and ends with a proactive application.

## Teach Nora a New Instrument

An unfamiliar sensor does not require permanent custom logic in the chat
prompt. It becomes a tested skill:

```text
discover device -> draft decoder -> validate output -> repeat experiment
                -> promote skill -> use in future tasks -> recheck on drift
```

For an I2C sensor, the first task can inventory the bus without writing to it.
PicoClaw can identify candidate datasheets and draft a decoder. The executor
then tests register stability, units, plausible ranges, missing-device
behavior, memory use, and repeated results. Only the version that passes those
checks becomes available for unattended work.

This creates a growing local laboratory vocabulary. A camera setup, sensor
decoder, image analysis, or model wrapper learned for one study can be reused
without repeating the integration work.

<p align="center">
  <img src="images/Nano-os-Agent.jpg" width="760" alt="Nora as a compact scientific companion beside instruments, samples, and field observations">
  <br>
  <sub>The original Nora concept: a persistent companion for instruments in the laboratory and in the field.</sub>
</p>

## Applications

| Application | What Nora can observe and investigate |
|---|---|
| [Microscope timelapse](docs/applications/microscope-timelapse.md) | Focus, illumination, object counts, morphology, growth rate, and transitions that justify denser sampling. |
| [Automatic laboratory experiments](docs/applications/automatic-lab-experiments.md) | Timed images, reaction endpoints, liquid levels, protocol checks, and comparisons with controls. |
| [Fermentation](docs/applications/wine-fermentation-monitor.md) | Temperature, audio activity, turbidity, manual density measurements, and batch-specific trajectories. |
| [Machine health](docs/applications/machine-health-monitor.md) | Status lights, gauges, audio or vibration drift, operating conditions, and machine-specific baselines. |
| [Environmental sentinel](docs/applications/environmental-event-sentinel.md) | Weather, sound, camera confirmation, missing observations, and changing local baselines. |
| [Dataset builder](docs/applications/automatic-dataset-builder.md) | Hard negatives, uncertain samples, confirmed labels, and model or skill evaluation. |
| [Robot manipulation](docs/applications/robot-manipulation.md) | Action verification, bounded retries, visual feedback, and local reflexes. |
| [Vineyard and plant research](docs/applications/vineyard-plant-research.md) | Disease conditions, phenology, weather, fruit development, field operations, and grower feedback. |

The [application atlas](docs/applications) contains more worked patterns.

## A Reference Deployment: Vineyard Guard

Vineyard Guard shows the full system working across a growing season. Each
field has its own identity, weather history, disease models, plots, operations,
and confirmed observations. The board refreshes its evidence daily, sends one
concise summary, attaches disease-specific plots when attention is needed, and
asks the grower for information the models cannot observe.

The same local records also support broader research questions: how nighttime
humidity relates to disease signals, whether weather patterns precede changes
in fruit measurements, which alerts agree with inspection, and when a missing
measurement prevents a useful conclusion. Nearby boards can exchange selected
model information while their raw field history remains under local control.

Vineyard Guard is an application, not Nora's definition. The disease-model
source and deployment data can remain in a separate repository while the
executor, research engine, and reusable hardware skills remain general.

Read [the Vineyard Guard example](VINEYARD_GUARD.md) or the
[application chapter](docs/proactive-agent/08-vineyard-guard.md).

## What Nora Will Not Pretend to Know

- A model forecast is not a confirmed physical event.
- A sequence in time does not prove that one event caused the next.
- A failed or partial experiment is not rewritten as success.
- A web search result does not become an operating instruction.
- A proposed operation is not recorded as completed.
- A numerical sugar, harvest, disease, or quality estimate requires a model
  that was validated for that field and measurement process.

These are ordinary scientific distinctions expressed in software. They let an
autonomous system do more useful work without making stronger claims than its
data support.

## Documentation

| Start here | Purpose |
|---|---|
| [Interactive tutorial](https://vbaulin.github.io/nora/) | Build a first observer, add a monitor, investigate its journal, and connect a human decision. |
| [Single-page tutorial](docs/tutorial-proactive-field-companion.md) | The complete walkthrough in one Markdown document. |
| [Application atlas](docs/applications) | Concrete microscope, fermentation, machine, robotics, field, and dataset examples. |
| [Board installation](INSTALL_BOARD.md) | Build, install, and run Nora on the LicheeRV Nano. |
| [Run off-board](deploy/README.md) | Laptop, x86-64, ARM, systemd, container, and cloud deployment. |
| [Working with physical hardware](HARDWARE_BOUNDARY.md) | Why skills make device automation reproducible, and how to add a new instrument. |
| [Build an application while keeping data local](REPO_BOUNDARY.md) | Separate reusable runtime code from private measurements, identities, and credentials. |

## Repository Map

| Path | Contains |
|---|---|
| [`main.go`](main.go) | Static task executor, local actions, MCP tools, task state, and experiment journal. |
| [`program.yaml`](program.yaml) | Research goals, hypotheses, metrics, and constraints owned by the operator. |
| [`tasks/`](tasks) | Ready-to-run experiments and inactive templates. |
| [`skills/`](skills) | Instrument drivers, analyses, research, validation, and application adapters. |
| [`pico/`](pico) | PicoClaw launcher and web integration. |
| [`docs/`](docs) | Tutorials, applications, and deployment guides. |
| [`scripts/`](scripts) | Provisioning, board synchronization, scheduling, and maintenance. |

## Current Limits

The reference board has 256 MB RAM, with part of that memory reserved for the
camera and NPU. Skills therefore use bounded processes and compact local
journals. Hardware support depends on the board image and connected devices.
Application-specific models still require application-specific validation and
labelled outcomes. Nora provides the experimental machinery; it does not make
every attached model scientifically valid.

The README visual system follows
[beautify-github-readme](https://github.com/oil-oil/beautify-github-readme).
The chapter structure of the tutorial follows the relationship-first method of
[PocketFlow Tutorial Codebase Knowledge](https://github.com/The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge),
with every runtime claim checked against this repository.
