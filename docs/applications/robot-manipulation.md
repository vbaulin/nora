# Closed-Loop Robot Manipulation

The board can act as a local perception and reflex layer for simple robotics. picoClaw specifies the goal; nano-os-agent handles the tight loop.

## What It Controls

- Pan/tilt camera alignment.
- Servo or PWM-controlled stages.
- Small grippers or dispensers.
- Valves, pumps, lights, and LEDs.
- Sample positioning and verification.
- Before/after action checks.
- Turntables, simple XY stages, feeders, gates, and shutters.
- Camera-guided calibration targets.
- Local stop conditions for safety and precision.

## Why It Is Powerful

Robot manipulation should not round-trip through an LLM for every correction. The board can see, move, verify, and retry locally. picoClaw only needs the final evidence or a failure summary.

## Chain

```text
detect target
-> compute visual offset
-> move servo/PWM
-> recapture
-> verify target centered or action completed
-> retry up to N times
-> journal final pose and evidence
```

## More Robot Templates

### Visual Servo Pan/Tilt

```text
capture
-> detect target centroid
-> compute error from center
-> move pan/tilt servo
-> recapture
-> stop when centered or confidence falls
```

Useful for tracking plant clusters, lab samples, machine gauges, or a moving object without waking picoClaw for every correction.

### Sample Dispenser Verification

```text
before image
-> actuate valve/pump/feeder
-> after image
-> estimate liquid drop, seed count, or object presence
-> retry or flag failure
```

Useful in automatic lab protocols where the board needs to verify that a physical action actually happened.

### Object Sorting Gate

```text
detect incoming object
-> classify locally with TPU or learned skill
-> actuate gate/servo
-> verify path changed
-> log class + decision + confidence
```

Useful for seeds, small parts, lab samples, or simple agricultural sorting.

### Camera-Guided Micro-Experiment Stage

```text
move stage to sample A
-> capture and measure
-> move to sample B
-> capture and measure
-> compare treatment/control
-> return to most uncertain sample
```

This turns a simple servo stage into a local experiment scheduler.

### Safe Manipulation Gate

```text
capture scene
-> check expected object and safe region
-> actuate only if confidence is high
-> verify no unexpected movement
-> stop on mismatch
```

This is important because the LLM should design the mission, not push motors blindly.

## Useful Skills

- `visual_servo_target`: target center and correction vector.
- `actuate_pwm_position`: servo/PWM pose command.
- `verify_action_effect`: before/after image comparison.
- `safe_actuation_gate`: blocks actuation unless scene matches expectation.
- `pick_point_estimator`: chooses grasp or interaction point.
- `calibrate_stage`: maps actuator positions to camera coordinates.
- `retry_motion_until_seen`: local closed-loop correction.
- `pump_or_valve_pulse`: short calibrated fluid actuation.
- `stage_scan_policy`: chooses which sample position to visit next.
- `object_sort_decision`: local class-to-actuator mapping.
- `actuator_health_check`: detects stuck servo, backlash, or no-op movement.
- `active_alignment_policy`: selects the next move that should reduce visual error fastest.

## Example Real Change

The board fails to center a grape cluster after two pan adjustments. It journals the offsets, picoClaw infers backlash in the servo, and creates a compensation skill. Future alignment commands include measured backlash correction.

Another example: a dispenser pulse is expected to add one drop but the after-image shows no level change. The board retries once, then logs a pump-failure evidence pack. picoClaw later updates the protocol to prime the pump before dosing.
