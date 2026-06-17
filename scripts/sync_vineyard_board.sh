#!/usr/bin/env sh
set -eu

BOARD="${BOARD:-root@192.168.36.151}"
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
GOIDANICH_ROOT="${GOIDANICH_ROOT:-$ROOT_DIR/../goidanich}"

VINEYARD_SKILLS="
daily_vineyard_briefing
vineyard_disease_risk
risk_alert_policy
farmer_report_compose
farmer_notify
farmer_feedback_capture
report_guard
vineyard_guard_scheduler
vineyard_model_explainer
"

echo "syncing contracts to $BOARD"
scp "$ROOT_DIR/AGENT.md" "$BOARD:/root/.picoclaw/workspace/AGENT.md"
scp "$ROOT_DIR/AGENTS.md" "$BOARD:/root/.picoclaw/workspace/AGENTS.md"
scp "$ROOT_DIR/USER.md" "$BOARD:/root/.picoclaw/workspace/USER.md"
scp "$ROOT_DIR/SOUL.md" "$BOARD:/root/.picoclaw/workspace/SOUL.md"
scp "$ROOT_DIR/PICOCLAW_ORCHESTRATOR_PROMPT.md" "$BOARD:/root/.picoclaw/workspace/PICOCLAW_ORCHESTRATOR_PROMPT.md"

echo "syncing PicoClaw app runtime"
scp "$ROOT_DIR/pico/app.yaml" "$BOARD:/tmp/app_picoclaw_app.yaml"
scp "$ROOT_DIR/pico/config.py" "$BOARD:/tmp/app_picoclaw_config.py"
scp "$ROOT_DIR/pico/main.py" "$BOARD:/tmp/app_picoclaw_main.py"
scp "$ROOT_DIR/pico/picoclaw.py" "$BOARD:/tmp/app_picoclaw_picoclaw.py"
scp "$ROOT_DIR/pico/ui.py" "$BOARD:/tmp/app_picoclaw_ui.py"

echo "syncing authoritative nano-os-agent skills"
for skill in $VINEYARD_SKILLS; do
  if [ -d "$ROOT_DIR/skills/$skill" ]; then
    scp -r "$ROOT_DIR/skills/$skill" "$BOARD:/root/nano-os-agent/skills/"
  fi
done

echo "syncing deterministic Vineyard Guard scheduler scripts"
scp "$ROOT_DIR/scripts/vineyard_guard_cron.py" "$BOARD:/tmp/vineyard_guard_cron.py"
scp "$ROOT_DIR/scripts/vineyard_guard_tick.sh" "$BOARD:/tmp/vineyard_guard_tick.sh"
scp "$ROOT_DIR/scripts/telegram_outbox_sender.py" "$BOARD:/tmp/telegram_outbox_sender.py"
scp "$ROOT_DIR/scripts/S32vineyard_guard_crond" "$BOARD:/tmp/S32vineyard_guard_crond"

if [ -d "$GOIDANICH_ROOT" ]; then
  echo "syncing board-safe Goidanich runtime from $GOIDANICH_ROOT"
  ssh "$BOARD" 'rm -rf /tmp/goidanich_sync && mkdir -p /tmp/goidanich_sync'
  for module in \
    board_fill_gaps.py \
    board_predict.py \
    board_rossi.py \
    board_update_dashboard.py \
    daily_update.py \
    disease_tasks.py \
    disease_tasks.yaml \
    field_config.py \
    forecast_projection.py \
    goidanich_agent.py \
    personalized_model.py \
    personalized_predict.py \
    powdery_mildew.py \
    product_catalog.py \
    record_feedback.py \
    rossi.py \
    season_gate.py \
    stations.py \
    supabase_sync.py
    train_personalized_model.py
  do
    if [ -f "$GOIDANICH_ROOT/$module" ]; then
      scp "$GOIDANICH_ROOT/$module" "$BOARD:/tmp/goidanich_sync/$module"
    fi
  done
fi

echo "repairing board skill discovery without duplicate skill copies"
ssh "$BOARD" 'sh -s' <<'SH'
set -eu

