---
name: research-agent
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 120
parameters:
  - name: mode
    type: string
    default: cycle
  - name: state_dir
    type: string
    default: /root/.picoclaw/workspace/research
  - name: journal_dirs
    type: string
    default: /tmp/monitors
  - name: pack_dirs
    type: string
  - name: evidence_journal
    type: string
    default: /root/nano-os-agent/experiments.jsonl
  - name: subject
    type: string
  - name: analysis
    type: string
  - name: params
    type: object
  - name: question_id
    type: integer
  - name: finding_id
    type: integer
  - name: decision
    type: string
  - name: option_id
    type: string
  - name: note
    type: string
  - name: watch
    type: boolean
    default: false
  - name: watch_days
    type: integer
    default: 180
  - name: max_questions
    type: integer
    default: 3
  - name: max_seconds
    type: number
    default: 20
  - name: max_files
    type: integer
    default: 12
  - name: max_lines
    type: integer
    default: 400
  - name: idle_recheck_seconds
    type: number
    default: 21600
  - name: task_drafts_dir
    type: string
    default: /root/.picoclaw/workspace/research/task_drafts
  - name: max_new_pairs
    type: integer
    default: 2
  - name: status
    type: string
  - name: verdict
    type: string
  - name: limit
    type: integer
returns:
  - status
  - questions
  - findings
  - reportable
  - investigated
  - watches
  - checks
---
# Research Agent

Turn idle board time into research. The board raises questions from the
evidence it already produced, tests them with bounded deterministic analyses,
keeps the conclusion, and hands back only the findings that would change a
decision. It never sends a message and never acts.

This skill is domain-neutral. It knows about questions, analyses, findings,
verdicts and watches. Vineyards, cameras, microphones and soil probes arrive as
packs.

## Why this exists

A 1 W board spends almost all of its day waiting for the next sample. That idle
time is enough to answer questions about data already on disk. The alternative
is an agent that either stays silent until a human asks, or interrupts on every
raw threshold crossing. Neither is research.

## The loop

```text
signals and human feedback
  -> questions (claim + analysis + parameters)
  -> bounded analysis over local evidence
  -> finding (method, sample, verdict, limitations, options)
  -> human decisions and completed-result bulletins are separated by an adapter
  -> the decision is recorded, and may arm a watch for next time
```

## Modes

- `cycle`: one budgeted idle cycle. Scan for new questions, investigate the
  oldest few, journal the findings. This is the mode a schedule should call.
- `scan`: raise questions from journals and feedback without investigating.
- `catalog`: list inferred channel metadata, entity partitions and adaptive
  clock-window eligibility without returning measurement values.
- `investigate`: run one question (`question_id`), one ad-hoc analysis
  (`analysis` + `params`), or the next few open questions.
- `questions` / `findings` / `reportable`: read stored state. `reportable`
  returns only open findings that require human knowledge. Completed and
  negative findings remain available through `findings`; an adapter may place
  newly changed results in a bounded informational bulletin.
- `record_decision`: store `accepted`, `rejected`, `deferred` or `corrected`
  for a finding, with the chosen `option_id`. `watch=true` on an acceptance
  arms a watch. An adapter that delivered a finding elsewhere echoes the answer
  back through `engine.record_external_decision(subject, analysis, ...)`, so
  feedback collected over Telegram or a dashboard still counts.
- `arm_watch` / `watches`: manage confirmed future actions.
- `self_test`: report registry, packs, journals and stored counts.

## Verdicts

| Verdict | Meaning | Human-action queue | Result bulletin |
| --- | --- | --- | --- |
| `material_unresolved` | Real, decision-relevant, and not answerable from local evidence | Yes, after autonomous deepening | Only when the remaining step is local computation |
| `not_material` | Real, but it changed no decision | No | May be summarized once as a negative result |
| `resolved_local` | Already answered by evidence the board holds | No | May be summarized once |
| `insufficient_data` | The analysis could not conclude | No | May be counted as an explicit data limitation |

An analysis that cannot run is an internal gap. It is never converted into a
request for hardware, budget, or attention.

## Digging further automatically

A material finding may carry the `deeper_analysis` option. That option uses the
board's own time, so it is executed automatically before any notification: the
same question is opened over a window four times wider at a slightly higher
priority. The narrow conclusion and the wide one are stored separately, so a
pattern that only appears at one scale stays visible as such.

An adapter must remove `deeper_analysis` from farmer-facing choices. If no other
option remains, it sends no question. The completed result may enter the next
informational bulletin. A person is asked to act only when the wider analysis
leaves a concrete observation or decision that cannot be supplied by the board.

## From understanding to anticipation

A confirmed relationship can be pointed forwards. Accepting
`forecast_from_relationship` on a `lagged_association` finding opens a
`relationship_forecast` question that watches the driver and, when it crosses
the 95th percentile of its own history, reports what that would point at and
when — carrying the relationship's lag, strength and sample as its reason.

