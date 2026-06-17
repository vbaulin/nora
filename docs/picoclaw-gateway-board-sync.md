# PicoClaw Gateway Board Sync

This runbook records how the PicoClaw launcher, PicoClaw gateway, and
nano-os-agent skills are rebuilt and installed on the LicheeRV Nano board.

The central rule is that the web launcher and gateway must be built from a
compatible PicoClaw source tree. Updating only one side can make the webapp
show `500 no models configured`, make the gateway reject `config.json`, or
break `/api/pico/info` and `/ready`.

## Verified Board State

Current validated board:

```text
board: 192.168.36.102
launcher: /opt/picoclaw/picoclaw-launcher
gateway: /opt/picoclaw/picoclaw
gateway version label: vineyard-guard-tool-first-20260612
launcher version label: vineyard-guard-task-runner-20260612
launcher runtime UI: /runtime
launcher nano-os-agent UI: /nano-os-agent
launcher task compatibility route: /task-runner
nano one-shot executor: /root/nano-os-agent/nano-os-agent --once <task.yaml>
gateway checksum: 3517901aa586826a86db04ad6ca0c9c5c50e8428b986eaa50bb152bc211a7410
launcher checksum: 97a9f756b8d384ce0ab4dc464f6d966b79a8a781cd7916c5b95c4f71f72ad1c6
nano-os-agent checksum: c7ddc09b6d0e4dd7636a0726718b4a9ea4e37358cfea8e6e7ff06e3ed10a8415
dashboard password: rootroot
gateway init timezone: TZ=Europe/Madrid
```

Expected runtime checks:

```sh
wget -qO- http://127.0.0.1:18790/ready
tail -80 /tmp/picoclaw_gateway.log | grep "Channels enabled" | tail -1
```

Expected result:

```text
{"status":"ready", ...}
✓ Channels enabled: [pico telegram]
```

The currently verified Vineyard Guard jobs are enabled and scheduled in Madrid
local time:

```text
vineyard_guard_supabase_sync              55 7 * * *
vineyard_guard_supabase_sync_powdery      56 7 * * *
vineyard_guard_daily_cache_refresh         0 8 * * *
vineyard_guard_risk_only_telegram_alert    5 8 * * *
```

On boards with more than two vineyard fields, the all-field cache refresh must
be split into single-field jobs. The Telegram summary should run after those
jobs and pass `cache_only=true`, so farmer chat does not regenerate plots and
cannot time out.

## Source Of Truth

- Repo skills live in `skills/` for versioning and review.
- Board canonical runtime skills live in `/root/nano-os-agent/skills/`.
- PicoClaw discovers skills under `/root/.picoclaw/workspace/skills/`.
- Do not maintain independent copied skills on the board. Use bind mounts from
  `/root/nano-os-agent/skills/<skill>` to
  `/root/.picoclaw/workspace/skills/<skill>`.

The board init script is:

```sh
/etc/init.d/S30picoclaw_skill_mounts
```

It must run before the PicoClaw gateway. It bind-mounts the vineyard and
farmer-facing skills, including:

```text
daily_vineyard_briefing
vineyard_disease_risk
risk_alert_policy
farmer_report_compose
farmer_notify
farmer_feedback_capture
report_guard
vineyard_guard_scheduler
vineyard_model_explainer
```

Use underscore directory names on disk when the nano-os-agent skill directory
already uses them. Inside each `SKILL.md`, `name:` must be hyphenated, for
example `daily-vineyard-briefing`.

## Vineyard Guard PicoClaw Patch

The local source patch for the Vineyard Guard PicoClaw gateway runtime is:

```text
patches/sipeed-picoclaw-structured-telegram.patch
```

It is intentionally small. Its purpose is to make Telegram and Pico channel
turns tool-first for board/vineyard requests:

1. Force vineyard requests through the appropriate skill instead of session
   memory.
