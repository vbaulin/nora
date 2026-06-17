---
name: vineyard-disease-risk
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 300
parameters:
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: mode
    type: string
    default: current_status
  - name: disease
    type: string
    default: downy_mildew
  - name: field
    type: string
  - name: date
    type: string
  - name: start
    type: string
  - name: end
    type: string
  - name: key
    type: string
  - name: output_dir
    type: string
    default: results
  - name: no_plot
    type: boolean
    default: false
  - name: feedback_type
    type: string
  - name: grade
    type: integer
  - name: severity
    type: string
    default: moderate
  - name: notes
    type: string
  - name: product
    type: string
  - name: product_number
    type: string
  - name: lot
    type: string
  - name: dose
    type: string
  - name: water_volume
    type: string
  - name: area
    type: string
  - name: method
    type: string
  - name: target
    type: string
  - name: treatment_type
    type: string
  - name: products_json
    type: string
  - name: model_path
    type: string
  - name: features_json
    type: string
  - name: neighbours_file
    type: string
    default: neighbours.yaml
  - name: neighbour_radius_km
    type: number
  - name: all_neighbours
    type: boolean
    default: false
  - name: skip_supabase
    type: boolean
    default: false
  - name: timeout
    type: integer
    default: 300
returns:
  - status
  - mode
  - result
---
# Vineyard Disease Risk

Board-facing wrapper for the Goidanich vineyard disease model tool.

Use this skill when picoClaw or a long-running monitor needs to:

- check whether the disease model repository is ready;
- run the daily mildew update;
- read latest risk rows from SQLite;
- refresh federated neighbours from Supabase;
- push/pull feedback events and shared model artifacts;
- run a locked daily cron update;
- run a period report;
- record farmer feedback;
- score a compact feature vector with a compiled personalized model scorer.
- run pandas-free prediction on the board from local SQLite rows.
- generate a pandas-free board plot from local SQLite prediction rows.
- fill observed weather/baseline gaps on the board without pandas.
- update stable dashboard files from board-local predictions.

## Modes

### `health`

Checks that the Goidanich repository, key config files, model scripts, and
SQLite database are present.

Required/optional inputs:

- `repo_path`: path to the Goidanich repo. Defaults to
  `/root/.picoclaw/workspace/goidanich`.

### `daily_update`

Runs:

```bash
python3 daily_update.py --date YYYY-MM-DD --disease <disease>
```

Optional inputs:

- `date`
- `field`
- `disease`
- `skip_supabase=true`

### `cron_daily`

Runs the same daily update through a local lock file in `results/` and then
returns `current_status`. Use this from cron, systemd timers, or a picoClaw
scheduler when the task may be triggered automatically.

Why this exists: if yesterday's weather/model job is still running, a new
morning run should return `already_running` instead of starting a second model
process on a small board.

Optional inputs:

- `date`
- `field`
- `disease`
- `skip_supabase=true`
- `timeout` in seconds, default `900` for this mode

### `current_status`

Reads the latest prediction rows from `goidanich.db`.

Important interpretation:

- Personalized risk is the farmer-facing alert risk.
- Original Goidanich is the deterministic weather/index baseline.
- Rossi is a primary-infection comparison model for downy mildew.
- Do not tell the farmer "no mildew" unless there is explicit clean feedback.

### `board_predict`

Runs prediction on the board without pandas. It reads existing
`goidanich_daily_predictions`, `rossi_daily_predictions`, `meteo_raw`, and
feedback rows from SQLite, computes the lightweight rolling features with the
Python standard library, scores the personalized JSON model, and writes
`disease_daily_predictions`.

For `downy_mildew`, it also updates
`goidanich_daily_predictions.personalized_risk`, so `current_status` and alert
policy see the new board-side prediction.

Use this when the board has local model/data rows and needs prediction even
though pandas cannot be installed.

Optional inputs:

- `field`
- `disease`
- `date` or `end`
- `start`
- `days`
- `model_path`

### `board_plot`

Pandas-free board plot path. It reads `disease_daily_predictions` and
`goidanich_daily_predictions` from SQLite and writes a real SVG plot under
`results/`.

Use this on the LicheeRV Nano instead of `predict_period` when pandas is not
available. It requires prediction rows; run `board_predict` first if needed.

### `board_fill_gaps`

Pandas-free replacement for a narrow `daily_update.py --start --end` gap fill.
It fetches observed station CSV with stdlib `urllib`, stores `meteo_raw`,
computes Goidanich baseline rows, writes `goidanich_daily` and
`goidanich_daily_predictions`, then calls `board_predict`.

Use this on the board instead of:

```bash
python3 daily_update.py --field <field> --start YYYY-MM-DD --end YYYY-MM-DD
```

Required inputs:

- `field`
- `start`
- `end`

Optional inputs:

- `disease`
- `retry_attempts`
- `retry_delay_minutes`
- `db_path`

### `board_update_dashboard`

Pandas-free unified model refresh and dashboard file updater. It refreshes all
board-side disease model layers that are available for the disease, runs
`board_predict.py` unless `skip_predict=true`, reads SQLite prediction rows, and
writes stable files:

- `results/dashboard_state_<disease>.json`
- `results/dashboard_report_<disease>.md`
- `results/dashboard_latest_<disease>.png`
- legacy `results/dashboard_state.json`, `dashboard_report.md`, and
  `dashboard_latest.png` copies for the latest successful disease run

Use this when the dashboard needs updated files after prediction or gap filling,
or when any model layer such as Rossi is missing. picoClaw should not call
submodel-specific regeneration routes directly.