mkdir -p /root/.picoclaw/workspace/skills
mkdir -p /root/.picoclaw/workspace/pico
mkdir -p /root/.picoclaw

cp /root/.picoclaw/workspace/AGENT.md /root/.picoclaw/AGENT.md
cp /root/.picoclaw/workspace/AGENTS.md /root/.picoclaw/AGENTS.md
cp /root/.picoclaw/workspace/USER.md /root/.picoclaw/USER.md
cp /root/.picoclaw/workspace/SOUL.md /root/.picoclaw/SOUL.md
cp /root/.picoclaw/workspace/PICOCLAW_ORCHESTRATOR_PROMPT.md /root/.picoclaw/PICOCLAW_ORCHESTRATOR_PROMPT.md

cp /tmp/app_picoclaw_app.yaml /root/.picoclaw/workspace/pico/app.yaml
cp /tmp/app_picoclaw_config.py /root/.picoclaw/workspace/pico/config.py
cp /tmp/app_picoclaw_main.py /root/.picoclaw/workspace/pico/main.py
cp /tmp/app_picoclaw_picoclaw.py /root/.picoclaw/workspace/pico/picoclaw.py
cp /tmp/app_picoclaw_ui.py /root/.picoclaw/workspace/pico/ui.py

for app_dir in /opt/app_picoclaw /root/app_picoclaw /root/.picoclaw/app_picoclaw; do
  if [ -d "$app_dir" ] || [ -f "$app_dir/picoclaw.py" ] || [ "$app_dir" = "/opt/app_picoclaw" ]; then
    mkdir -p "$app_dir"
    cp /tmp/app_picoclaw_app.yaml "$app_dir/app.yaml"
    cp /tmp/app_picoclaw_config.py "$app_dir/config.py"
    cp /tmp/app_picoclaw_main.py "$app_dir/main.py"
    cp /tmp/app_picoclaw_picoclaw.py "$app_dir/picoclaw.py"
    cp /tmp/app_picoclaw_ui.py "$app_dir/ui.py"
  fi
done

for skill in \
  daily_vineyard_briefing \
  vineyard_disease_risk \
  risk_alert_policy \
  farmer_report_compose \
  farmer_notify \
  farmer_feedback_capture \
  report_guard \
  vineyard_guard_scheduler \
  vineyard_model_explainer
do
  umount "/root/.picoclaw/workspace/skills/$skill" 2>/dev/null || true
  rm -rf "/root/.picoclaw/workspace/skills/$skill"
  mkdir -p "/root/.picoclaw/workspace/skills/$skill"
  mount --bind "/root/nano-os-agent/skills/$skill" "/root/.picoclaw/workspace/skills/$skill"
done

for pair in \
  daily-vineyard-briefing:daily_vineyard_briefing \
  vineyard-disease-risk:vineyard_disease_risk \
  risk-alert-policy:risk_alert_policy \
  farmer-report-compose:farmer_report_compose \
  farmer-notify:farmer_notify \
  farmer-feedback-capture:farmer_feedback_capture \
  report-guard:report_guard \
  vineyard-guard-scheduler:vineyard_guard_scheduler \
  vineyard-model-explainer:vineyard_model_explainer
