---
title: Evidence Memory and Release Gates
summary: Preserve provenance, quarantine failed runs, and avoid turning temporal order into causality.
order: 4
eyebrow: Chapter 4
---

# Evidence Memory and Release Gates

A proactive system needs memory, but not every stored value has the same
epistemic status. nano-os-agent journals attempted experiments. Application
adapters maintain observations and confirmed facts. PicoClaw explains released
evidence. Chat history is not a truth source for board state.

## Evidence classes

| Class | Example | Permitted statement |
|---|---|---|
| Observation | A calibrated sensor read `31.2 C` at a timestamp | The sensor reported this value under the recorded conditions |
| Released experiment result | A focus-control task passed all declared checks | This run passed its checks |
| Human-confirmed fact | The operator confirmed a treatment or sample identity | The event was reported and confirmed |
| Public source | A paper or manual with URL and retrieval time | The source states or supports a candidate method |
| Proposal | Inspect a sample or test a sensor placement | This is a suggested next action, not an executed fact |

## Release gate

Field-related nano-os-agent results use a narrow release rule:

- **Passing and internally consistent:** retain as `observed_success` with the
  scope of that run.
- **Failed, partial, blocked, or step-inconsistent:** quarantine the result and
  exclude its measurements from operational advice.
- **Missing current application state:** create an internal refresh or
  investigation request rather than inventing a current value.

The gate limits what may influence downstream explanations. It does not erase
failure; failure remains valuable diagnostic evidence.

## Provenance

Every durable item should answer:

1. What subject or sample did this concern?
2. When was it observed or reported?
3. Which skill, task, sensor, person, or source produced it?
4. Which units, model version, and configuration applied?
5. Did release checks pass?
6. Was the item observed, confirmed, inferred, or proposed?

Without these fields, a numeric value may be precise but scientifically weak.

## Temporal association is not causality

Suppose a farmer confirms an operation and a later observation is clean. The
agent may store:

```json
{
  "relation": "observed_association",
  "operation_id": 41,
  "outcome_id": 57,
  "causal_claim": false
}
```

The sequence can guide a future question, but it does not establish that the
operation caused the outcome. Stronger claims require controls, replication,
or another defensible design.

## Staleness

Evidence also has a time boundary. A fresh dashboard, sensor snapshot, or task
result can answer a current question. Yesterday's value may remain valid
history, but it should not be silently reused as today's state. Application
adapters therefore define freshness and regeneration rules.

Next: [use released evidence to initiate a bounded dialogue](05-proactive-dialogue.md).
