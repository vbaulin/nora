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
returns:
  - status
  - observations
  - proposals
  - pending_proposal
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

## Evidence Order

1. Current field definitions and stable covariates in `agent_config.yaml`.
2. Fresh dashboard JSON and PNG artifacts for each independent disease.
3. Confirmed farmer feedback and treatment/operation records.
4. nano-os-agent task evidence and experiment journal entries.
5. Source-attributed public research, explicitly marked for review.

A nano-os-agent result enters field memory only after its declared experiment
checks pass. A failed, partial, blocked, or internally inconsistent experiment
is quarantined: its measurements are excluded from farmer advice, an internal
investigation is opened, and one bounded source search is queued. The farmer
sees a remedy proposal only after public sources are attached.

If required disease state is absent or stale, create an internal
`refresh_required` proposal. Do not improvise farmer advice from memory.

## Modes

- `tick`: observe current local evidence, update memory, create at most one new
  proposal per field and optionally package the highest-priority proposal for
  Telegram.
- `observe`: update evidence and field profiles without creating proposals.
- `status`: return field profiles, current evidence, pending proposals and
  queued research.
- `research`: run one bounded web search (Tavily, then Brave when configured,
  otherwise DuckDuckGo HTML with a DuckDuckGo Lite fallback), retain source URLs/snippets, and create a review
  proposal.
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

## Telegram Conversation

Scheduled use is deterministic:

```json
{"mode":"tick","notify":true,"research":false}
```

The cycle creates no more than one new proposal per field. A farmer-facing
proposal must contain the field name, concrete model/measurement signal, clear
uncertainty, and a `PF-<id>` reference. It asks for one useful next response,
for example an inspection outcome, recent protection record, missing stable
field attribute, or approval to investigate a sensor.

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

Bounded internet research creates source-attributed review proposals at the
normal proactive notification threshold. These messages identify candidate
solutions and ask whether the farmer wants a field-specific comparison. Search
snippets never become treatment instructions, product selections, or confirmed
field facts by themselves.

Search credentials are read from the process environment, the explicit
`search_env`, `/root/.picoclaw/search.env`, or the application `.env`, in that
order. Only `TAVILY_API_KEY` and `BRAVE_SEARCH_API_KEY` are parsed; no other
secret is loaded into proactive memory, traces, or farmer messages. A paid or
keyed provider is preferred because the keyless DuckDuckGo HTML endpoint may
return a challenge page or rate-limit embedded clients. The runtime retries
the same bounded query against DuckDuckGo Lite when the HTML response contains
no parseable results; it does not broaden the query or turn search snippets
into operational instructions.

This also closes the nano-os-agent evaluation loop. A passing field experiment
is stored as `observed_success` with the narrow interpretation that one run
passed its declared checks. A failed or partial run creates
`experiment_investigation`, remains internal, and is replaced by a
source-attributed `research_review` only when the bounded search succeeds.

Always reply in the farmer's configured/question language. Preserve field
names and model values exactly; never expose raw JSON, database rows, or local
file paths in the farmer-facing text.

## Safety Contract

- Web snippets are candidate evidence, never agronomic truth.
- A proposal may ask for scouting, records, a sensor, or expert review. It must
  never claim that a treatment was applied or order an automatic application.
- Product selection, dose and treatment recording remain the two-step
  `farmer-feedback-capture` route.
- Stale/missing dashboards generate an internal refresh request, not farmer
  advice.
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
