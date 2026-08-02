---
title: Research, Failure, and Adaptation
summary: Use attributed sources and failed experiments to design the next test, not to bypass validation.
order: 6
eyebrow: Chapter 6
---

# Research, Failure, and Adaptation

An autonomous experiment station eventually encounters an unknown sensor, a
failed protocol, or an observation not covered by the current skill set. The
safe response is not to broaden authority. It is to create a bounded research
question and retain the resulting sources as candidate evidence.

## Research route

The proactive adapter separates four stages:

1. `next_research` returns one queued question.
2. `research` performs one bounded search through a configured provider.
3. `ingest_research` stores externally collected results with URLs and source
   metadata.
4. A `research_review` proposal asks whether the candidate should be compared
   with the local problem.

Search snippets never become confirmed facts, product selections, doses, or
hardware operations by themselves.

## Failure as diagnostic evidence

A failed or partial nano-os-agent experiment is quarantined from advice, but it
can create an internal investigation. The investigation should be narrow:

```text
Observed failure:
  sensor skill returned no device identity after two bounded attempts

Research question:
  which SG2002 I2C bus and voltage constraints apply to this sensor family?

Next experiment:
  read-only bus discovery followed by identity-register validation
```

The process preserves the original failure and prevents a web answer from being
misreported as a local success.

## Learning a sensor skill

A reasonable skill-learning sequence is:

1. Inspect existing hardware capabilities and task history.
2. Read the sensor datasheet and board electrical constraints.
3. Create a read-only draft skill with a structured output contract.
4. Validate device identity and plausible ranges.
5. Repeat under known conditions and record artifacts.
6. Promote only after declared checks pass.
7. Add the promoted skill to a monitor task.
8. Revalidate after wiring, firmware, or hardware changes.

This is how the system may discover and use additional hardware without making
uncontrolled bus writes.

## Protocol adaptation

Adaptation may change *when* or *what* to measure within declared bounds. A
microscope monitor can sample faster after a registered change point. A machine
monitor can add an audio capture after vibration drift. The journal must record
the trigger, previous protocol, revised protocol, and eventual verdict.

## Model learning remains separate

Application models have their own training data, fitted parameters, evaluation,
release status, and version. Neither a promoted skill nor an LLM explanation is
a trained scientific model. This distinction matters when boards exchange
model deltas or when a fallback model is used before enough confirmed local
labels exist.

Next: [run the platform and extend one experiment](07-run-an-experiment.md).
