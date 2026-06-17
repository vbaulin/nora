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
```

Their source directories may use underscores on disk, but each `SKILL.md`
`name:` field must be hyphenated.

## Daily Operation

Vineyard Guard runs three daily functions:

1. **Supabase/network sync**: register board/fields, pull neighbour alerts,
   pull released model versions, and push farmer feedback.
2. **Daily cache refresh**: update weather, forecasts, disease models, reports,
   and plots once per day per field/disease unless stale or feedback changed.
3. **Farmer notification**: send a concise daily summary. Attach plots for
   high-risk/full reports or when the board has only a small number of fields.

Low-risk messages should be short and treatment-focused. High-risk messages
must include the full disease report and plot attachments.

The scheduled jobs must remain enabled in
`/root/.picoclaw/workspace/cron/jobs.json`:

```text
vineyard_guard_supabase_sync              55 7 * * *
vineyard_guard_supabase_sync_powdery      56 7 * * *
vineyard_guard_daily_cache_refresh         0 8 * * *
vineyard_guard_risk_only_telegram_alert    5 8 * * *
```

For multi-field boards, do not run the daily cache refresh as one all-field
Telegram/gateway call. Use one `daily-vineyard-briefing` refresh job per field
and schedule the Telegram summary after those jobs with `cache_only=true`.
La Granada uses:

```text
vineyard_guard_daily_cache_refresh_<field>   0/8/16/24/32 8 * * *
vineyard_guard_risk_only_telegram_alert      45 8 * * *  cache_only=true
```

The gateway init script must export `TZ=Europe/Madrid` so the morning schedule
is interpreted in the field timezone.

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
