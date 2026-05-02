# Petri Dish Colony Counting

Petri dish monitoring turns the board into a small microbiology imaging station. It can count colonies, track growth curves, compare treatment/control plates, and flag contamination candidates.

## What It Observes

- Colony count over time.
- Colony area distribution.
- Radial expansion rate.
- Color, opacity, or morphology changes.
- Merge and overlap events.
- Contamination candidates outside expected morphology.
- Growth inhibition zones around antimicrobial disks or treatments.
- Divergence between treatment and control plates.

## Why It Is Powerful

Microbiology often needs repeated consistent imaging. The board can keep the camera fixed, capture at intervals, segment colonies, and wake picoClaw only when a plate diverges from control or crosses a contamination threshold.

## Chain

```text
fixed-angle plate capture every 15-60 min
-> detect dish circle and agar region
-> normalize lighting / crop plate
-> segment colonies
-> count colonies and estimate area
-> track colony expansion over time
-> detect contamination or unexpected morphology
-> summarize growth curves per plate
```

## Treatment / Control Workflow

```text
register plate positions
-> capture all plates on schedule
-> compute colony count and area per plate
-> compare treatment against control
-> detect inhibition or accelerated growth
-> write growth graph and evidence pack
```

This supports antibiotic disk diffusion, media comparisons, contamination checks, and growth-rate experiments.

## Useful Skills

- `plate_register`: finds plate circle and stable crop.
- `agar_region_segment`: masks non-agar background.
- `petri_colony_counter`: colony segmentation and count.
- `colony_growth_curve`: colony area and expansion over time.
- `colony_morphology_score`: color, edge, opacity, circularity.
- `inhibition_zone_measure`: clear zone around treatment disks.
- `plate_contamination_detector`: flags unexpected color, fuzz, shape, or spread.
- `treatment_control_compare`: compares growth curves across plates.
- `plate_kg_update`: writes plate/sample/treatment/outcome relationships.

## Knowledge Graph Feedback

```text
Plate_A3
  belongs_to -> Experiment_17
  has_treatment -> "low-dose antimicrobial"
  colony_count_t24 -> 42
  colony_area_delta -> "slower_than_control"
  has_inhibition_zone_mm -> 6.2
  has_risk -> "possible contaminant colony"
  evidence_pack -> "/tmp/evidence/plate_a3_t24.json"
```

picoClaw can then ask which treatment slowed growth, which plates are contaminated, or which colony morphology deserves a new learned classifier.

## Example Real Change

A treatment plate shows delayed colony expansion compared with control. picoClaw creates a `growth_inhibition_score` skill, validates it on saved plate images, and promotes it. Future plate experiments report inhibition curves automatically instead of raw colony counts.
