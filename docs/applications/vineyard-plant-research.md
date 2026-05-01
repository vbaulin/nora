# Autonomous Vineyard and Plant Research Station

The board becomes a low-cost plant science station when it watches the same target every day, keeps its own evidence, and only asks picoClaw for reasoning when trends change.

## What It Observes

- Grape cluster visibility and apparent size.
- Color transition from green to purple.
- Yellowing, browning, and leaf stress.
- Wet surface events after rain, dew, or irrigation.
- Shading and sun exposure during the day.
- Sudden changes caused by wind, pests, humans, or bad camera framing.

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

