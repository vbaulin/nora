# Automatic Lab Experiment Runner

nano-os-agent can run small physical experiments where the LLM designs the protocol but the board performs repeatable measurement.

## What It Observes

- Seed germination and early growth.
- Drying, curing, or evaporation.
- Liquid level and meniscus changes.
- Color reaction timing.
- Bubble activity from fermentation or chemical reactions.
- Crystal growth or corrosion over days.
- Well-plate or sample-grid color changes.
- Mold, contamination, turbidity, sedimentation, or phase separation.
- LED/UV exposure response, phototropism, and circadian plant movement.
- Temperature-dependent rate changes when paired with sysfs/I2C sensors.

## Why It Is Powerful

Lab work often needs regular observation, patience, and strict timing. The board can execute the protocol locally and keep structured data. picoClaw can redesign the next experiment from evidence instead of watching the current one.

## Chain

```text
load protocol YAML
-> capture sample tray on schedule
-> segment wells / samples
-> compute color, level, bubbles, motion
-> detect endpoint or plateau
-> write experiment journal
-> summarize outcome
```

## More Experiment Templates

### Germination Plate

```text
capture tray every 30 min
-> register seed positions
-> detect root/shoot emergence
-> estimate growth length
-> increase sampling when growth begins
-> daily germination report
```

Useful for comparing seed batches, light exposure, humidity, or substrate.

### Reaction Kinetics by Color

```text
start experiment timer
-> capture vial/well grid every N seconds
-> extract color curves
-> detect slope change or plateau
-> estimate endpoint time
-> adapt next sampling interval
```

Useful for low-cost chemistry, enzyme assays, pH indicators, and dye reactions.

### Fermentation Watcher

```text
periodic image + short audio
-> bubble activity score
-> foam height / liquid level
-> temperature snapshot
-> detect stall or overflow risk
```

Useful for yeast, kombucha, microbial cultures, and gas-producing reactions.

### Crystal / Corrosion Growth

```text
fixed-angle capture every hour
-> image registration
-> edge/texture change score
-> growth front estimate
-> anomaly pack for picoClaw
```

Useful where change is slow and a human would miss the important transition.

### Active Protocol Search

```text
observe current sample state
-> compare to preferred outcome
-> choose next perturbation: light, pump, wait, heat, mix
-> measure result
-> update belief about which perturbation works
```

This is where the board starts acting like an experimenter, not just a camera.

## Useful Skills

- `experiment_protocol_runner`: timed protocol execution.
- `sample_position_register`: learns fixed positions of cups/samples.
- `well_plate_reader`: extracts per-well color/brightness.
- `reaction_endpoint_detect`: detects plateau or endpoint.
- `liquid_level_estimate`: tracks meniscus height.
- `bubble_activity_score`: estimates fermentation or reaction activity.
- `daily_lab_report`: compresses all samples and anomalies.
- `turbidity_index`: measures cloudiness or sediment.
- `contamination_watch`: detects unexpected color/texture growth.
- `growth_length_estimate`: root/shoot/crystal front measurement.
- `adaptive_sampling_policy`: increases sampling near fast transitions.
- `active_protocol_policy`: chooses the next perturbation from local evidence.
- `multi_sample_comparator`: compares treatment/control groups.

## Example Real Change

A color reaction reaches endpoint much earlier than expected. picoClaw updates the next task to sample every minute near the expected transition instead of every ten minutes. The board has changed the experimental protocol from observed kinetics.

Another example: a fermentation monitor detects that bubble activity is falling while temperature is stable. picoClaw creates a draft `fermentation_stall_detector`, validates it against saved audio/image clips, and promotes it. Future experiments detect stalls without asking the LLM to inspect raw logs.
