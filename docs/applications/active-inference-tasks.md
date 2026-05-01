# Active Inference Tasks

Yes, the board can run active-inference-style tasks. The practical version is a local loop:

```text
observe -> update belief -> score possible actions -> act -> observe again
```

picoClaw defines the goal, preferred observations, action set, and policy constraints. nano-os-agent runs the loop deterministically and journals belief/action/outcome rows.

## What "Active Inference" Means Here

For this project, active inference does not mean a giant neural model on the board. It means the board keeps a small belief state and chooses actions that reduce uncertainty or move the world toward preferred observations.

Example belief state:

```json
{
  "target_centered": 0.42,
  "sample_reacted": 0.10,
  "liquid_level_ok": 0.77,
  "camera_framing_good": 0.66
}
```

Example action set:

```json
[
  {"action": "wait", "cost": 0.01},
  {"action": "capture_closeup", "cost": 0.10},
  {"action": "move_stage_left", "cost": 0.20},
  {"action": "pulse_pump", "cost": 0.30}
]
```

The board chooses the action with the best expected local value: reduce uncertainty, improve target state, avoid unsafe actuation, and respect power/time cost.

## Why It Fits nano-os-agent

- The loop is local and fast.
- It does not need an LLM at every step.
- It can be bounded by retry limits, confidence gates, and safety checks.
- It produces structured evidence for picoClaw.
- picoClaw can redesign the model or policy after reading summaries.

## Lab Example: Find Reaction Endpoint

```text
belief: reaction endpoint likely soon, but exact time uncertain
preferred observation: endpoint detected with high confidence
actions: wait 30s, wait 5min, capture closeup, increase light, stop experiment

loop:
  capture sample
  update color-curve belief
  if slope is high: sample more often
  if plateau is likely: capture closeup
  if endpoint confidence > threshold: stop and summarize
```

The board changes sampling frequency because its belief changed. picoClaw only sees the endpoint summary unless something fails.

## Robotics Example: Center A Target

```text
belief: target x/y offset and confidence
preferred observation: target centered, confidence high
actions: move left/right/up/down, zoom/crop, stop

loop:
  capture
  detect target
  update offset belief
  choose smallest safe movement expected to reduce error
  actuate
  verify after-image
```

This is active inference as a local reflex: choose actions to make observations match the preferred state.

## Environmental Example: Diagnose An Event

```text
belief: sound was wind / animal / machine / human
preferred observation: enough evidence to classify event
actions: capture image, record more audio, scan I2C, wait, summarize

loop:
  audio trigger
  update event belief
  choose evidence-gathering action
  stop when confidence is high or budget is exhausted
```

## Useful Skills

- `belief_state_update`: updates a small JSON belief from observation metrics.
- `policy_score`: scores candidate actions by expected information gain, goal progress, and cost.
- `active_inference_loop`: runs observe/update/act until stop condition.
- `preferred_observation_check`: tests whether the current state satisfies the goal.
- `safe_action_filter`: removes unsafe or low-confidence actions.
- `belief_journal_summary`: summarizes how beliefs changed over the task.

## Task Shape

```yaml
- id: active_center_target
  name: "Center target with active inference"
  priority: 8
  status: pending
  steps:
    - id: active_loop
      action: call_skill
      parameters:
        skill_name: active_inference_loop
        belief_path: /tmp/beliefs/target_centering.json
        action_set: /root/policies/pan_tilt_actions.json
        preferred_state:
          target_centered: 0.9
          camera_framing_good: 0.8
        max_steps: 12
        journal_path: /tmp/monitors/active_centering.jsonl
      expect:
        status: success
```

## Important Constraint

The LLM should not be inside the fast control loop. picoClaw should define or revise the model, then nano-os-agent should execute the loop with strict local limits. That keeps the board responsive, safe, and cheap to run.

