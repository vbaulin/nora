# Vineyard Disease Risk Models

This application connects nano-os-agent to the Goidanich vineyard disease model
tool in `/root/goidanich` or another configured repository path.

It is different from image-only disease detection. The Goidanich tool is a
weather, biology, feedback, and federation model for vineyard mildew risk.

## What It Runs

- Original Goidanich downy mildew weather/index prior.
- Rossi primary-infection comparison for downy mildew.
- Personalized local risk trained from farmer feedback.
- Powdery mildew prior models and PMI timing support.
- Supabase event/model sync when enabled.
- Supabase neighbour refresh from active agents.
- Period reports and dashboard plots.
- Field feedback recording.
- Optional compact Go scorer for board-side personalized inference.

## Board Skill

The board-facing skill is:

```text
skills/vineyard_disease_risk/
  SKILL.md
  run.sh
```

Modes:

- `health`
- `daily_update`
- `cron_daily`
- `current_status`
- `sync_neighbours`
- `sync_all`
- `register_agent`
- `push_events`
- `pull_events`
- `push_model_deltas`
- `pull_model_version`
- `latest_neighbours`
- `predict_period`
- `record_feedback`
- `score_features`

Example task step:

```yaml
- id: daily_disease_update
  action: call_skill
  parameters:
    skill_name: vineyard_disease_risk
    repo_path: /root/goidanich
    mode: cron_daily
    disease: downy_mildew
    date: ${date}
    timeout: 900
  expect:
    status: success
```

Neighbour refresh is also a first-class board action:

```yaml
- id: refresh_neighbours
  action: call_skill
  parameters:
    skill_name: vineyard_disease_risk
    repo_path: /root/goidanich
    mode: sync_neighbours
    neighbours_file: neighbours.yaml
    neighbour_radius_km: 15
  expect:
    status: success
```

This runs `supabase_sync.py --pull-neighbours` and then `stations.py`, so the
local `topology` table reflects newly active nearby boards before risk is
computed.

## Alert Semantics

- Personalized risk is the main farmer-facing alert risk.
- Original Goidanich remains the transparent deterministic baseline.
- Rossi is primary-infection biology for comparison, not a second personalized risk.
- Neighbor/regional pressure is not EPI.
- Do not say "no mildew" unless there is clean inspection or false-alarm feedback.
- Powdery PMI is treatment-timing support, not an automatic treatment order.

## Why It Fits picoClaw + nano-os-agent

picoClaw can reason about field reports, farmer language, and model
interpretation. nano-os-agent can run the daily deterministic update, read
SQLite status, record feedback, and expose compact JSON results through MCP.

For the full control-plane contract, including picoClaw on the machine,
`../goidanich`, cron tasks, neighbour refresh, and federated learning modes, see
[picoClaw, nano-os-agent, and Goidanich coordination](../../PICOCLAW_GOIDANICH_COORDINATION.md).

The useful loop is:

```text
daily update
-> latest risk rows
-> concise alert/watch/normal message
-> farmer feedback
-> record_feedback
-> push/pull events and shared model updates
-> retrain/personalize
-> next daily update
```

## Example Real Change

A farmer records `clean_inspection` after a high alert. The next daily update
uses that local feedback to reduce future false alerts for this field, while the
baseline Goidanich value remains visible and unchanged. The board has not hidden
the biological prior; it has learned how this field responds.