do
  hyphen_name=${pair%%:*}
  underscore_name=${pair#*:}
  target="/root/nano-os-agent/skills/$underscore_name"
  link="/root/.picoclaw/workspace/skills/$hyphen_name"
  if [ -d "$target" ]; then
    if [ -e "$link" ] && [ ! -L "$link" ]; then
      rm -rf "$link"
    fi
    ln -sfn "$target" "$link"
  fi
done

# These were copied into PicoClaw workspace as ordinary workspace skills, but
# they are not valid PicoClaw skill packages there. Remove the duplicate copies
# instead of patching them in place.
for stale in fermentation_monitor wine_grape_analyzer; do
  if [ ! -L "/root/.picoclaw/workspace/skills/$stale" ]; then
    rm -rf "/root/.picoclaw/workspace/skills/$stale"
  fi
done

find /root/nano-os-agent/skills -name run.sh -exec chmod +x {} \;
find /root/nano-os-agent/skills -name run.py -exec chmod +x {} \;

mkdir -p /root/.picoclaw/workspace/scripts /etc/crontabs
cp /tmp/vineyard_guard_cron.py /root/.picoclaw/workspace/scripts/vineyard_guard_cron.py
cp /tmp/vineyard_guard_tick.sh /root/.picoclaw/workspace/scripts/vineyard_guard_tick.sh
cp /tmp/telegram_outbox_sender.py /root/.picoclaw/workspace/scripts/telegram_outbox_sender.py
cp /tmp/S32vineyard_guard_crond /etc/init.d/S32vineyard_guard_crond
chmod +x \
  /root/.picoclaw/workspace/scripts/vineyard_guard_cron.py \
  /root/.picoclaw/workspace/scripts/vineyard_guard_tick.sh \
  /root/.picoclaw/workspace/scripts/telegram_outbox_sender.py \
  /etc/init.d/S32vineyard_guard_crond

if [ -d /tmp/goidanich_sync ]; then
  mkdir -p /root/.picoclaw/workspace/goidanich
  for module in /tmp/goidanich_sync/*; do
    [ -f "$module" ] || continue
    cp "$module" "/root/.picoclaw/workspace/goidanich/$(basename "$module")"
  done
fi
touch /etc/crontabs/root
grep -v vineyard_guard_tick.sh /etc/crontabs/root > /tmp/root.cron.new || true
echo "*/5 * * * * /root/.picoclaw/workspace/scripts/vineyard_guard_tick.sh" >> /tmp/root.cron.new
cp /tmp/root.cron.new /etc/crontabs/root

cat > /etc/init.d/S30picoclaw_skill_mounts <<'MOUNTSH'
#!/bin/sh

case "$1" in
  start)
    mkdir -p /root/.picoclaw/workspace/skills
    for skill in \
      daily_vineyard_briefing \
      vineyard_disease_risk \
      risk_alert_policy \
      farmer_report_compose \
      farmer_notify \
      farmer_feedback_capture \
      report_guard \
      vineyard_guard_scheduler \
      vineyard_model_explainer
    do
      if [ -d "/root/nano-os-agent/skills/$skill" ]; then
        umount "/root/.picoclaw/workspace/skills/$skill" 2>/dev/null || true
        rm -rf "/root/.picoclaw/workspace/skills/$skill"
        mkdir -p "/root/.picoclaw/workspace/skills/$skill"
        mount --bind "/root/nano-os-agent/skills/$skill" "/root/.picoclaw/workspace/skills/$skill"
      fi
    done
    for pair in \
      daily-vineyard-briefing:daily_vineyard_briefing \
      vineyard-disease-risk:vineyard_disease_risk \
      risk-alert-policy:risk_alert_policy \
      farmer-report-compose:farmer_report_compose \
      farmer-notify:farmer_notify \
      farmer-feedback-capture:farmer_feedback_capture \
      report-guard:report_guard \
      vineyard-guard-scheduler:vineyard_guard_scheduler \
      vineyard-model-explainer:vineyard_model_explainer
    do
      hyphen_name=${pair%%:*}
      underscore_name=${pair#*:}
      target="/root/nano-os-agent/skills/$underscore_name"
      link="/root/.picoclaw/workspace/skills/$hyphen_name"
      if [ -d "$target" ]; then
        if [ -e "$link" ] && [ ! -L "$link" ]; then
          rm -rf "$link"
        fi
        ln -sfn "$target" "$link"
      fi
    done
    ;;
  stop)
    for skill in \
      daily_vineyard_briefing \
      vineyard_disease_risk \
      risk_alert_policy \
      farmer_report_compose \
      farmer_notify \
      farmer_feedback_capture \
      report_guard \
      vineyard_guard_scheduler \
      vineyard_model_explainer
    do
      umount "/root/.picoclaw/workspace/skills/$skill" 2>/dev/null || true
    done
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  *)
    echo "Usage: $0 {start|stop|restart}"
    exit 1
    ;;
