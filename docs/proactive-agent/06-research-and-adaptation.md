---
title: Research the Evidence on Idle Time
summary: How the board raises its own questions, answers most of them alone, and interrupts a human only for the rest.
order: 6
eyebrow: Chapter 6
---

# Research the Evidence on Idle Time

A board that samples once an hour is idle for fifty-nine minutes. Those minutes
are enough to answer questions about data already on disk. This chapter is the
engine that spends them: `skills/research_agent`.

It is domain-neutral. It knows about questions, analyses, findings, verdicts
and watches, and nothing about what the numbers mean.

## The loop

![Signals and feedback become a question, a bounded analysis produces a finding, and the verdict decides who hears about it](../../assets/readme/research-loop.svg)

Three properties make this research rather than alerting:

- The question exists before the answer, and is stored with its provenance.
- The analysis reports what it *cannot* establish alongside what it can.
- A conclusion that changes no decision is a result, and stays silent.

## Where questions come from

**Signals.** A scan reads the tail of each monitor journal and looks for shapes
worth a closer look: a source that stopped reporting, a level that moved beyond
its own noise, a channel piling up against a limit. The scan concludes nothing;
it raises a question and hands it to an analysis.

**Human feedback.** Two refusals on the same subject are not stubbornness. They
are evidence that the board is asking the wrong question, or asking it too
often, so the engine opens a question about its own alerting threshold.

**Packs.** A domain declares the questions it always cares about. See
[chapter 8](08-vineyard-guard.md).

## The six shapes it looks for

Every analysis is a shape in the data. Learn the six pictures and you know what
the board can notice.

![Six analyses drawn as the data shape each one detects](../../assets/readme/analysis-shapes.svg)

| Analysis | Question it answers |
| --- | --- |
| `level_shift` | Did the level move beyond its own noise? |
| `ceiling_saturation` | Is a channel piling up against a limit? |
| `data_gap` | Did a source go quiet? |
| `threshold_materiality` | Did the uncertainty ever change a decision? |
| `source_disagreement` | Do two sources that should agree, agree? |
| `outcome_calibration` | Are the board's own alerts earning their interruptions? |
| `neighbour_reports` | Do nearby reporters see something this board does not? |

| `baseline_deviation` | Is the current period unlike the periods before it? |

Three of these are what a networked board with a weather history is for.
`neighbour_reports` reads confirmed reports from other boards with their
distance and asks whether the local indicator agrees — a confirmation two
kilometres away raises the prior here and earns one cheap local check, nothing
more. `source_disagreement` between a weather forecast and what the station
later measured answers whether the forecast driving a risk projection can still
be trusted. `baseline_deviation` asks the question a person actually asks about
weather: not "is it warm" but "is this season unlike the last several".

## Reusing a skill instead of reimplementing it

A board that already has a skill for seasonal averages should not have that
arithmetic written again inside an analysis. A source can name an installed
skill, or a glob of the artifacts a skill wrote, and any source may carry a
`refresh` that runs first:

```json
{"kind": "glob", "pattern": ".../results/season_climate_*_*.json",
 "refresh": {"kind": "skill", "name": "vineyard_season_climate",
             "params": {"mode": "report", "write_artifacts": true}}}
```

Vineyard Guard uses exactly this: `vineyard-season-climate` computes each
season's rainfall and accumulated heat and writes one artifact per year; the
engine reads those artifacts and compares this season against the median and
deviation of the previous ones. Five ordinary seasons and one drought produce
one finding, and five ordinary seasons produce none.

A skill-backed question sets its own `min_interval_seconds` — reading a season
of weather is a weekly job, not an hourly one.

Each reads a JSONL journal or a local SQLite table, so anything nora already
records is a valid input. Most domain questions turn out to be one of these six
wearing different words.

## A worked study

Take the quickstart journal from the [index](index.md) and ask one question
directly instead of waiting for the scan:

