# Microscope Timelapse Station

nano-os-agent can turn a small board-mounted microscope or macro imaging rig into an autonomous timelapse experiment station. The LLM defines the protocol and interpretation questions; the board executes repeated imaging, quality control, segmentation, journaling, and summary generation.

## What It Observes

- Cell, colony, crystal, droplet, or particle growth.
- Motility, aggregation, sedimentation, or phase separation.
- Focus drift and field-of-view drift.
- Illumination changes, condensation, bubbles, and dust artifacts.
- Treatment/control divergence over time.
- Endpoint transitions such as color, morphology, density, or motion plateaus.

## Why It Is Powerful

Microscope observations are often limited by attention rather than by instrumentation. A low-cost board can keep a fixed optical setup under continuous observation, reject bad frames, increase sampling near change points, and preserve compact evidence for later human or LLM review.

The core requirement is determinism: image capture, focus scoring, exposure normalization, segmentation, and journaling should run locally without asking the LLM to inspect every frame.

## Chain

```text
load microscope protocol
-> capture frame on schedule
-> check focus / illumination / field drift
-> segment target structures
-> compute growth, motion, density, or morphology metrics
-> adapt sampling interval near change points
-> write JSONL evidence and representative images
-> summarize experiment outcome
```

## Example Protocols

### Crystal Growth

```text
capture every 2-10 min
-> register field of view
-> segment crystal edges
-> estimate growth-front velocity
-> detect sudden nucleation events
-> summarize final morphology and growth curve
```

### Microbial Or Cell Motility

```text
capture short bursts every N minutes
-> stabilize frame
-> detect moving particles/cells
-> estimate speed and direction statistics
-> flag aggregation or motility loss
```

### Droplet Or Phase Separation

```text
capture frame every 30-120 s
-> segment droplets/domains
-> estimate size distribution
-> track coalescence or settling
-> detect plateau or instability
```

## Useful Skills

- `microscope_capture`: fixed camera capture with exposure metadata.
- `focus_quality_score`: Laplacian/contrast-based focus check.
- `illumination_normalize`: flat-field and brightness correction.
- `field_register`: estimate field-of-view drift.
- `object_segment`: threshold, contour, or learned segmentation.
- `growth_curve_estimate`: area/count/length over time.
- `motion_score`: frame-difference or particle-motion summary.
- `change_point_detect`: increase sampling near sharp transitions.
- `experiment_summary`: compress metrics and representative frames.

## Evidence Record

```json
{
  "timestamp": "2026-06-17T09:00:00+02:00",
  "experiment_id": "crystal_growth_03",
  "image_path": "/tmp/microscope/crystal_growth_03/frame_00042.png",
  "focus_score": 0.82,
  "illumination_ok": true,
  "object_count": 18,
  "total_area_px": 42130,
  "growth_rate_px_per_min": 34.7,
  "change_point": false
}
```

## Example Real Change

A crystal growth experiment shows a sudden increase in edge velocity after six hours. nano-os-agent increases capture frequency from every ten minutes to every minute, writes representative frames, and summarizes the transition. picoClaw then proposes the next experiment with a narrower sampling window around the inferred nucleation phase.