2. Preserve structured delivery envelopes from skills.
3. Prevent raw JSON dumps to Telegram.
4. Preserve photo/media attachments.
5. Keep `/ready` accurate after gateway startup.

Do not replace this with broad application rewrites for the field board. The
SG2002 board has limited RAM and should run stripped, static RISC-V binaries.

The local source patch for the launcher runtime page is:

```text
patches/sipeed-picoclaw-runtime-dashboard.patch
```

It adds:

- authenticated `GET /api/runtime/status`;
- compatibility `GET /api/vineyard-guard/status`;
- `/runtime` webapp route;
- platform cards for PicoClaw Gateway and nano-os-agent;
- an Apps section where Vineyard Guard is active only when the private
  Goidanich checkout exists;
- extension slots for future apps such as AdBlock.

The local source patch for the tool-first gateway and Task Runner UI is:

```text
patches/sipeed-picoclaw-task-runner-tool-first.patch
```

It adds:

- stricter board evidence requirements for chat and Telegram;
- a finalization guard that refuses board/vineyard/hardware answers when no
  current tool/skill evidence was collected in the turn;
- treatment-advice routing that checks current Vineyard Guard state without
  sending full reports unless requested;
- authenticated `GET /api/task-runner/status`;
- authenticated `POST /api/task-runner/tasks/run`;
- authenticated artifact serving and deletion for allowed task/result
  directories;
- `/nano-os-agent` webapp route with nano task inventory, safe one-shot run
  controls, recent run logs, rendered Markdown previews, file deletion, and
  daily/background artifacts;
- `/task-runner` compatibility route for existing links.

## Rebuild From Upstream

Use a throwaway upstream checkout:

```sh
WORK=/private/tmp/sipeed-picoclaw-rebuild
rm -rf "$WORK"
git clone https://github.com/sipeed/picoclaw "$WORK"
cd "$WORK"
git apply /Users/vbaulin/antigr/picoClaw/patches/sipeed-picoclaw-structured-telegram.patch
git apply /Users/vbaulin/antigr/picoClaw/patches/sipeed-picoclaw-runtime-dashboard.patch
git apply /Users/vbaulin/antigr/picoClaw/patches/sipeed-picoclaw-task-runner-tool-first.patch
```

If the local Go runtime is slightly older than upstream `go.mod`, adjust only
the throwaway clone. Do not commit this compatibility edit:

```sh
perl -0pi -e 's/^go 1\.25\.11$/go 1.25.10/m' go.mod
```

Build the launcher frontend/backend:

```sh
cd "$WORK/web/frontend"
PATH=/Users/vbaulin/.nvm/versions/node/v22.12.0/bin:$PATH pnpm install --frozen-lockfile
PATH=/Users/vbaulin/.nvm/versions/node/v22.12.0/bin:$PATH pnpm build:backend

cd "$WORK"
GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=riscv64 \
  go build -v -tags goolm,stdjson -ldflags "-s -w" \
  -o /private/tmp/picoclaw-launcher-riscv64 ./web/backend
```

Build the gateway:

```sh
cd "$WORK"
go run scripts/copydir.go workspace cmd/picoclaw/internal/onboard/workspace
GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=riscv64 \
  go build -v -tags goolm,stdjson -ldflags "-s -w" \
  -o /private/tmp/picoclaw-gateway-riscv64 ./cmd/picoclaw
```

Build nano-os-agent from this repository when the web Task Runner is required:

```sh
cd /Users/vbaulin/antigr/picoClaw
GOCACHE=/private/tmp/go-build-cache GOMODCACHE=/private/tmp/go-mod-cache \
  CGO_ENABLED=0 GOOS=linux GOARCH=riscv64 GOTOOLCHAIN=auto \
  go build -v -ldflags "-s -w" \
  -o /private/tmp/nano-os-agent-riscv64 ./main.go
```

## Deploy To Board

The current deployment key is:

```text
/private/tmp/picoclaw_board_ed25519
```

Install the launcher:

