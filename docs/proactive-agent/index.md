---
title: Build an Autonomous Research Agent
summary: A code-guided tutorial for turning an idle edge board into an instrument that asks its own questions and answers most of them alone.
order: 0
eyebrow: nora tutorial
---

# Build an Autonomous Research Agent

nora runs experiments on small hardware and keeps the evidence honest. It is
not a vineyard product, a camera product, or a chatbot. It is a research
implementer: you describe an experiment, it runs it deterministically, and it
studies what came back.

The domain is yours. A vineyard board and a bench rig with a light sensor run
the same engine and differ only in configuration.

## The whole idea in one picture

A board that samples once an hour is idle for fifty-nine minutes. nora spends a
few of those seconds reading what it already recorded, and speaks up only when
something is both real and worth your time.

![The research loop: signals and feedback become a question, a bounded analysis produces a finding, and the verdict decides who hears about it](../../assets/readme/research-loop.svg)

Most of what it finds, it keeps to itself. That is the feature.

## Try it in sixty seconds

The research engine is standard-library Python, so the core loop runs on your
laptop with no board and no install. Clone the repository, then create a
journal that looks like something a sensor task would have written:

```bash
mkdir -p /tmp/nora-demo/monitors && python3 - <<'PY'
import json, datetime as dt, random
random.seed(1)
now = dt.datetime.now(dt.timezone.utc)
rows = [
    {
        "timestamp": (now - dt.timedelta(minutes=(48 - i) * 30)).isoformat(),
        "lux": min(100.0, round(random.gauss(86, 15), 1)),
        "temp_c": round(21 + random.gauss(0, 0.4), 2),
    }
    for i in range(48)
]
open("/tmp/nora-demo/monitors/light_probe.jsonl", "w").write(
    "\n".join(json.dumps(row) for row in rows))
PY
```

Now let the board research it:

```bash
printf '%s' '{"mode":"cycle","state_dir":"/tmp/nora-demo/state","journal_dirs":"/tmp/nora-demo/monitors","evidence_journal":"/tmp/nora-demo/experiments.jsonl"}' | ./skills/research_agent/run.sh
```

```json
{"status": "success", "mode": "cycle",
 "raised": ["lux piles up against 100 instead of passing it"],
 "investigated": [{"subject": "light_probe", "analysis": "ceiling_saturation",
                   "verdict": "material_unresolved", "sample_size": 48,
                   "open_question": "whether the channel is clipping at its range"}],
 "safety": "Findings are evidence about stored data. No action was taken and no message was sent."}
```

Nobody told it to look at `lux`. It read the journal, noticed that the values
pile up against 100 instead of passing it, checked whether that pile-up is a
real wall or just the top of a range, and produced a finding it cannot settle
alone. `temp_c` varied normally, so it produced nothing — which is most of the
job.

## Why it works this way

An unattended board has a great deal of time and very little to say. Two easy
failure modes follow: it stays silent until someone thinks to ask, or it
reports every threshold crossing and gets muted. Neither is research.

Four verdicts decide who hears about a finding:

| Verdict | Meaning | Reaches a human |
| --- | --- | --- |
| `material_unresolved` | Real, decision-relevant, unanswerable from local evidence | Yes |
| `not_material` | Real, but it changed no decision | No |
| `resolved_local` | Already answered by evidence on the board | No |
| `insufficient_data` | The analysis could not run | No |

The last row is the one that keeps an agent honest. A board that cannot check
something has not discovered anything, and must not turn its own blind spot
into a request for attention or hardware.

## Core abstractions

The chapter order follows the dependency structure of the code, not the
directory tree.

| Abstraction | Question it answers |
|---|---|
| Reasoning/execution boundary | Which decisions belong to an LLM, and which to a deterministic runtime? |
| Task contract | How is an experiment made explicit, repeatable, and time-bounded? |
| Skill lifecycle | How does a new capability become trusted for unattended use? |
| Evidence release | Which results may become current facts, and which stay quarantined? |
| Proactive dialogue | How does new evidence start a precise human interaction without acting? |
| Autonomous research | How does the board use idle time to answer its own questions? |
| Experimental operation | How do you run, inspect, and extend a first experiment? |
| Domain packs | How does a field such as viticulture plug in without defining the runtime? |

## Learning path

1. [Separate reasoning from execution](01-reasoning-and-execution.md) — why an
   LLM must not hold the sampling loop.
2. [Encode an experiment as a task](02-task-contract.md) — YAML steps,
   repeats, journals.
3. [Validate and promote reusable skills](03-skill-lifecycle.md) — how a new
   capability earns unattended use.
4. [Release evidence without overstating it](04-evidence-release.md) — the
   difference between a reading and a fact.
5. [Turn a change into one confirmable proposal](05-proactive-dialogue.md) —
   asking a human well, and rarely.
6. [Research the evidence on idle time](06-research-and-adaptation.md) — the
   engine, the analyses, and a worked study.
7. [Run and extend a first experiment](07-run-an-experiment.md) — laptop first,
   then hardware.
8. [Adapt it to your own domain](08-vineyard-guard.md) — write a pack; read the
   vineyard one as a complete example.

## What learning means

This codebase uses *learning* for several distinct processes. They should not
be collapsed into one claim.

| Process | Durable output | What it does not prove |
|---|---|---|
| Evidence memory | Timestamped observations, artifacts, provenance | Why an observation occurred |
| Autonomous research | A finding with a verdict and its limitations | That the finding generalizes beyond the window |
| Protocol adaptation | A bounded change to sampling or a next test | That the revised protocol is universally better |
| Skill learning | A validated and promoted capability | That every future run will pass |
| Model learning | Versioned fitted parameters and evaluation evidence | That an LLM explanation is a trained model |
| Human correction | A confirmed label, operation, or outcome | Causality between an action and a later state |

The rest of the tutorial keeps these meanings explicit.

## Method note

The chapter map uses the abstraction-first, relationship-first structure of
[PocketFlow Tutorial Codebase Knowledge](https://github.com/The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge).
The text was not produced by an unattended codebase generator: every runtime
claim is checked against this repository's task engine, skill contracts,
research engine, and operator documentation, and every command in the tutorial
was executed against the current tree.
