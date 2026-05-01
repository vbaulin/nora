# Scientific Reflexes

Scientific reflexes are small universal skills that make every application smarter. They are not tied to grapes, machines, or labs; they improve how the board decides when to observe, summarize, alert, or act.

## Core Reflexes

- `baseline_learn`: learn normal ranges for image, audio, and metrics.
- `change_point_detect`: detect when a trend meaningfully shifts.
- `anomaly_score`: compare current observation to baseline.
- `adaptive_interval`: sample less when stable, more when changing.
- `event_debounce`: avoid duplicate alerts.
- `confidence_gate`: block actions or alerts below evidence threshold.
- `power_budget_guard`: reduce work under high temperature or low memory.
- `evidence_pack`: bundle image, audio, metrics, and summary.
- `daily_summary`: compress JSONL into one report.
- `experiment_outcome_judge`: map raw metrics to keep/discard/partial.

## Why They Are Powerful

These skills give the board local judgment. picoClaw can ask for high-level behavior such as "watch carefully when things change" instead of writing a rigid interval forever.

## Chain

```text
observe
-> compare to baseline
-> detect change point
-> adapt interval or collect evidence pack
-> summarize locally
-> wake picoClaw only if useful
```

## Example Real Change

A lab experiment is stable for six hours, so `adaptive_interval` slows captures from every minute to every fifteen minutes. When `change_point_detect` sees a color shift, the board returns to high-frequency sampling and captures the reaction endpoint.

