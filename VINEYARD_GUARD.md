# Vineyard Guard App Runtime

Vineyard Guard is a field application built on the PicoClaw and nano-os-agent
platform modules. PicoClaw is the gateway/orchestrator binary. nano-os-agent is
the deterministic board executor. Vineyard Guard is the agricultural app
contract, skill set, scheduler policy, Telegram behavior, Supabase
synchronization route, and disease-report UI layer.

Goidanich is a separate adjacent repository. Vineyard Guard calls that checkout
for disease models, SQLite state, Open-Meteo forecast handling, Supabase sync,
and plot/report generation; it does not vendor or own Goidanich code.

## Runtime Stack

```text
farmer / Telegram / webapp
  -> PicoClaw gateway platform module
  -> nano-os-agent platform module
  -> installed apps
       -> Vineyard Guard when /root/.picoclaw/workspace/goidanich exists
       -> future apps such as AdBlock when their runtime/config exists
```

The field board must answer from current tools and local state. It must not
reuse previous chat text as evidence for disease risk, treatment history,
weather, sensor state, or forecast.

## Board Components

The validated board runtime uses:

- PicoClaw gateway version label `vineyard-guard-tool-first-20260612`.
- PicoClaw launcher version label `vineyard-guard-task-runner-20260612`.
- PicoClaw launcher served on port `18800`.
- PicoClaw launcher `/runtime` page with:
  - platform section: PicoClaw Gateway;
  - platform section: nano-os-agent;
  - apps section: Vineyard Guard when Goidanich is present;
  - extension slots for future apps.
- PicoClaw launcher `/nano-os-agent` page with:
  - nano-os-agent task inventory;
  - safe one-shot task execution through `nano-os-agent --once`;
  - recent run logs;
  - background artifacts including Vineyard Guard plots and Telegram outbox
    payloads;
  - rendered Markdown preview for reports;
  - guarded file deletion for allowed artifact directories.
- PicoClaw launcher `/task-runner` route retained as a compatibility alias.
- PicoClaw gateway health on port `18790`.
- nano-os-agent canonical skills under `/root/nano-os-agent/skills`.
- PicoClaw skill discovery through bind mounts under
  `/root/.picoclaw/workspace/skills`.
- Separate Goidanich checkout mounted at
  `/root/.picoclaw/workspace/goidanich`.
- Telegram token exported by `/etc/init.d/S97picoclaw_gateway` from
  `/root/.picoclaw/telegram.env`.

## Vineyard Skills

Required runtime skills:

```text
daily-vineyard-briefing
vineyard-disease-risk
risk-alert-policy
farmer-report-compose
farmer-notify
farmer-feedback-capture
report-guard
vineyard-guard-scheduler
vineyard-model-explainer
black-rot-risk
proactive-field-agent
research-agent
vineyard-season-climate
```

`research-agent` is platform, not app: it is the domain-neutral research engine
described in [`skills/research_agent/SKILL.md`](skills/research_agent/SKILL.md).
Vineyard Guard registers with it through
`skills/proactive_field_agent/pack.py`, which expresses the vineyard's standing
questions as parameters for the engine's generic analyses. A board without the
Goidanich checkout runs the engine with one fewer pack.

Their source directories may use underscores on disk, but each `SKILL.md`
`name:` field must be hyphenated.

## Daily Operation

Vineyard Guard runs four daily functions:

1. **Supabase/network sync**: register board/fields, pull neighbour alerts,
   pull released model versions, and push farmer feedback.
2. **Daily cache refresh**: update weather, forecasts, disease models, reports,
   and plots once per day per field/disease unless stale or feedback changed.
3. **Farmer notification**: send a concise daily summary. Attach plots for
   high-risk/full reports or when the board has only a small number of fields.
4. **Proactive field reflection**: ingest fresh model artifacts, confirmed
   operations and field-related nano-os-agent experiments; queue one bounded
   research question when evidence is insufficient; and create at most one
   confirmable proposal per field.

Low-risk messages should be short and treatment-focused. High-risk messages
must include the full disease report and plot attachments.

