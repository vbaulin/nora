---
title: Let Evidence Start the Conversation
summary: Send one useful question from a new observation and connect an ordinary-language answer to the right experiment.
order: 5
eyebrow: Chapter 5
---

# Let Evidence Start the Conversation

The proactive adapter converts released evidence into an interaction. It does
not replace the scientific model, task engine, or domain-specific write route.

The reference implementation is
[`proactive-field-agent`](https://github.com/vbaulin/nora/tree/main/skills/proactive_field_agent).
Its loop is deliberately bounded:

```text
observe -> compare -> propose one next step -> wait -> record decision
```

## What a useful question needs

A proactive application should make these objects explicit:

1. **Subject:** instrument, sample, batch, machine, field, or experimental unit.
2. **Observation:** current measurement with time, source, and units.
3. **Memory:** released observations and confirmed facts for that subject.
4. **Rule:** declared condition that makes a question useful.
5. **Proposal:** one bounded next action or clarification.
6. **Decision:** acceptance, rejection, deferral, or correction.
7. **Outcome:** a later confirmed observation, stored without automatic causal
   interpretation.

This model generalizes beyond farming. A microscope can propose a focus check;
a fermenter can ask whether a sample was taken; a machine monitor can request a
bearing inspection.

## How the reference companion processes a reply

| Mode | Purpose |
|---|---|
| `observe` | Ingest current evidence without creating proposals |
| `tick` | Observe and create at most one new proposal per subject |
| `status` | Return profiles, evidence, pending proposals, and research queue |
| `next_proposal` | Select the highest-priority pending proposal |
| `proposal_context` | Resolve a reply to one proposal without writing |
| `record_decision` | Store an explicit accepted/rejected/deferred/corrected decision |
| `draft_operation` | Structure a general operation and identify missing fields |
| `record_operation` | Write only a complete, explicitly confirmed operation |
| `notify` | Package an existing proposal through the normal notification route |

## Give every open question a stable reference

Farmer-facing proposals include an identifier such as `PF-12`. A short reply
can then be resolved to the exact field, disease, or operation follow-up that
created the question.

```text
Board: PF-12 - Please inspect the north field for compatible symptoms.
Human: PF-12: no symptoms on inspected leaves.
```

The first processing step is read-only `proposal_context`. If it resolves one
subject and one domain route, the domain capture skill prepares a structured
draft. Only an explicit second confirmation writes the result.

## Ask when the subject is ambiguous

When a message could refer to more than one field, sample, or operation, the
correct result is a clarification question. Guessing creates false evidence.

For example:

```text
Human: I applied sulfur yesterday.
Agent: Which field, which product/code, dose per hectare, treated area, and
       application method should I record?
```

The system can understand informal language while preserving a deliberate
confirmation step. Language interpretation drafts the structure; confirmation
authorizes persistence.

## Protect the operator's attention

Proactivity should not become message flooding. The reference adapter:

- creates no more than one new proposal per field per tick;
- suppresses a proactive message already covered by the daily disease report;
- preserves the proposal in evidence memory even when delivery is suppressed;
- attaches only artifacts belonging to the relevant alert disease;
- never treats an accepted proposal as proof that an operation occurred.

## Investigate locally before asking

Everything above describes how to ask well. The stronger discipline is to ask
rarely, because the board answered the question itself. A raw threshold
crossing is not yet a reason to interrupt anyone: the next chapter shows how
the same evidence is investigated first, and how a conclusion that changes no
decision stays silent.

Next: [research the evidence on idle time](06-research-and-adaptation.md).
