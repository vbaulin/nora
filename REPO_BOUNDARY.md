# Repository Boundary: nano-os-agent, PicoClaw, and Goidanich

This repository can be published as the open `nano-os-agent` runtime only if
private Vineyard Guard deployment state remains outside the public tree.

## Intended Split

```text
open repository: nano-os-agent
  main.go
  task executor and --once mode
  generic hardware skills
  generic task templates
  PicoClaw integration patches and runbooks
  optional app integration contracts

private repository: goidanich
  disease model implementation
  field YAML with real GPS/field identities
  forecast/cache/database state
  Supabase synchronization implementation and credentials
  farmer feedback/product catalog when deployment-specific
  treatment history and generated reports/plots
```

PicoClaw is the gateway and UI layer. It can remain as an upstream patch set in
this repository unless a maintained PicoClaw fork is created.

## Runtime Mount Contract

The board runtime stays compatible with this split:

```text
/root/nano-os-agent
  public runtime, hardware skills, generic tasks

/root/.picoclaw/workspace/goidanich
  private Goidanich checkout, mounted only on boards that run Vineyard Guard

/root/.picoclaw/workspace/skills
  PicoClaw discovery directory, normally bind-mounted to selected
  /root/nano-os-agent/skills entries or private app skill entries
```

Vineyard Guard must be treated as an app that activates only when the private
Goidanich checkout exists. The launcher should display it as unavailable rather
than failing when the checkout is absent.

## What May Be Public

The open nano-os-agent repository may include:

- executor code and task schema;
- generic board hardware skills: camera, I2C, GPIO, PWM, ADC, NPU, audio,
  diagnostics, system state, and local learning;
- generic `apps/` or `integrations/` stubs that define how a private app is
  mounted;
- PicoClaw patch files that do not contain secrets or private field data;
- documentation that describes placeholder paths and configuration keys.

## What Must Stay Private

Keep these out of the open repository:

- `.env`, `telegram.env`, SSH keys, Supabase keys, API tokens;
- real board IPs, passwords, Telegram chat IDs, and Supabase project refs;
- real vineyard names, field IDs, exact GPS coordinates, station mappings, and
  treatment history unless intentionally public;
- `goidanich.db`, generated reports, generated plots, cached forecasts, model
  JSON files, and product catalogs with deployment-specific records;
- Goidanich model source if it is proprietary.

## Current Transitional State

This repository still contains Vineyard Guard skills and tasks under:

```text
skills/daily_vineyard_briefing
skills/vineyard_disease_risk
skills/farmer_feedback_capture
skills/farmer_notify
skills/farmer_report_compose
skills/report_guard
skills/risk_alert_policy
skills/vineyard_guard_scheduler
skills/vineyard_model_explainer
tasks/024_vineyard_disease_daily_update.yaml
tasks/025_vineyard_federated_neighbour_refresh.yaml
tasks/026_vineyard_disease_cron_daily.yaml
tasks/027_daily_vineyard_briefing.yaml
```

Do not publish those files until they are reviewed. They are safe to keep in
the working tree for the current board because PicoClaw skill discovery and the
daily schedule expect them.

## Recommended Public Layout

When preparing the public repository, move optional app material behind an
explicit app boundary:

```text
apps/
  vineyard_guard/
    README.md
    skills/        # only generic adapters if publishable
    tasks/         # templates without private field identities
    examples/      # synthetic placeholders

skills/
  adc_read/
  agri_color_index/
  agri_env_probe/
  audio_event_detect/
  camera_init/
  capture_audio/
  capture_image/
  gpio_control/
  hardware_diagnostic/
  npu_info/
  observe_scene/
  pwm_control/
  run_yolo/
  sensor_fusion_snapshot/
  system_info/
  time_sync/
  validate_skill/
  vision_state_sync/

tasks/
  001_camera_init.yaml
  002_npu_benchmark.yaml
  003_adc_pwm_test.yaml
  004_vision_guard.yaml
  generic templates only
```

Private Vineyard Guard deployments can then mount app skills explicitly:

```sh
mount --bind /root/.picoclaw/workspace/goidanich/skills/daily_vineyard_briefing \
  /root/.picoclaw/workspace/skills/daily_vineyard_briefing
```

or keep the current compatibility mount from `/root/nano-os-agent/skills` until
the board schedule is migrated.

## Publication Checklist

Before opening the repository:

1. Run a secret scan for tokens, keys, IP addresses, board passwords, chat IDs,
   and Supabase project refs.
2. Remove private Vineyard Guard tasks or convert them to placeholder templates.
3. Remove generated data: DBs, plots, reports, model JSON, JSONL journals, and
   cached weather.
4. Verify `go test ./...` or the board-supported subset.
5. Build the RISC-V nano-os-agent binary.
6. Boot a board without Goidanich mounted and confirm:
   - nano-os-agent starts;
   - generic skills list;
   - `/nano-os-agent` shows tasks and artifacts;
   - Vineyard Guard appears unavailable rather than failing.
7. Mount private Goidanich and confirm Vineyard Guard activates.

## Goidanich Private Repository Checklist

The private Goidanich repository should keep:

- `.env.example` with variable names only;
- `.gitignore` excluding `.env`, `goidanich.db`, `results/*`, `models/*.json`,
  caches, and logs;
- `supabase_schema.sql` and migration docs if schema is part of the private app;
- `SKILL.md` describing the private app contract;
- tests using synthetic field data.

It should not depend on a copied nano-os-agent tree. It should expose skills or
scripts that the board mounts into PicoClaw/nano-os-agent at deployment time.