The production board uses the deterministic BusyBox tick, not LLM
`agent_turn` cron jobs. `/etc/crontabs/root` runs:

```text
*/5 * * * * /root/.picoclaw/workspace/scripts/vineyard_guard_tick.sh
```

The tick uses dated stamps and locks to execute Supabase sync, per-field
three-disease cache refresh, one board Telegram summary, morning proactive
reflection/research, and an evening operation-ingestion pass. Legacy
`vineyard_guard_*` jobs in
`/root/.picoclaw/workspace/cron/jobs.json` are disabled during deployment so
the LLM cannot duplicate the deterministic schedule.

The tick exports the POSIX Europe/Madrid daylight-saving rule before comparing
local schedule windows:

```text
TZ=CET-1CEST,M3.5.0,M10.5.0/3
```

## Proactive Field Learning

`proactive-field-agent` provides a small SQLite evidence memory at
`/root/.picoclaw/workspace/proactive_field/proactive_field.db`. It keeps field
profiles, current model observations, confirmed farmer operations,
field-related nano-os-agent experiments, facts, investigations, research
sources, proposals and farmer decisions as separate epistemic objects.

The skill never writes a treatment. A high-priority proposal is packaged
through the existing `farmer-notify` outbox and includes `Ref: PF-<id>`. An
explicit farmer acceptance, rejection, deferral or correction is stored with
`mode=record_decision`; product/application details still pass through the
two-step feedback workflow below. See
[`docs/waku-agent-proactive-field-integration.md`](docs/waku-agent-proactive-field-integration.md).

## Proactive Investigation

A detected pattern is investigated before the farmer is contacted. Each tick
runs the bounded analyses in `skills/proactive_field_agent/investigations.py`
over evidence the board already holds:

| Topic | Reads | Question |
| --- | --- | --- |
| `leaf_wetness_proxy` | `black_rot_daily_predictions` | Does the unmeasured-wetness assumption change any decision here? |
| `peer_signal_divergence` | `peer_signals`, `topology` | Do nearby boards report what this field's model does not? |
| `alert_calibration` | local proposals and confirmed outcomes | Do this board's alerts match what the farmer finds? |

Each finding stores its question, method, window, sample size, verdict,
confidence, limitations and ranked options. Only a `material_unresolved`
verdict is sent; `not_material`, `resolved_local` and `insufficient_data` stay
in evidence memory, and `not_material` is sent once as a closure only when the
farmer was already asked about that topic.

Farmer-facing findings report their numbers and order the ways to close them by
cost. A free field observation comes first and hardware last: a sensor may be
offered only alongside cheaper options, once per field per season, and never
again after a refusal. A rejected proposal closes its subject for the season.
An external search is queued only for what the local analysis could not settle,
and it asks the scientific question rather than a product question.

Run the analyses without contacting anyone:

```bash
printf '%s' '{"mode":"investigate"}' | /root/nano-os-agent/skills/proactive_field_agent/run.sh
```

## Farmer Feedback

Farmer feedback is a two-step structured workflow:

1. Parse the farmer message with `farmer-feedback-capture confirmed=false`.
2. Ask for confirmation/correction in the farmer's language.
3. Write only after explicit confirmation with
   `farmer-feedback-capture confirmed=true`.

Treatment records must preserve:

- all products;
- product registration/code;
- lot;
- dose;
- water volume;
- treated area;
- method;
- date;
- target disease or reason;
- normalized per-hectare quantities when area is known.

Confirmed writes update local state and push to Supabase when configured.

## Product Catalog

Product advice is not a generic risk report. If the farmer asks what to apply
or mentions a product, Vineyard Guard must check the product catalog first,
present the matched product/code, and ask for confirmation before writing an
application event.

The product catalog should exist locally for offline matching and sync with
Supabase when new confirmed products are introduced.

## Board And Parcel Metadata

Board identity must not be inherited by cloning another card. Each physical
board and logical field receives a stable, unique UUID derived from its own
`board.id` or `field.id`. The Vineyard Guard SD-card provisioner writes these
identities and the field context consumed by local models and Supabase
registration.

