---
title: Build a Proactive Scientific Agent
summary: A code-guided tutorial from deterministic task execution to evidence-based human dialogue.
order: 0
eyebrow: nano-os-agent tutorial
---

# Build a Proactive Scientific Agent

This tutorial explains how PicoClaw and nano-os-agent turn a small edge board
into a scientific companion that can observe autonomously, retain evidence,
and ask a useful question when the evidence changes.

The architecture does not make an LLM responsible for continuous hardware
control. Reasoning selects or designs a bounded capability. A deterministic
executor performs the experiment. Release checks decide what may enter evidence
memory. A proactive adapter can then propose one next action, which still
requires confirmation when it has consequences.

<picture>
  <source media="(max-width: 560px)" srcset="../../assets/readme/evidence-loop-mobile.svg">
  <img src="../../assets/readme/evidence-loop.svg" alt="Evidence-gated proactive experiment loop">
</picture>

## Core abstractions

The chapter order follows the dependency structure of the codebase rather than
the directory tree.

| Abstraction | Question it answers |
|---|---|
| Reasoning/execution boundary | Which decisions belong to an LLM, and which belong to a deterministic runtime? |
| Task contract | How is an experiment made explicit, repeatable, and time-bounded? |
| Skill lifecycle | How does a new capability become trusted for unattended use? |
| Evidence release | Which results may become current facts, and which remain quarantined? |
| Proactive dialogue | How can new evidence initiate a precise human interaction without silently acting? |
| Research and adaptation | How can public sources and failed experiments guide the next test without becoming instructions? |
| Experimental operation | How do you build, execute, inspect, and extend a first task? |
| Application adapter | How does a domain such as Vineyard Guard connect without defining the universal runtime? |

## Learning path

1. [Separate reasoning from execution](01-reasoning-and-execution.md).
2. [Encode an experiment as a task](02-task-contract.md).
3. [Validate and promote reusable skills](03-skill-lifecycle.md).
4. [Release evidence without overstating it](04-evidence-release.md).
5. [Turn a change into one confirmable proposal](05-proactive-dialogue.md).
6. [Use research and failed runs as bounded inputs](06-research-and-adaptation.md).
7. [Run and extend a first experiment](07-run-an-experiment.md).
8. [Study Vineyard Guard as a complete adapter](08-vineyard-guard.md).

## What learning means

This codebase uses *learning* for several distinct processes. They should not
be collapsed into one claim.

| Process | Durable output | What it does not prove |
|---|---|---|
| Evidence memory | Timestamped observations, artifacts, and provenance | Why an observation occurred |
| Protocol adaptation | A bounded change to sampling or a next test | That the revised protocol is universally better |
| Skill learning | A validated and promoted capability | That every future run will pass |
| Model learning | Versioned fitted parameters and evaluation evidence | That an LLM explanation is a trained model |
| Human correction | A confirmed label, operation, or outcome | Causality between an operation and later state |

The rest of the tutorial keeps these meanings explicit.

## Method note

The chapter map uses the abstraction-first, relationship-first structure of
[PocketFlow Tutorial Codebase Knowledge](https://github.com/The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge).
The text was not produced by an unattended codebase generator: every runtime
claim is checked against this repository's task engine, skill contracts,
proactive adapter, and operator documentation.
