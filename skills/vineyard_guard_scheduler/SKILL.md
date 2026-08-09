---
name: vineyard-guard-scheduler
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 30
parameters:
  - name: mode
    type: string
    default: schedule_spec
  - name: field
    type: string
    description: Optional. Omit to run all fields from agent_config.yaml.
  - name: hour
    type: integer
    default: 8
  - name: minute
    type: integer
    default: 0
  - name: timezone
    type: string
    default: Europe/Madrid
  - name: high_threshold
    type: number
    default: 70
  - name: watch_threshold
    type: number
    default: 50
  - name: delta_threshold
    type: number
    default: 15
returns:
  - status
  - scheduler
  - jobs
---
# vineyard-guard-scheduler

Use this skill whenever the user asks to schedule, refresh, monitor, run daily,
run at 8 AM, fix cron, or configure Vineyard Guard automation.

Do **not** use BusyBox/system `crontab`, `/var/spool/cron/crontabs`, `while true`
loops, `/etc/rc.local` watchdog loops, or vague scheduler prompts such as
`EXECUTE_VINEYARD_GUARD_AVGVSTVS`.

The correct scheduler is PicoClaw Gateway CronService, stored under:

`/root/.picoclaw/workspace/cron/jobs.json`

The scheduled action must be explicit and skill-based:

```json
{
  "skill_name": "daily-vineyard-briefing",
  "parameters": {
    "mode": "both_disease_report",
    "days": 31,
    "notify": false,
    "board_only": true
  }
}
```

If `field` is omitted, the scheduler must run every field listed in
`agent_config.yaml`. Each field is separate: separate personalized model,
separate risk alert memory, separate dashboard state, and separate plot.

Alert thresholds must be configurable per job through `high_threshold`,
`watch_threshold`, and `delta_threshold`. Do not hard-code 50/70 into the
scheduled job when the user provides different thresholds.

Daily cache refresh should use `notify=false` so it regenerates fresh dashboard
state and both PNG plots without pushing low-risk Telegram messages.

Daily risk alert should use `notify_mode=risk_only` so it sends Telegram only
when the deterministic alert policy detects watch/high risk or a treatment /
protection signal such as powdery PMI due. This applies to any configured
disease/model layer, including personalized risk, Goidanich baseline,
forecast projection, Rossi, powdery UC, and PMI.

Telegram/user-request delivery should call the same skill with
`mode=both_disease_report` and `notify=true` or with the Telegram transport
preserving `attachments` / `media`. Generic `risc` or `risk` means both
`downy_mildew` and `powdery_mildew`, never one disease.

Valid daily refresh / risk-only alert result:

- both dashboard state files updated today;
- both PNG plots updated today;
- `forecast_current=true`;
- `forecast_refresh_ok=true`;
- `forecast` length > 0;
- renderer version visible in state and PNG;
- no fallback plot.

Recommended schedule:

- 07:55 synchronize downy mildew, powdery mildew, and black-rot history through
  Supabase. The learned mildew routes also pull the active training policy,
  peer deltas, and released shared models; any released model is evaluated on
  the board's own labelled windows before validation metrics are published.
- 08:00 refresh weather, forecasts, deterministic disease layers, dashboards,
  reports, and plots for every configured field. Then fit the field-specific
  downy and powdery models from cached evidence. An artifact with insufficient
  confirmed positive and negative outcomes remains explicitly untrained and is
  never uploaded as a model delta.
- 08:15 evaluate all three disease families independently and package one
  Telegram summary. Only active alerts contribute plots.

The next 07:55 pass contributes any local model that became trainable during
the preceding refresh. Grapevine black rot remains a deterministic infection
model: its separated history is synchronized, but it does not emit logistic
model coefficients.

If PicoClaw cron is used through agent-turn messages, the message must contain
the exact skill call above. A vague trigger phrase is invalid because the LLM
may summarize, pick one disease, or skip attachments.
