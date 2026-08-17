# Autonomous Vineyard and Plant Research Station

The board becomes a low-cost plant science station when it watches the same target every day, keeps its own evidence, and only asks picoClaw for reasoning when trends change.

## What It Observes

- Grape cluster visibility and apparent size.
- Color transition from green to purple.
- Yellowing, browning, and leaf stress.
- Wet surface events after rain, dew, or irrigation.
- Shading and sun exposure during the day.
- Sudden changes caused by wind, pests, humans, or bad camera framing.
- Daily rainfall, solar energy, clearness, heat, vapour-pressure deficit, and
  day/night temperature and humidity from the field's weather record.
- Confirmed phenology, berry weight, Brix, titratable acidity, pH, crop load,
  harvest, and field operations when those measurements are available.

## Why It Is Powerful

A human does not need to check the vine every hour. The board can collect consistent evidence under the same camera angle, then summarize the growth curve. picoClaw can use the LLM for higher-level questions: "Is this stress?", "Should I watch more often?", "What skill should I learn next?"

## Chain

```text
hourly capture
-> TPU detection
-> color/ripeness/stress metrics
-> compare with previous day
-> append JSONL
-> summarize every 24h
-> ask picoClaw only on trend change
```

## Climate, Fruit Quality, and Harvest Timing

`vineyard-season-climate` writes 18 daily, unit-preserving environmental
channels per field. The generic research engine treats these channels as
environmental drivers and tests them, with bounded lags, against whatever
biological, disease, operation, image, and fruit-composition responses the
board has actually observed. The set of candidate relationships is discovered
from stored series; it is not a deterministic list of agronomic correlations.

The proactive adapter groups fields by cultivar and performs one internal
source search for each distinct variety. It stores source-attributed evidence
about phenology, thermal requirements, solar and water response, veraison, and
maturity criteria as a candidate prior shared by the relevant fields. It does
not ask the farmer to review papers and does not convert literature thresholds
directly into treatment or harvest instructions.

Weather can constrain a plausible ripening window, but an optimal harvest date
depends on the intended wine style and current fruit composition. A numerical
date therefore remains unavailable until dated phenology and serial local
measurements such as Brix, titratable acidity, pH, and berry weight support a
field-matched model with held-out error in days.

## Useful Skills

- `observe_scene`: camera + TPU + color analysis.
- `agri_color_index`: green/purple/yellow/brown ratios.
- `monitor_summary`: daily trend compression.
- `leaf_stress_score`: learned stress estimator.
- `dew_or_rain_event`: visual wetness plus environment cues.
- `growth_change_detector`: aligned daily image comparison.
- `shadow_map`: learns when the target is sunlit or shaded.

## Example Real Change

The monitor sees `yellow_ratio` rising for two mornings while `purple_ratio` stays flat. picoClaw asks the LLM for hypotheses, creates a draft `leaf_stress_score` skill, validates it on the saved images, and promotes it. The next monitoring task now measures stress directly instead of only color.