```sh
scp -i /private/tmp/picoclaw_board_ed25519 \
  /private/tmp/picoclaw-launcher-riscv64 \
  root@192.168.36.102:/tmp/picoclaw-launcher-riscv64

ssh -i /private/tmp/picoclaw_board_ed25519 root@192.168.36.102 '
set -e
TS=$(date +%Y%m%d_%H%M%S)
/etc/init.d/S98picoclaw_launcher stop 2>/dev/null || true
cp /opt/picoclaw/picoclaw-launcher /opt/picoclaw/picoclaw-launcher.bak.$TS
cp /tmp/picoclaw-launcher-riscv64 /opt/picoclaw/picoclaw-launcher
chmod +x /opt/picoclaw/picoclaw-launcher
/etc/init.d/S98picoclaw_launcher start
'
```

Install the gateway:

```sh
scp -i /private/tmp/picoclaw_board_ed25519 \
  /private/tmp/picoclaw-gateway-riscv64 \
  root@192.168.36.102:/tmp/picoclaw-gateway-riscv64

ssh -i /private/tmp/picoclaw_board_ed25519 root@192.168.36.102 '
set -e
TS=$(date +%Y%m%d_%H%M%S)
/etc/init.d/S97picoclaw_gateway stop 2>/dev/null || true
cp /opt/picoclaw/picoclaw /opt/picoclaw/picoclaw.bak.$TS
cp /tmp/picoclaw-gateway-riscv64 /opt/picoclaw/picoclaw
chmod +x /opt/picoclaw/picoclaw
/etc/init.d/S30picoclaw_skill_mounts restart 2>/dev/null || true
/etc/init.d/S97picoclaw_gateway start
'
```

Install nano-os-agent together with the matching gateway and launcher when
using `/task-runner`:

```sh
scp -i /private/tmp/picoclaw_board_ed25519 \
  /private/tmp/nano-os-agent-riscv64 \
  root@192.168.36.102:/tmp/nano-os-agent-riscv64

ssh -i /private/tmp/picoclaw_board_ed25519 root@192.168.36.102 '
set -e
TS=$(date +%Y%m%d_%H%M%S)
cp /root/nano-os-agent/nano-os-agent /root/nano-os-agent/nano-os-agent.bak.$TS 2>/dev/null || true
cp /tmp/nano-os-agent-riscv64 /root/nano-os-agent/nano-os-agent
chmod +x /root/nano-os-agent/nano-os-agent
'
```

Current deployed checksums:

```text
/root/nano-os-agent/nano-os-agent  c7ddc09b6d0e4dd7636a0726718b4a9ea4e37358cfea8e6e7ff06e3ed10a8415
/opt/picoclaw/picoclaw           3517901aa586826a86db04ad6ca0c9c5c50e8428b986eaa50bb152bc211a7410
/opt/picoclaw/picoclaw-launcher  97a9f756b8d384ce0ab4dc464f6d966b79a8a781cd7916c5b95c4f71f72ad1c6
```

## Telegram Credential Compatibility

Current PicoClaw reads the Telegram token from
`PICOCLAW_CHANNELS_TELEGRAM_TOKEN` or
`channel_list.telegram.settings.token`. Older board images store:

```text
/root/.picoclaw/telegram.env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

The board init script `/etc/init.d/S97picoclaw_gateway` must source
`telegram.env` and export the new variable:

```sh
if [ -f /root/.picoclaw/telegram.env ]; then
    . /root/.picoclaw/telegram.env
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -z "$PICOCLAW_CHANNELS_TELEGRAM_TOKEN" ]; then
        export PICOCLAW_CHANNELS_TELEGRAM_TOKEN="$TELEGRAM_BOT_TOKEN"
    fi
