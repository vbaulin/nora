---
name: daily-vineyard-briefing
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 1200
parameters:
  - name: mode
    type: string
    default: daily_briefing
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: field
    type: string
  - name: disease
    type: string
    default: downy_mildew
  - name: days
    type: integer
    default: 14
  - name: start
    type: string
  - name: end
    type: string
  - name: key
    type: string
  - name: outbox_dir
    type: string
    default: /tmp/picoclaw_outbox
  - name: channel
    type: string
    default: picoclaw_telegram
  - name: memory_path
    type: string
    default: /tmp/vineyard_alert_memory.json
  - name: board_only
    type: boolean
    default: false
  - name: capture_on_alert
    type: boolean
    default: false
  - name: photo_path
    type: string
returns:
  - status
  - mode
  - notified
  - plot_path
  - outbox_json
---
# daily-vineyard-briefing / Vineyard Guard

First-class Vineyard Guard orchestration skill. It treats the existing skills as
muscles and provides an explicit API for picoClaw, cron tasks, and Telegram
workflows.

Default `mode=daily_briefing` is the same verified dashboard/report path as
`standard_report`, normally with `notify=false` for cron. It refreshes the
daily cache once, verifies that all required model layers and the PNG plot are
current for today, then reuses that cache for the rest of the day.

Daily cache validity:

- valid for one calendar day only;
- plot must exist, be PNG, and be large enough to be a real dashboard;
- latest history row must equal today's date;
- downy mildew requires personalized/Goidanich/Rossi rows for today;
- powdery mildew requires personalized, UC/Gubler-Thomas, and PMI rows for
  today;
- if any layer or plot is stale/missing, call the unified
  `vineyard-disease-risk mode=board_update_dashboard` path to regenerate gaps,
  models, dashboard state, and plot;
- after a successful refresh, later requests deliver the fresh cached plot and
  report instead of regenerating or offering old PNG choices.

Supported one-shot modes:

- `trigger_daily_update`
- `get_current_risk`
- `run_board_prediction` / `board_predict`
- `generate_period_plot`
- `evaluate_alert_policy`
- `optionally_capture_canopy_photo`
- `package_farmer_alert`
- `both_disease_report` / `generic_report` / `risc_report` / `risk_report`
- `standard_report` / `farmer_report` / `vineyard_guard` / `telegram_report`
- `daily_briefing` / `run_daily_guard`

Use `both_disease_report` for generic farmer requests such as `risc`, `risk`,
`vineyard risk`, or "give me the report" when the user does not name only one
disease. It runs `standard_report` for both `downy_mildew` and
`powdery_mildew`, and returns both PNG plots in `attachments` / `media` plus
the full text for both diseases. This is not optional: a generic risk answer
that sends only text, only one image, or asks the user whether to send the plot
is a contract failure.

Use `standard_report` when a user asks for a disease report. It first checks
the daily verified cache. If the cache is fresh, it delivers the cached report
and plot. If not, it runs board prediction, fills observed weather/baseline
gaps, refreshes all disease-specific model layers, updates stable dashboard
files, reads current status, and calls `farmer-report-compose`, returning the
full standardized report and a real `dashboard_latest_<disease>.png` plot path
in one JSON response.

Default plot/report horizon is the last month (`days=31`) plus the available
forecast projection window. Do not expand this into the winter cold period for
farmer-facing disease reports unless the user explicitly asks for a season or
historical report.

The canonical plot is the rich May-9 `predict_period.py` /
`agent_dashboard.py` PNG: full title, rain, model lines, accumulated infection
lines, forecast projection window, local meteorology, and status panel. A
simple fallback PNG must not be presented to the farmer as the finished
dashboard.

`standard_report` returns top-level `send_text`, `send_image_path`,
`send_photo_path`, `attachments`, `telegram`, `must_attach_image=true`, and
`must_send_exactly=true`; picoClaw must send those exact fields rather than
hand-composing a shorter message. The default image is PNG because Telegram
handles it reliably. A one-paragraph low-risk summary is not a valid substitute
for the standardized report, and a path printed as text is not a valid image
delivery.

For user-requested Telegram delivery, call with `notify=true` and
`channel=picoclaw_telegram`. This writes `/tmp/picoclaw_outbox/*.json` with
`telegram.method`, `media`/`attachments`, `send_text`, and
`must_send_exactly=true`. Silent scheduler cache refreshes should keep
`notify=false`.

`vineyard_guard` is a report alias, not a summary mode. It must return the same
`send_text`, `send_image_path`, `must_send_exactly`, notification, and PNG plot
fields as `standard_report`.

If any model layer is missing, `standard_report` must use
`vineyard-disease-risk mode=board_update_dashboard`, which is a compatibility
alias for the May-9 `predict_period.py` dashboard path, then compose the report
from the repaired status. "not available" is only valid after this refresh path
fails and the JSON includes that failure evidence.

For `powdery_mildew`, use the May-9 `predict_period.py` / `agent_dashboard.py`
path so the UC/Gubler-Thomas and PMI layers are plotted in the same style as
the reference dashboards.

The skill writes a farmer notification package by default; picoClaw's existing
Telegram transport reads the outbox payload and must send the PNG as a photo
attachment with the report as the caption. `send_photo_path` points to a copy
of the PNG inside the outbox directory, so the consumer should upload that file
directly instead of printing the path.

Set `board_only=true` when running on the LicheeRV Nano without pandas. In that
mode, `trigger_daily_update` uses `vineyard-disease-risk mode=board_predict`,
which performs local SQLite/model prediction without importing pandas, and
`generate_period_plot` uses `vineyard-disease-risk mode=board_plot`.
