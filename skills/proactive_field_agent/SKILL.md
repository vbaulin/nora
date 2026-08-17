---
name: proactive-field-agent
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 180
parameters:
  - name: mode
    type: string
    default: tick
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: state_dir
    type: string
    default: /root/.picoclaw/workspace/proactive_field
  - name: field
    type: string
  - name: notify
    type: boolean
    default: false
  - name: research
    type: boolean
    default: false
  - name: proposal_id
    type: integer
  - name: decision
    type: string
  - name: note
    type: string
  - name: raw_text
    type: string
  - name: operation_type
    type: string
  - name: occurred_at
    type: string
  - name: confirmed
    type: boolean
    default: false
  - name: language
    type: string
  - name: search_env
    type: string
    default: /root/.picoclaw/search.env
  - name: nano_root
    type: string
    default: /root/nano-os-agent
  - name: notify_threshold
    type: integer
    default: 70
  - name: topic
    type: string
  - name: limit
    type: integer
returns:
  - status
  - observations
  - proposals
  - pending_proposal
  - investigations
  - research_request
  - notification
  - operations
  - facts
  - decisions
  - derived_insights
  - alert_diseases
  - next_route
  - confirmation_question
---
# Proactive Field Agent

Turn the board from a passive monitor into an evidence-linked field assistant.
The skill observes current local state, remembers confirmed field knowledge,
proposes one bounded next step, talks to the farmer through PicoClaw's existing
Telegram outbox, and incorporates the farmer's confirmed reply. It does not add
another gateway, bot token, LLM runtime, or uncontrolled agent loop.

Use this skill for proactive field assistance, learned field state, pending
checks, farmer decisions, general operations, bounded research, and follow-up
to a `PF-<id>` Telegram message. Current disease facts still come from the
disease skills and dashboard cache. Session text and previous assistant
messages are never evidence.

An open question is answered by investigation, never by proposing hardware.

## Evidence Order

1. Current field definitions and stable covariates in `agent_config.yaml`.
2. Fresh dashboard JSON and PNG artifacts for each independent disease.
3. Confirmed farmer feedback and treatment/operation records.
4. nano-os-agent task evidence and experiment journal entries.
5. Source-attributed public research, retained as candidate evidence for local
   comparison.

A nano-os-agent result enters field memory only after its declared experiment
checks pass. A failed, partial, blocked, or internally inconsistent experiment
is quarantined: its measurements are excluded from farmer advice, an internal
investigation is opened, and one bounded source search is queued. The farmer
sees a remedy proposal only after public sources are attached.

If required disease state is absent or stale, create an internal
`refresh_required` proposal. Do not improvise farmer advice from memory.

## Modes

- `tick`: observe current local evidence, run the bounded investigations,
  update memory, create at most one new proposal per field and optionally
  package the highest-priority proposal for Telegram.
- `observe`: update evidence, field profiles and investigations without
  creating proposals.
- `investigate`: run the investigation registry for one field or all fields and
  return the full findings without contacting anyone.
- `investigations`: list stored findings, optionally filtered by `topic`.
- `status`: return field profiles, current evidence, investigations, pending
  proposals and queued research.
- `research`: run one bounded web search (Tavily, then Brave when configured,
  otherwise DuckDuckGo HTML with a DuckDuckGo Lite fallback), retain source
  URLs/snippets, and synthesize internal candidate evidence. It does not ask the
  farmer to read or compare papers.
- `next_research`: return the oldest queued research request.
- `ingest_research`: store externally collected, source-attributed results.
- `next_proposal`: return the highest-priority pending proposal.
- `proposal_context`: resolve a `PF-<id>` or the single active field-check or
  operation-follow-up proposal. Disease checks resolve to their configured
  field and exact alert disease(s). General-operation follow-ups resolve to
  `draft_operation`; treatment outcomes resolve to `farmer-feedback-capture`.
  It never writes. If more than one field or disease is possible, return one
  localized clarification question instead of guessing.
- `record_decision`: record farmer `accepted`, `rejected`, `deferred` or
  `corrected` feedback for a proposal.
- `draft_operation` / `record_operation`: structure and confirm general field
  operations such as pruning, mowing, soil work, irrigation, fertilization,
  cover-crop work or harvest. Treatments and disease inspections are redirected
  to `farmer-feedback-capture`.
- `remember`: store a farmer-confirmed or locally observed fact with provenance.
- `notify`: package an existing pending proposal through `farmer-notify`.
- `self_test`: validate SQLite integrity, configured-field discovery, disease
  state coverage, nano journal visibility and the existing notification route.

