# Wine Fermentation Monitor

Wine fermentation is a perfect long-running experiment for the board: change is slow, many signals are cheap to measure, and alerts are only useful when they connect trends to batch context.

## What It Observes

- Alcohol-conversion proxies from fermentation activity trends.
- Temperature from sysfs, I2C, or attached probes.
- pH from an attached pH board or manually entered readings.
- Bubble or airlock activity from microphone and image cues.
- Turbidity, clarity, sedimentation, foam, and cap height from camera frames.
- Color drift during extraction or clearing.
- Stall, overheating, contamination, or overflow risk.

## Why It Is Powerful

The board cannot directly measure alcohol conversion from camera alone, but it can infer fermentation phase from multiple weak signals: bubble rate, temperature curve, turbidity clearing, elapsed time, foam/cap behavior, and optional hydrometer/Brix/pH input. picoClaw can reason over those trends without watching every sample.

## Chain

```text
periodic image + short audio + sensor read
-> bubble / airlock activity score
-> temperature and pH capture
-> turbidity and color index
-> estimate fermentation phase
-> infer alcohol-conversion progress from trend proxies
-> alert on stall, overheating, pH drift, or contamination cue
-> update knowledge graph
```

## Knowledge Graph Feedback

Instead of sending "temperature high", the board can update relationships:

```text
Batch_2026_A
  has_phase -> "active fermentation"
  has_temperature_trend -> "rising"
  has_bubble_rate -> "falling"
  has_pH_trend -> "stable"
  has_turbidity -> "high"
  has_risk -> "stuck fermentation candidate"
  evidence_pack -> "/tmp/evidence/batch_2026_a_042.json"
  recommended_action -> "increase sampling and request Brix reading"
```

This lets picoClaw ask useful questions:

- Which yeast strain had similar temperature/bubble behavior?
- Did a pH drift precede the stall risk?
- Which intervention improved previous batches?
- Should the board sample more often or ask for a manual Brix reading?

## Useful Skills

- `fermentation_phase_estimate`: lag/active/slow/complete phase from multimodal trends.
- `bubble_rate_from_audio`: airlock or bubbling rhythm from microphone.
- `bubble_rate_from_video`: visual airlock or surface bubble activity.
- `foam_cap_height`: visual foam/cap segmentation.
- `turbidity_index`: cloudiness and clearing estimate.
- `ph_temperature_probe`: attached pH/temperature sensors or manual input.
- `brix_manual_entry`: structured human-entered hydrometer/Brix readings.
- `fermentation_kg_update`: batch/trend/risk/action graph relationships.
- `fermentation_stall_detector`: learned stall-risk classifier.
- `batch_daily_summary`: daily trend summary and evidence links.

## Example Real Change

The board sees temperature rising above the preferred yeast range while bubble rate drops and turbidity remains high. Instead of sending a vague alert, it updates the batch knowledge graph with `risk -> stuck fermentation candidate`, attaches an evidence pack, and asks picoClaw whether to request a Brix/pH reading or change the monitoring interval.

If picoClaw later confirms this pattern, it can create and promote `fermentation_stall_detector`. Future batches get earlier, more specific alerts.