Three guards keep it from becoming fortune-telling:

- **Founded only.** Below rho 0.5 or 60 observed days it stays an association
  and says so. Understanding is a legitimate place to stop.
- **Unusual only.** The 95th percentile of the driver's own history, because a
  threshold crossed one day in five produces a warning that means nothing.
- **In time only.** A projection whose day has already arrived is news about
  the past; it is not reported as a warning.

It is written as a projection of a relationship, never as a measurement of the
thing predicted, and the open question it asks is whether the response actually
rises — which only a look at the field can settle.

## Attending to what is missing

Every other analysis studies evidence that exists. `coverage_gaps` studies its
absence: it collects the questions the board has already framed and could not
run, groups them by the measurement each one needs, and reports the register
once — not once per blocked question.

```text
3 missing measurements. The most useful would be insect counts:
it would let me answer 2 questions I cannot answer now.
```

A gap describes the board's instruments, not the field, and adding a
measurement makes a question testable rather than making its answer positive.
The engine asks this of itself weekly, with no pack required.

## Confirming a hypothesis drafts a study

A pattern found in the record that produced it has been described, not
confirmed. The first option on a hypothesis is therefore `run_measurement_task`:
"shall I test this properly?" Accepting it writes a bounded task that re-runs
the same question weekly on data collected *after* the hypothesis was formed.

The draft is written to `task_drafts_dir` as `status: template`, which the
executor does not run. Promotion to `pending` is a human act. The skill name is
validated as an identifier and the repeat interval and iteration count are
clamped before anything reaches disk. The board proposes an experiment; it never
starts one.

## Drafting a model as a candidate skill

A published model may be written down as a skill candidate — but only with
sources attached and only after a person agrees. `draft_model_skill` writes a
`SKILL.md` under `task_drafts_dir/skill_candidates/` carrying `status: draft`,
`requires_validation: true`, its sources, and the checks it must pass. It is
not installed, not registered, and emits nothing.

The route refuses without a published source: a model nobody has written down
is a hypothesis, and this is for putting literature into a testable shape, not
for inventing agronomy. A disease model is not a sensor driver — its output
becomes treatment advice — so validation against confirmed local outcomes and
explicit human promotion stay separate acts, and product selection never comes
from such a skill alone.

## Built-in analyses

| Analysis | Question |
| --- | --- |
| `threshold_materiality` | Does the gap between a confirmed and an upper-bound estimate ever cross a decision threshold, and was it resolved anyway? |
| `ceiling_saturation` | Is a channel pinned at its range, or never reaching a criterion it keeps approaching? |
| `source_disagreement` | Do two sources that should agree actually agree? |
| `outcome_calibration` | Do this board's own alerts match the outcomes that came back? |
| `data_gap` | Did a source stop reporting, or thin out? |
| `level_shift` | Did the level of a series change beyond its own noise? |
| `neighbour_reports` | Do nearby reporters see something this board's own indicator does not? |
| `baseline_deviation` | Is the current period unlike the periods before it? |
| `lagged_association` | Does one series move before another, by a fixed number of days? |
| `coverage_gaps` | Which questions has the board framed that nothing here can measure? |
| `relationship_forecast` | A confirmed relationship's driver ran high — what does it point at, and when? |

All of them read either a JSONL journal or a local SQLite table, so any
experiment nora runs is already in a supported format.

Two combinations worth naming, because they are what a networked board is for:

- **Other boards.** `neighbour_reports` takes an event source carrying a time
  and a location, an origin, and the local indicator with its alert threshold.
  A confirmed report two kilometres away while the local model sits quiet is a
  raised prior and a cheap local check, never a confirmation. Vineyard Guard
  points it at `peer_signals`.
- **Weather.** `source_disagreement` between a forecast table and what the
  station later measured answers whether the forecast driving a risk projection
  can still be trusted. Vineyard Guard compares `weather_forecast_daily`
  against the observed daily temperature with a two-degree tolerance.

## Forming a hypothesis nobody wrote down

The analyses above answer questions somebody registered. `lagged_association`
is different: the board can propose a lead between two measured channels and
test it without a pack naming that relationship.

That is also where an autonomous researcher starts finding patterns in noise,
so every guard exists to make a negative result the easy outcome:

- the test runs on **first differences**, so two series that merely share a
  seasonal trend cannot produce a result;
- the effect must **persist in both halves** of the record with the same sign;
- the significance level is **corrected jointly for inferred clock windows and
  lags**, so trying more views of the record does not buy a result;
- a **sample floor** of 30 overlapping days, and a minimum effect size;
- a pair answered `not_material` **stays answered**, so a refuted relationship
  is never re-proposed.

Measured on synthetic series: 0 false positives in 200 trials of independent
noise, and 100% detection of a moderate real lead. It reports **precedence,
never causation** — a driver that leads a response may share a cause with it or
proxy for it, and the finding says so.

