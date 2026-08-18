---
title: Turn a Question into a Repeatable Experiment
summary: Describe an observation once, then let Nora repeat it with known limits and a readable notebook.
order: 2
eyebrow: Chapter 2
---

# Turn a Question into a Repeatable Experiment

A task turns "observe this subject" into a method another person can inspect
and rerun. It states the operation, required result, time limit, recovery from
temporary failure, and where the evidence should be kept.

## Describe one observation

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

## What each field gives you

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

## Leave it observing

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

## Return to a scientific notebook

After a task, nano-os-agent records an `ExperimentEntry` with:

- task identity and optional hypothesis reference;
- metrics before and after execution;
- steps run and steps passed;
- duration and timestamp;
- a verdict and compact summary.

Task state and experiment evidence are different. State answers *what the
executor is doing now*. The journal answers *what was attempted and what
happened*.

## Keep examples inactive until they are ready

Long-running examples should remain `status: template`. This makes them
discoverable without launching them automatically. An operator or PicoClaw
creates a deliberate pending copy when the experiment is ready to run.

Next: [teach Nora a reusable instrument capability](03-skill-lifecycle.md).