```bash
printf '%s' '{"mode":"investigate","state_dir":"/tmp/nora-demo/state","analysis":"level_shift","subject":"light_probe","params":{"source":{"kind":"journal","path":"/tmp/nora-demo/monitors/light_probe.jsonl"},"key":"temp_c"}}' | ./skills/research_agent/run.sh
```

```json
{"status": "success", "mode": "investigate",
 "summary": [{"subject": "light_probe", "analysis": "level_shift",
              "verdict": "not_material", "sample_size": 48}]}
```

`not_material` is the answer, and nobody is interrupted by it. The stored
finding still carries the numbers that produced it:

```bash
printf '%s' '{"mode":"findings","state_dir":"/tmp/nora-demo/state","limit":1}' | ./skills/research_agent/run.sh
```

The `metrics` object holds `median_before`, `median_after`, `shift`,
`within_half_deviation` and `shift_threshold`. Anyone can check the reasoning
without rerunning it.

### Why the spread is measured within each half

A shift detector that measures noise across the whole window is defeated by the
shift itself: the step inflates the very spread it is compared against, and a
real change scores as ordinary variation. The engine measures the deviation
inside each half separately, so a step between two stable halves is significant
no matter how large it is.

This is the kind of detail that decides whether an autonomous researcher is
useful or merely busy.

## Verdicts and silence

| Verdict | What happens |
| --- | --- |
| `material_unresolved` | Handed to an adapter, with options ordered by cost |
| `not_material` | Stored; the question is marked answered |
| `resolved_local` | Stored; the evidence already answered it |
| `insufficient_data` | Stored as an internal gap; never a human message |

An analysis that could not run is not a discovery. A board that lacks the data
to check something must not convert its blind spot into a request for
attention, budget, or hardware.

## Budget

One cycle is bounded by questions, seconds, files and lines:

```json
{"mode":"cycle","max_questions":3,"max_seconds":20,"max_files":12,"max_lines":400}
```

`tasks/029_autonomous_research_cycle.yaml` runs one every fifteen minutes and
journals the result. The defaults are sized so the research never competes with
sampling on a 256 MB board.

## Asking, and not insisting

A finding that reaches a human arrives with its numbers, with options ordered
by cost, and with "nothing for now" as a legitimate answer. The engine records
the reply:

```bash
printf '%s' '{"mode":"record_decision","state_dir":"/tmp/nora-demo/state","finding_id":1,"decision":"accepted","option_id":"check_source","watch":true,"note":"probe is capped at 100"}' | ./skills/research_agent/run.sh
```

An acceptance may arm a **watch**: a future action a human confirmed once. When
the same pattern returns, the watch fires and disarms. A refusal closes the
question for the season instead of rescheduling it, because "no" is an answer.

Hardware is never the first way to close a question, and never the only one. A
suggestion to buy something belongs at the end of a list whose first entry is
free, and it is not repeated after a refusal.

## Failure as diagnostic evidence

A failed or partial task run is quarantined from advice, but it can open a
narrow investigation:

```text
Observed failure:
  sensor skill returned no device identity after two bounded attempts

Research question:
  which SG2002 I2C bus and voltage constraints apply to this sensor family?

Next experiment:
  read-only bus discovery followed by identity-register validation
```

The original failure is preserved, and a web answer never becomes a local
success.

## When local evidence is not enough

An external search is for the question the local analysis could not settle, and
it asks the scientific question. "Is a 95% humidity threshold a validated
wetness proxy?" is research. "Which humidity sensors should I buy?" is
shopping. Source-attributed results become candidate evidence for review, never
instructions, product selections, or confirmed facts.

## Model learning remains separate

Application models have their own training data, fitted parameters, evaluation,
release status, and version. Neither a promoted skill nor an LLM explanation is
a trained scientific model, and neither is a finding. This distinction matters
when boards exchange model deltas or when a fallback model is used before
enough confirmed local labels exist.

Next: [run and extend a first experiment](07-run-an-experiment.md).
