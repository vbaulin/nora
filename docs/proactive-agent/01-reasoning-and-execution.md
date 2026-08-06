---
title: Reasoning and Deterministic Execution
summary: Put uncertain planning and physical control on opposite sides of an explicit contract.
order: 1
eyebrow: Chapter 1
---

# Reasoning and Deterministic Execution

An LLM is useful when the next question is uncertain: which measurement would
discriminate between two hypotheses, which existing capability matches a new
request, or which failed step deserves investigation. It is a poor process
supervisor for a camera, sensor, actuator, or week-long monitor.

nano-os-agent therefore begins with a boundary rather than a prompt.

```text
uncertain intent -> declared task -> deterministic execution -> evidence
```

## Three runtime roles

| Runtime | Owns | Does not own |
|---|---|---|
| PicoClaw | Intent interpretation, capability selection, explanation, and chat/Telegram interaction | Continuous hardware loops or unverified board facts |
| nano-os-agent | Task execution, retries, timeouts, expectations, metrics, journals, and MCP tools | Open-ended scientific interpretation |
| Research engine | Bounded analyses over recorded evidence, and the verdict each one supports | Domain meaning, message delivery, or any action |
| Application adapter | Domain observations, proposal rules, and confirmed domain events | Universal hardware control or unrestricted action |

Note where the research engine sits. It reasons about data, deterministically
and within a budget, which is exactly the part of "reasoning" that does not
need an LLM at all.

The distinction is implemented in the repository contracts
([AGENTS.md](https://github.com/vbaulin/nora/blob/main/AGENTS.md) and
[HARDWARE_BOUNDARY.md](https://github.com/vbaulin/nora/blob/main/HARDWARE_BOUNDARY.md)),
not merely described in this tutorial.

## Capability-first routing

Before answering a board question, PicoClaw should inspect registered skills,
current nano-os-agent tasks, and existing artifacts. A current structured
result outranks chat history. If no capability exists, PicoClaw may design a
draft skill or task, but the new route still passes through validation.

```mermaid
flowchart TD
    U["User or scheduled intent"] --> L["List skills and current tasks"]
    L --> F{"Matching capability exists?"}
    F -->|yes| C["Call skill, MCP tool, or task"]
    F -->|no| D["Create bounded draft"]
    D --> V["Validate and experiment"]
    V --> C
    C --> E["Read structured result and artifacts"]
    E --> A["Explain only released evidence"]
```

## The hardware boundary

Direct shell access may look expedient, but it bypasses the controls needed on
a constrained edge board. Camera initialization, NPU memory, I2C writes, and
repeated monitors require retries, memory limits, evidence capture, and a clear
owner.

Use this order:

1. An existing MCP tool for an immediate one-shot operation.
2. A task YAML for an experiment, repeated measurement, or monitor.
3. A registered skill for a reusable board capability.
4. A draft skill followed by validation and promotion.

The boundary is especially important after an error. A low-level failure is
evidence that a declared capability failed; it is not permission to replace the
task with unjournaled probing.

## Why this makes the system proactive

Autonomy does not require an LLM to remain awake. nano-os-agent can execute and
journal while PicoClaw is offline. A compact summary or released anomaly can
later wake the reasoning layer. The system is proactive because evidence can
initiate the next interaction, not because language controls the device every
second.

Next: [encode that deterministic work as a task](02-task-contract.md).