## Investigations

Every detected pattern becomes a bounded investigation before it becomes a
message. An investigation is stored with its question, method, window, sample
size, verdict, confidence, findings, limitations, ranked options and the source
references it read.

This skill is the vineyard **adapter**: it phrases findings for the farmer,
delivers them, and records decisions. The domain-neutral engine lives in
`research-agent`, and `pack.py` here declares the vineyard's standing questions
as parameters for that engine's generic analyses. The topics below are the
farmer-facing side of the same questions.

The scheduled research route also groups fields by cultivar and queues one
source search per distinct variety. Candidate phenology, thermal requirement,
solar/water response, and maturity literature is attached to every field of
that variety as `variety_evidence_profile`. It remains a prior until the board
has local dated phenology and berry-composition measurements. The generic
research engine separately discovers relationships among the daily climate,
disease, operation, and future fruit-quality series; these relationships are
not hardcoded in this skill.

Registered topics:

- `leaf_wetness_proxy`: compares the confirmed VitiMeteo infection index with
  the upper-bound index that also counts near-saturated air, then checks
  whether each ambiguous day was already covered by a confirmed threshold
  crossing within two days. It also detects the systematic case where the
  station never reaches the RH>=95% criterion at all.
- `peer_signal_divergence`: compares confirmed events from nearby boards with
  the local model value for the same disease, using reported coordinates and
  the local/regional radius.
- `alert_calibration`: audits the board's own notified alerts against the
  confirmed outcomes that came back, and proposes fewer messages when the
  record does not justify them.

Verdicts decide what happens next:

- `material_unresolved`: a decision-relevant question the board cannot close
  from its own data. This is the only verdict that may reach the farmer.
- `not_material`: the ambiguity exists but changed no decision. It stays in
  evidence memory. It is sent once, as a closure, only if the farmer was
  already asked about that topic.
- `resolved_local`: the board's own data already answers it, for example a
  field that records measured wetness hours.
- `insufficient_data`: the analysis could not run. This creates an internal
  gap, never a farmer message and never a hardware suggestion.

A farmer-facing finding must report what was checked, over how much data, what
came out, and what remains open, using its own numbers. Options are ordered by
cost: an observation the farmer can make for free comes first, a comparison
with an existing peer board next, and hardware last. A hardware option is
offered only when cheaper options accompany it, at most once per field per
season, and never again after any refusal. Refusing is always an offered
answer; a rejected proposal closes its subject for the season instead of
returning after a short cooldown.

An external search is queued only for the question a local investigation could
not settle, and it asks the scientific question, not a product question.
Search results are internal evidence: store their URLs and a bounded synthesis,
compare them against the field record automatically, and do not create a
farmer-facing `research_review` proposal. Never send snippets or ask the farmer
for permission to read, compare, or interpret papers. Contact the farmer only
when the completed comparison leaves one decision-relevant fact that only a
field observation can supply.

## Telegram Conversation

Scheduled use is deterministic:

```json
{"mode":"tick","notify":true,"research":false}
```

The cycle creates no more than one new proposal per field. A farmer-facing
proposal must contain the field name, concrete model/measurement signal, clear
uncertainty, and a `PF-<id>` reference. It asks for one useful next response,
for example an inspection outcome, recent protection record, missing stable
field attribute, or a choice between the options of a finished investigation.

A reply to an `investigation:<topic>` proposal resolves through
`proposal_context` to `next_mode=record_decision` and carries the finding's
options; map the answer to one option and record it. Nothing is written before
that decision, and a refusal is recorded as a decision, not as a delay.

For `leaf_wetness_proxy`, a direct answer such as `sí, les fulles són
mullades`, `están secas`, or `yes, wet` is itself the requested observation.
Record it immediately with `option_id=same_day_canopy_check`, a timestamp and
the farmer's exact note. Persist it to `leaf_wetness_observations`, rerun the
black-rot model and local investigation, close the answered proposal and any
superseded wetness source search, then return the localized conclusion in the
same Telegram turn and mark the question complete. Do not leave a separate
closure message for the next scheduled cycle. Do not ask for a
second confirmation, a paper review, or a sensor purchase. One observation is
one measured hour/event; it must not be expanded into an unobserved whole night.

For a farmer reply such as `PF-12: cap símptoma`, first call:

```json
{"mode":"proposal_context","raw_text":"PF-12: cap símptoma"}
```

If exactly one field and disease are resolved, pass those values plus the raw
message to `farmer-feedback-capture` with `confirmed=false`. Show its structured
draft and ask the farmer to confirm or correct it. Only the second call with
`confirmed=true` may write and synchronize the event. A PF reference with a
clear `accepted`, `rejected`, `deferred`, or `corrected` decision instead uses
`record_decision` and never implies that an operation was executed.