fi
```

Without this compatibility export, gateway restarts can silently start only the
Pico channel, while Telegram appears configured in `config.json`.

## Authenticated Webapp Checks

After the launcher password is set, protected APIs return `401` until a
session cookie is obtained. Use this check on the board:

```sh
python3 - <<'PY'
import json, urllib.request, http.cookiejar
base = "http://127.0.0.1:18800"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(
    base + "/api/auth/login",
    data=json.dumps({"password": "rootroot"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print("login", opener.open(login, timeout=5).status)
for path in [
    "/api/gateway/status",
    "/api/models",
    "/api/pico/info",
    "/api/system/version",
    "/api/task-runner/status",
]:
    data = opener.open(base + path, timeout=5).read()
    print(path, "OK", len(data))
PY
```

Expected:

```text
login 200
/api/gateway/status OK ...
/api/models OK ...
/api/pico/info OK ...
/api/system/version OK ...
/api/task-runner/status OK ...
```

Check the board runtime page/API:

```sh
python3 - <<'PY'
import json, urllib.request, http.cookiejar
base = "http://127.0.0.1:18800"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(
    base + "/api/auth/login",
    data=json.dumps({"password": "rootroot"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
opener.open(login, timeout=5).read()
data = json.load(opener.open(base + "/api/runtime/status", timeout=10))
print(sorted(data["platform"].keys()))
print(sorted(data["apps"].keys()))
print(data["platform"]["picoclaw_gateway"]["telegram"]["active"])
print(data["apps"]["vineyard_guard"]["app"]["available"])
PY
```

Expected:

```text
['nano_os_agent', 'picoclaw_gateway']
['available_slots', 'vineyard_guard']
True
True
```

Check the Task Runner page/API:

```sh
python3 - <<'PY'
import json, urllib.request, http.cookiejar
base = "http://127.0.0.1:18800"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(
    base + "/api/auth/login",
    data=json.dumps({"password": "rootroot"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
opener.open(login, timeout=5).read()
data = json.load(opener.open(base + "/api/task-runner/status", timeout=10))
print(data["executor"]["runnable"])
print(data["tasks"]["count"])
print(data["artifacts"]["count"])
print(data["background_operations"]["enabled"])
PY
```

Expected on the validated board:

```text
True
22
40
3
```

The canonical browser route is:

```text
http://192.168.36.102:18800/nano-os-agent
```

The page should render `.md` artifacts in the preview panel. The `Raw` button is
only for opening the original file representation.

Verified UI screenshot:

![nano-os-agent Task Runner Markdown preview](assets/picoclaw-nano-agent-md-preview.png)

## Config Compatibility

This gateway build rejects unknown config fields. If startup fails with unknown
fields, remove only unsupported keys from `/root/.picoclaw/config.json` after a
timestamped backup.

Known fields removed during recovery:

```text
channels
session.dm_scope
tools.web.kagi
```

If startup fails with `model identifier must not contain //`, the model entry
has a URL in the `model` field. Move the URL to `api_base` and keep `model` as
a model identifier.

## Vineyard Telegram Rule

For risk/report/plot/forecast/mildew requests:

- use `daily-vineyard-briefing`;
- use fresh cached `dashboard_state`, `dashboard_report`, and PNG files when
  they are current for today;
- regenerate once only when cache files or model layers are stale/missing;
- send both disease plots for generic high-risk or requested full reports;
- send one concise daily summary when risk is low;
- never paste raw JSON to Telegram;
- do not use session memory as a risk source.

For farmer feedback or treatment:

- call `farmer-feedback-capture` with `confirmed=false`;
- ask the farmer to confirm/correct the structured draft in the same language;
- only after explicit confirmation call it again with `confirmed=true`;
- the confirmed write updates local DB/dashboard and pushes pending events to
  Supabase when Supabase config is present.

## Hardware Discovery Boundary

PicoClaw must not probe hardware directly from shell during normal operation.
All camera, TPU/NPU, audio, GPIO, PWM, ADC, and I2C actions must go through
nano-os-agent MCP tools, task YAML, or skills. See
`docs/picoclaw-nano-webapp-integration.md` for the webapp integration plan and
automatic hardware-discovery contract.
