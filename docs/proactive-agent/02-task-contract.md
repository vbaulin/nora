---
title: Tasks, Steps, and Journals
summary: Express experiments as inspectable YAML with expectations, retries, and local repetition.
order: 2
eyebrow: Chapter 2
---

# Tasks, Steps, and Journals

The task is nano-os-agent's unit of experimental intent. In
[`main.go`](https://github.com/vbaulin/nora/blob/main/main.go), `Task` contains
identity, priority, status, optional hypothesis linkage, success criteria,
steps, and subtasks. Each `Step` declares an action, parameters, timeout,
expectations, retry policy, failure policy, optional saved name, and optional
repeat configuration.

## Minimal task

```yaml
- id: tutorial_system_snapshot
  name: "Tutorial system snapshot"
  priority: 1
  status: pending
  steps:
    - id: read_system
      action: call_skill
      save_as: system
      parameters:
        skill_name: system_info
      expect:
        ram_total_mb: ">=1"
      timeout: 15
      max_retries: 1
      on_fail: block
```

This is more than a command wrapper. It states what operation is allowed, how
long it may run, what output must be present, what is retained, and what failure
means.

## Step semantics

| Field | Role |
|---|---|
| `action` | Native action such as `call_skill`, `capture_image`, or another registered executor path |
| `parameters` | Typed or structured inputs for the action |
| `expect` | Output checks that must pass for the step to pass |
| `timeout` | Maximum duration for one attempt |
| `max_retries` | Bounded recovery from transient failure |
| `on_fail` | Continue or block the remaining chain |
| `save_as` | Stable alias for use by later steps |
| `repeat` | Local interval, duration/iteration bound, journal, and failure behavior |

Later steps can reference earlier outputs with `${step_id.field}` or
`${save_as.field}`. This keeps data flow inside the task instead of copying
intermediate values through chat.

## Local repetition

```yaml
repeat:
  interval_sec: 300
  max_iterations: 288
  journal_path: /tmp/monitors/environmental_baseline.jsonl
  continue_on_fail: true
```

The example records one day of five-minute observations. Each iteration writes
a compact JSON object to the declared journal. A later summary skill can reduce
the series to extrema, trends, failures, and representative artifacts.

This is the cost-control mechanism: one task can collect hundreds of samples
without hundreds of LLM calls.

## Experiment journal

After a task, nano-os-agent records an `ExperimentEntry` with:

- task identity and optional hypothesis reference;
- metrics before and after execution;
- steps run and steps passed;
- duration and timestamp;
- a verdict and compact summary.

Task state and experiment evidence are different. State answers *what the
executor is doing now*. The journal answers *what was attempted and what
happened*.

## Template versus pending

Long-running examples should remain `status: template`. This makes them
discoverable without launching them automatically. An operator or PicoClaw
creates a deliberate pending copy when the experiment is ready to run.

Next: [turn repeated task logic into a reusable skill](03-skill-lifecycle.md).
