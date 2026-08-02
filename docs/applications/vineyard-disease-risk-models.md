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
- VitiMeteo grapevine black-rot infection-index and incubation model for
  *Guignardia bidwellii*, with a labelled
  rain/RH leaf-wetness proxy when no wetness sensor is installed.
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

Explicit black-rot requests use the additional board skill:

```text
skills/black_rot_risk/
  SKILL.md
  run.py
  run.sh
```

Grapevine black rot is reported as infection degree-hours (`85`, `150`, and `300`
event thresholds) and a `175` degree-day leaf-incubation projection. It is not
reported as percentage disease probability. The skill preserves the local
inoculum status and whether leaf wetness was measured or inferred.

The term is pathogen-qualified deliberately: grapevine black rot caused by
*Guignardia bidwellii* (syn. *Phyllosticta ampelicida*) is distinct from
secondary bunch rots associated with *Aspergillus*, *Penicillium*, and other
opportunistic fungi. The current secondary-bunch-rot concern is retained as
field metadata, but Vineyard Guard does not yet claim a validated predictive
model for that disease complex.

The daily notification policy forwards a threshold-crossing VitiMeteo weather
signal even when local inoculum is unknown. In that case it is explicitly an
unconfirmed model signal, not diagnosed disease: the plot is attached and the
farmer is asked to report compatible symptoms, no symptoms, or a false alarm.
A statement that an expert has not personally observed the disease is retained
as provenance, not converted into a regional presence/absence conclusion.

The primary index requires leaf wetness. Boards without a leaf-wetness sensor
use the explicit rain/RH >=95% proxy and also calculate a separate
near-saturation sensitivity index for hours at RH 90-<95%. Crossing 85
degree-hours in the sensitivity index creates a `wetness_uncertain_watch`; it
does not rewrite the primary VitiMeteo index and is not a confirmed infection
event. A primary value of zero therefore means that the proxy did not confirm
wetness, not that disease probability is zero.

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
- A black-rot infection event is weather evidence conditional on inoculum, not
  confirmation of symptoms or an automatic treatment order.
- A threshold-crossing black-rot weather signal is delivered regardless of
  inoculum status. Unknown inoculum adds a field-confirmation request and does
  not turn the signal into a diagnosis or treatment order.
- A black-rot wetness-uncertainty watch means canopy wetness is plausible but
  unmeasured; inspect locally and prefer a calibrated leaf-wetness sensor.

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
