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
  -> only material_unresolved reaches a human, through an adapter
  -> the decision is recorded, and may arm a watch for next time
```

## Modes

- `cycle`: one budgeted idle cycle. Scan for new questions, investigate the
  oldest few, journal the findings. This is the mode a schedule should call.
- `scan`: raise questions from journals and feedback without investigating.
- `investigate`: run one question (`question_id`), one ad-hoc analysis
  (`analysis` + `params`), or the next few open questions.
- `questions` / `findings` / `reportable`: read stored state. `reportable`
  returns only open findings a human should see.
- `record_decision`: store `accepted`, `rejected`, `deferred` or `corrected`
  for a finding, with the chosen `option_id`. `watch=true` on an acceptance
  arms a watch. An adapter that delivered a finding elsewhere echoes the answer
  back through `engine.record_external_decision(subject, analysis, ...)`, so
  feedback collected over Telegram or a dashboard still counts.
- `arm_watch` / `watches`: manage confirmed future actions.
- `self_test`: report registry, packs, journals and stored counts.

## Verdicts

| Verdict | Meaning | Reaches a human |
| --- | --- | --- |
| `material_unresolved` | Real, decision-relevant, and not answerable from local evidence | Yes |
| `not_material` | Real, but it changed no decision | No |
| `resolved_local` | Already answered by evidence the board holds | No |
| `insufficient_data` | The analysis could not run | No |

An analysis that cannot run is an internal gap. It is never converted into a
request for hardware, budget, or attention.

## Offering to dig further

A material finding may carry the `deeper_analysis` option, which is the board
offering its own time rather than yours: accepting it opens the same question
again over a window four times wider, at a slightly higher priority, and later
cycles run it unattended. The narrow conclusion and the wide one are stored
separately, so a pattern that only appears at one scale stays visible as such.

An adapter that delivers findings should present this option in the reader's
language and pass `option_id` back with the decision.

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

## Sources

```json
{"kind": "journal", "path": "/tmp/monitors/grape_growth.jsonl"}
{"kind": "sqlite", "path": "/path/app.db", "table": "daily", "columns": ["a","b"], "time_column": "day"}
{"kind": "inline", "records": [{"timestamp": "...", "value": 1}]}
```

Table and column names are validated as identifiers; a filter may only be a
single `column = ?` comparison.

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