Required field context:

- unique field id and display name;
- GPS coordinate;
- variety;
- planting year or vine age.

Recommended context:

- management regime and irrigation/water regime;
- weather station and municipality identifiers;
- training system and row orientation;
- phenology dates;
- black-rot inoculum history and evidence source;
- measured leaf-wetness sensor presence/channel;
- SIGPAC recinto reference and returned attributes.

SIGPAC is parcel context, not weather data. The provisioner queries the
official MAPA/FEGA `AU.Sigpac:recinto` WMS layer and stores the returned use,
surface, slope, irrigation coefficient, region, and altitude with source
provenance. It does not use SIGPAC to choose a meteorological station. A GPS
query may return adjacent recintos; unresolved matches must be reviewed rather
than selected silently.

Run the provisioner against a mounted SD-card rootfs:

```bash
python3 scripts/provision_vineyard_sd.py \
  --manifest /path/to/board.json \
  --rootfs /Volumes/rootfs \
  --fetch-sigpac \
  --require-sigpac
```

See [Vineyard board and SD-card provisioning](docs/vineyard-sd-card-provisioning.md).

## Hardware And Farm Health

Farm-health hardware must go through nano-os-agent, not direct PicoClaw shell
commands. The intended route is:

```text
PicoClaw intent
  -> nano-os-agent MCP tool or task
  -> skill/native handler
  -> sensor/camera/NPU/I2C/GPIO
  -> JSON evidence and journal
```

If a new sensor is attached, Vineyard Guard should:

1. request nano-os-agent hardware inventory;
2. match known buses/devices to existing skills;
3. create a safe read-only probe task for unknown candidates;
4. validate repeated observations;
5. promote a driver skill only after evidence is stable;
6. expose the new capability in the webapp and daily health state.

See `docs/picoclaw-nano-webapp-integration.md`.

For chat and Telegram, the same evidence rule applies. Board, vineyard,
weather, forecast, treatment, plot, sensor, camera, scheduler, and
nano-os-agent questions must inspect current skills/tools, nano tasks, or
current local state in the same turn. Session memory is not evidence. If no
current tool/skill evidence was collected, the gateway must not answer with
risk values, hardware status, or treatment advice.

## Rebuild And Deploy

The PicoClaw fork/variant is not stored as an opaque board binary in git. It is
stored as:

- a source patch: `patches/sipeed-picoclaw-structured-telegram.patch`;
- a launcher runtime UI patch:
  `patches/sipeed-picoclaw-runtime-dashboard.patch`;
- a tool-first gateway and Task Runner patch:
  `patches/sipeed-picoclaw-task-runner-tool-first.patch`;
- a deployment runbook: `docs/picoclaw-gateway-board-sync.md`;
- Vineyard Guard runtime docs and skill sources in this repo.

The compiled RISC-V gateway is deployed to:
```text
/opt/picoclaw/picoclaw
```

Current deployed gateway checksum:

```text
3517901aa586826a86db04ad6ca0c9c5c50e8428b986eaa50bb152bc211a7410
```

Current deployed launcher checksum:

```text
97a9f756b8d384ce0ab4dc464f6d966b79a8a781cd7916c5b95c4f71f72ad1c6
```

Current deployed nano-os-agent checksum:

```text
c7ddc09b6d0e4dd7636a0726718b4a9ea4e37358cfea8e6e7ff06e3ed10a8415
```

## Verification

Board health is valid when:

```text
/ready returns ready
launcher /api/models returns configured models after login
launcher /api/runtime/status returns platform and apps state after login
launcher /api/task-runner/status returns nano tasks, artifacts, and enabled jobs
launcher /runtime serves the Board Runtime UI
launcher /nano-os-agent serves the nano Task Runner UI
launcher /task-runner remains a compatibility alias
gateway status is running
channels include pico and telegram
vineyard skills are listed
nano-os-agent skills directory exists
```

The currently verified board satisfies these checks.