esac

exit 0
MOUNTSH
chmod +x /etc/init.d/S30picoclaw_skill_mounts
/etc/init.d/S32vineyard_guard_crond restart || true

if [ -f /root/.picoclaw/workspace/cron/jobs.json ]; then
  python3 - <<'PY'
import time
import json
from pathlib import Path
p = Path("/root/.picoclaw/workspace/cron/jobs.json")
text = p.read_text()
for old, new in {
    "daily_vineyard_briefing": "daily-vineyard-briefing",
    "vineyard_disease_risk": "vineyard-disease-risk",
    "risk_alert_policy": "risk-alert-policy",
    "farmer_report_compose": "farmer-report-compose",
    "farmer_feedback_capture": "farmer-feedback-capture",
    "farmer_notify": "farmer-notify",
    "report_guard": "report-guard",
    "vineyard_guard_scheduler": "vineyard-guard-scheduler",
    "vineyard_model_explainer": "vineyard-model-explainer",
}.items():
    text = text.replace(old, new)
data = json.loads(text)
for job in data.get("jobs", []):
    if str(job.get("id", "")).startswith("vineyard_guard_"):
        job["enabled"] = False
        job["disabled_reason"] = (
            "Replaced by deterministic BusyBox crond tick: "
            "/root/.picoclaw/workspace/scripts/vineyard_guard_tick.sh"
        )
        job["updatedAtMs"] = int(time.time() * 1000)
data["jobs"] = [job for job in data.get("jobs", []) if job.get("id") != "codex_command_probe"]
p.write_text(json.dumps(data, indent=2))
PY
fi

if [ -f /etc/init.d/S97picoclaw_gateway ]; then
  if ! grep -q "PICOCLAW_HOME=/root/.picoclaw" /etc/init.d/S97picoclaw_gateway; then
    cp /etc/init.d/S97picoclaw_gateway /etc/init.d/S97picoclaw_gateway.bak.$(date +%Y%m%d_%H%M%S)
    awk '
      /gateway -E/ && !done {
        print "export HOME=/root"
        print "export PICOCLAW_HOME=/root/.picoclaw"
        print "unset TZ"
        print "cd /root"
        done=1
      }
      { print }
    ' /etc/init.d/S97picoclaw_gateway > /tmp/S97picoclaw_gateway
    cat /tmp/S97picoclaw_gateway > /etc/init.d/S97picoclaw_gateway
    chmod +x /etc/init.d/S97picoclaw_gateway
  fi
fi

if command -v /opt/picoclaw/picoclaw >/dev/null 2>&1; then
  /opt/picoclaw/picoclaw skills list 2>/tmp/skills.err | grep -E "vineyard|risk|farmer|report-guard" || true
  cat /tmp/skills.err || true
fi

wget -qO- --post-data="" http://127.0.0.1:18790/reload 2>/tmp/reload.err || cat /tmp/reload.err || true

echo "restarting PicoClaw app runtime if installed"
app_restarted=0
for init in /etc/init.d/*picoclaw* /etc/init.d/*PicoClaw* /etc/init.d/*app_picoclaw*; do
  if [ -x "$init" ] && [ "$(basename "$init")" != "S30picoclaw_skill_mounts" ] && [ "$(basename "$init")" != "S32vineyard_guard_crond" ] && [ "$(basename "$init")" != "S97picoclaw_gateway" ]; then
    if "$init" restart 2>/tmp/picoclaw_app_restart.err; then
      app_restarted=1
    else
      cat /tmp/picoclaw_app_restart.err || true
    fi
  fi
done
if [ "$app_restarted" = "0" ]; then
  pkill -f '/opt/app_picoclaw/main.py|/opt/app_picoclaw/picoclaw.py|python.*app_picoclaw|python.*pico/main.py' 2>/dev/null || true
fi

python3 -m py_compile /root/.picoclaw/workspace/pico/picoclaw.py 2>/tmp/picoclaw_compile.err || cat /tmp/picoclaw_compile.err || true
SH

echo "done"