Daily invariant:

- run this once per disease per day, normally from cron or
  `daily-vineyard-briefing mode=daily_briefing`;
- default report horizon is the last month (`days=31`) plus forecast projection;
  do not expand farmer-facing dashboards into the winter cold period unless the
  user explicitly asks for a season or historical plot;
- if the disease-specific dashboard state was already generated today and
  `model_layer_freshness` confirms all required layers are current, reuse it;
- if the plot is missing/tiny/stale or any required layer is missing/stale,
  regenerate with this mode before answering the farmer;
- for `downy_mildew`, required layers are personalized/Goidanich/Rossi;
- for `powdery_mildew`, required layers are personalized, UC/Gubler-Thomas, and
  PMI.
- the canonical plot is the rich `agent_dashboard.py`-style PNG with full
  disease-specific model lines, accumulated infection lines, forecast
  projection, rain, meteorology, and status panel. This is the May-9
  `predict_period.py` / `agent_dashboard.py` path. A simplified fallback PNG
  may be used only as an emergency diagnostic artifact; do not send it to the
  farmer as the finished dashboard.

### `sync_neighbours`

Runs:

```bash
python3 supabase_sync.py --pull-neighbours --neighbours-file neighbours.yaml
python3 stations.py
```

This updates the local neighbour cache from active Supabase agents and rebuilds
SQLite topology. Use it when picoClaw asks for "updated neighbours" or before a
long monitoring season starts.

Optional inputs:

- `neighbours_file`
- `neighbour_radius_km`
- `all_neighbours=true`

### `sync_all`

Runs:

```bash
python3 supabase_sync.py --all --disease <disease>
python3 stations.py
```

This is the broad federated maintenance pass: registration, event exchange,
neighbour refresh, model-delta push, released model pull, and topology rebuild.

### `supabase_sync`

Alias for `sync_all`. Use this exact mode in PicoClaw scheduled jobs when the
intent is "sync with Supabase" or "refresh neighbour network". It runs:

```bash
python3 supabase_sync.py --all --disease <disease>
python3 stations.py
```

Expected effects:

- push pending farmer feedback/events;
- pull neighbour events/risk signals;
- refresh active neighbour list/network topology;
- push local model deltas;
- pull released/shared model version when available;
- rebuild local SQLite topology from `agent_config.yaml` + `neighbours.yaml`.

Run this before daily dashboard refresh and risk-only alert checks.

### Federated one-shot modes

Use these when picoClaw wants one clean operation instead of a full daily update:

- `register_agent`
- `push_events`
- `pull_events`
- `push_model_deltas`
- `pull_model_version`
- `latest_neighbours`

All modes return compact JSON and keep the shell details behind the skill
boundary.

### `predict_period`

Runs:

```bash
python3 predict_period.py --field <field> --start YYYY-MM-DD --end YYYY-MM-DD --key <key> --disease <disease>
```

By default this uses Goidanich's existing dashboard plot renderer and returns
the generated report/CSV/plot paths. Use `no_plot=true` only when Matplotlib is
not available or the caller explicitly wants text/CSV only.

### `record_feedback`

Runs `record_feedback.py` with a confirmed farmer label.

Allowed feedback types include:

- `detected_mildew`
- `grade`
- `clean_inspection`
- `false_alarm`
- `treatment`
- `not_inspected`
- `model_confirmed`

Use `grade` with `grade=0..4`.

For `treatment`, preserve the farmer's product details instead of flattening
them into notes. Supported structured fields:

- `product`: product/commercial name;
- `product_number`: registration, authorization, or internal product number;
- `lot`: batch/lot number;
- `dose`: product dose, for example `2 kg/ha`;
- `water_volume`: spray water volume, for example `400 L/ha`;
- `area`: treated area, for example `0.8 ha`;
- `method`: application method, for example `spray`;
- `target`: disease/canopy target;
- `treatment_type`: treatment family such as `copper`, `sulfur`,
  `systemic`, `biocontrol`, or `other`.
- `products_json`: optional JSON list for multi-product applications. Each
  object should preserve the farmer's original words and normalized values,
  for example `product`, `product_number`, `lot`, `quantity`, `unit`,
  `quantity_per_ha`, `unit_per_ha`, `dose`, and `notes`.

A confirmed `treatment` feedback record is a state-changing event. Downy
forecast accumulated lines may be continued only if no treatment is recorded
between the observed line seed and the forecast window.

### `score_features`

Scores one compact feature JSON object using the Go scorer in
`cmd/personalized_score`. Prefer a prebuilt board binary if present; otherwise
the wrapper can use `go run` when Go exists on the board.

Inputs:

- `model_path`
- `features_json`

## Operational Rules

- Use ISO dates: `YYYY-MM-DD`.
- Interpret missing `date` as board-local today.
- Never confuse neighbor/regional alerts with EPI.
- For `powdery_mildew`, show UC powdery disease pressure and PMI as treatment
  timing support, not an automatic treatment order.
- Keep output compact. The skill returns raw command JSON/text for picoClaw to
  summarize.
- Do not ask remote boards to open HTTP ports. Supabase is the coordination
  layer for neighbour discovery, feedback events, and released shared models.
- On the LicheeRV Nano, prefer the compiled Go scorer for fast local inference.
  Run the heavier Python/pandas daily pipeline on the board only if provisioned,
  or on the colocated picoClaw/gateway machine with `repo_path` pointing to the
  mounted Goidanich project.