Pair discovery is budgeted with `max_new_pairs` (default two per cycle). A pack
normally exposes a database without declaring variables:

```python
"catalog_sources": lambda context: [{
    "kind": "sqlite_catalog",
    "path": "/path/to/domain.db",
}]
```

The engine discovers tables, parseable temporal axes, changing numerical
columns, and repeated entity dimensions from the values. Every inferred
channel can be either antecedent or response. For subdaily channels it derives
cyclic windows from observed clock coverage; the windows carry hour ranges, no
semantic labels. JSONL monitor channels enter by the same route. A measurement
that does not exist cannot generate a hypothesis: the engine never invents a
missing response merely to ask for a sensor.

## Sources

```json
{"kind": "journal", "path": "/tmp/monitors/grape_growth.jsonl"}
{"kind": "sqlite", "path": "/path/app.db", "table": "daily", "columns": ["a","b"], "time_column": "day"}
{"kind": "glob", "pattern": "/path/results/season_climate_*_*.json"}
{"kind": "skill", "name": "vineyard_season_climate", "params": {...}, "records_path": "field_reports"}
{"kind": "inline", "records": [{"timestamp": "...", "value": 1}]}
```

Table and column names are validated as identifiers, and a filter may only be a
single `column = ?` comparison. A skill is named, never given as a path, and is
resolved against the installed skill directories.

Any source may carry a `refresh` source that runs first:

```json
{"kind": "glob", "pattern": ".../season_climate_*.json",
 "refresh": {"kind": "skill", "name": "vineyard_season_climate", "timeout": 170,
             "params": {"mode": "report", "write_artifacts": true}}}
```

That is how a question keeps a skill's artifacts current before reading them,
and it is the preferred way to reuse work the board already knows how to do:
the season-climate skill computes the averages, the engine compares them. A
failed refresh is not fatal — a stale baseline is still a baseline.

A question backed by a skill should set its own `min_interval_seconds` in its
params. Reading a season of weather is a weekly job, not an hourly one.

## Writing a pack

A pack is one `pack.py` in any directory listed in `pack_dirs` (by default the
sibling skill directories, so installing a domain skill registers it):

```python
PACK = {
    "name": "my_domain",
    "journal_dirs": ["/tmp/monitors/my_domain"],
    "analyses": {"my_analysis": my_callable},
    "questions": declare_questions,             # optional
    "scanners": [scan_my_signals],              # optional
    "calibration_sources": calibration_sources, # optional, dict or callable
    "evidence_paths": evidence_paths,           # optional: files whose mtime
                                                # decides whether a cycle runs
}
```

`analyses` values are callables taking one context dict and returning a finding.
`questions` returns the questions the domain always cares about. A pack that
raises on import is reported and skipped: one broken domain must not stop the
board from researching the others.

## Budget, and staying quiet

One cycle is bounded by `max_questions`, `max_seconds`, `max_files` and
`max_lines`. Defaults are sized so a cycle can run hourly on a 256 MB board
without competing with sampling.

Flash is the scarcest resource on such a board, so a cycle that has nothing to
do costs nothing:

- before opening the database, the cycle fingerprints what it would read
  (journal and pack file mtimes and sizes, plus the feedback count). If that
  fingerprint is unchanged, it returns `status: skipped` having written
  nothing at all;
- `idle_recheck_seconds` (default six hours) still forces an occasional run,
  because some conclusions depend on elapsed time — a source that stopped
  reporting looks healthier the less often you look;
- a question the board already holds is not rewritten just because a scan saw
  the same shape again;
- a finding whose conclusion has not changed is neither updated nor appended
  to the evidence journal. A metric that only moves with the clock, such as
  `seconds_since_last_record`, does not count as a change.

The effect: a board where nothing is happening performs no writes per cycle,
and a repeated conclusion appears in the journal once rather than hourly.

## Running off the board

This skill needs no hardware: standard-library Python, local files only. It
runs unchanged on a laptop or a cloud VM. When no parameter is supplied, these
environment variables replace the board defaults:

| Variable | Parameter |
| --- | --- |
| `NORA_STATE_DIR` | `state_dir` |
| `NORA_JOURNAL_DIRS` | `journal_dirs` |
| `NORA_EVIDENCE_JOURNAL` | `evidence_journal` |
| `GOIDANICH_REPO` | `repo_path` |

An explicit parameter always wins. See `deploy/` for systemd, container, and
cloud instructions.

## Safety contract

- A finding is evidence about stored data, never an instruction.
- The engine sends no messages and performs no domain action.
- A refusal is an answer: it closes the question, it does not reschedule it.
- A watch executes only what a human already confirmed, and expires.
- Findings are appended to the nano-os-agent evidence journal so they are
  auditable through the same route as executor experiments.