Confirmed pruning, mowing, soil, irrigation, fertilization, cover-crop,
planting, harvest, sensor, and treatment records are followed up after a
bounded operation-specific delay. If no later confirmed outcome exists, the
agent asks once what was observed and when. A general-operation answer is
drafted through `draft_operation`; a treatment/scouting answer remains on the
catalog-aware `farmer-feedback-capture` route. Once confirmed, the sequence is
stored as an `observed_association` with `causal_claim=false`. The agent may
learn that one event followed another; it may not claim that the operation
caused the outcome without stronger evidence.

The notification path is `proactive-field-agent -> farmer-notify -> existing
Telegram outbox/sender`. Alert proposals attach only plots belonging to the
alert disease(s). If today's daily disease briefing already covers the same
field and signal, notification is marked `skipped_covered`; the proposal stays
in evidence memory without generating a duplicate Telegram message.

Bounded internet research stores source-attributed internal syntheses. The
board performs the field-specific comparison automatically; source lists and
snippets never become proactive Telegram proposals. Search evidence does not
become a treatment instruction, product selection, threshold change, hardware
suggestion, or confirmed field fact by itself.

Search credentials are read from the process environment, the explicit
`search_env`, `/root/.picoclaw/search.env`, or the application `.env`, in that
order. Only `TAVILY_API_KEY` and `BRAVE_SEARCH_API_KEY` are parsed; no other
secret is loaded into proactive memory, traces, or farmer messages. A paid or
keyed provider is preferred because the keyless DuckDuckGo HTML endpoint may
return a challenge page or rate-limit embedded clients. The runtime retries
the same bounded query against DuckDuckGo Lite when the HTML response contains
no parseable results; it does not broaden the query, expose snippets to the
farmer, or turn them into operational instructions.

This also closes the nano-os-agent evaluation loop. A passing field experiment
is stored as `observed_success` with the narrow interpretation that one run
passed its declared checks. A failed or partial run creates
`experiment_investigation` and remains internal. A successful bounded search
adds a source-attributed synthesis to evidence memory and closes the internal
investigation; it does not delegate troubleshooting to the farmer.

Always reply in the farmer's configured/question language. Preserve field
names and model values exactly; never expose raw JSON, database rows, or local
file paths in the farmer-facing text.

## Safety Contract

- Web snippets are candidate evidence, never agronomic truth.
- A proposal may ask for scouting, records, a sensor, or expert review. It must
  never claim that a treatment was applied or order an automatic application.
- Hardware is a last option inside a finished investigation, never the answer
  to an open question, never offered alone, and never repeated after a refusal.
- Product selection, dose and treatment recording remain the two-step
  `farmer-feedback-capture` route.
- Stale/missing dashboards generate an internal refresh request, not farmer
  advice.
- An analysis that could not run is an internal gap, not a farmer message.
- Every farmer-facing proposal requires confirmation and includes its evidence
  references.

## Grapevine Black Rot

- `Black rot` here means grapevine black rot caused by *Guignardia bidwellii*
  (syn. *Phyllosticta ampelicida*). In Catalan use `Black rot de la vinya
  (Guignardia bidwellii)`, not the ambiguous label `podridura negra` alone.
- Secondary bunch rots associated with *Aspergillus*, *Penicillium*, or other
  opportunistic fungi are a separate disease complex and are not inferred from
  this model.
- A person's lack of previous observation is not evidence of regional absence.
  Store local inoculum as `unknown` until field evidence establishes otherwise;
  do not write `not_reported` unless an explicit records review supports it.
- Unknown inoculum never suppresses a current or forecast threshold crossing.
  Send the degree-hour value, date, wetness source, plot, and the qualification
  `unconfirmed weather-model signal`. Ask for `compatible symptoms`, `no
  symptoms`, or `false alarm` feedback.
- Positive confirmed compatible-symptom feedback may promote the local field
  evidence to `present`. A clean inspection or false alarm is calibration
  evidence for that field/date; it does not establish regional absence.
- No weather-model signal proves infection or authorizes treatment. Scouting,
  protection history, and registered-product checks remain mandatory.
- Canopy wetness is inferred from rain and relative humidity. The uncertainty
  this creates is quantified by the `leaf_wetness_proxy` investigation, which
  compares the confirmed and upper-bound indices over the stored season. It is
  reported only when it would have changed a decision, and it is never
  converted into a standing request for a sensor.
