---
name: black-rot-risk
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 900
parameters:
  - name: mode
    type: string
    default: report
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: field
    type: string
  - name: days
    type: integer
    default: 31
  - name: force_refresh
    type: boolean
    default: false
returns:
  - status
  - send_text
  - attachments
  - media
  - telegram
  - field_reports
---
# Grapevine Black Rot Risk

Runs and reports the published, evaluated VitiMeteo grape black-rot infection and leaf
incubation model. Use this skill for black rot, *Guignardia bidwellii*, black
rot infection periods, symptom timing, or a black-rot plot/forecast.

This disease is grapevine black rot caused by *Guignardia bidwellii*
(syn. *Phyllosticta ampelicida*). It is not the secondary bunch-rot complex
caused by *Aspergillus*, *Penicillium*, or other opportunistic fungi. Never use
the farmer-facing label `podridura negra` or `podredumbre negra` without the
pathogen-qualified name. Catalan reports use `Black rot de la vinya
(Guignardia bidwellii)`.

Do not invoke this skill for the unqualified local terms `podridura negra` or
`podredumbre negra`. Those terms first require `vineyard-model-explainer`
with `disease=rot_clarification`. Do not invoke it for secondary bunch rot,
*Aspergillus*, *Penicillium*, or another opportunistic bunch-rot organism.

The farmer-facing quantity is an infection index in degree-hours, not disease
probability:

- below 85: no modeled infection event;
- 85-149.99: light infection event;
- 150-300: moderate infection event;
- above 300: severe infection event.

When no leaf-wetness sensor exists, the primary index uses rain or RH >=95% as
its explicit proxy. A separate `wetness_uncertain_watch` may be emitted when
RH 90-<95% persists long enough for the wet-canopy sensitivity index to reach
85 degree-hours. This is a warning about potentially unmeasured dew or canopy
wetness, not a confirmed infection event. Never describe a primary index of
zero as 0% disease risk.

Leaf symptoms are projected after 175 bounded degree-days following an
infection event. The board currently uses a labelled rain/RH leaf-wetness proxy
unless a measured leaf-wetness value is supplied. Reports must preserve
`wetness_source` and `inoculum_status`; weather suitability must not be
presented as confirmed disease when local inoculum history is unknown.

Do not suppress a current or forecast threshold crossing when inoculum is
unknown. Return it as an unconfirmed weather-model signal, preserve the
degree-hours and date, attach the disease-specific plot, and ask the farmer to
reply with compatible symptoms, no symptoms, or false alarm. That response is
field evidence; it is not inferred automatically and the signal alone is not a
treatment order.

`mode=report` serves today's valid cache when present and regenerates it once
when missing or stale. `mode=model_info` returns the scientific model contract
without updating weather or dashboards.

Always attach every returned PNG in `attachments`/`media`. Never send a local
path as farmer-facing evidence text.
