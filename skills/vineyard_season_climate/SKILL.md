---
name: vineyard-season-climate
description: Calculate observed vineyard weather statistics from the local Goidanich SQLite cache, including April-to-harvest and monthly precipitation, day/night temperature and humidity, extremes, dry spells, VPD, growing-degree days, Huglin index, cool-night index, recent preharvest conditions, and data completeness. Use for seasonal climate summaries, vintage comparisons, grape-ripening context, weather exposure, rainfall received by a field, or questions about whether weather can estimate grape sugar/Brix.
exec_type: shell
command: ./run.sh
input_format: stdin
output_format: json
timeout: 180
parameters:
  - name: mode
    type: string
    default: report
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: field
    type: string
  - name: season_year
    type: integer
  - name: start
    type: string
  - name: end
    type: string
  - name: harvest_date
    type: string
  - name: timezone
    type: string
    default: Europe/Madrid
  - name: huglin_k
    type: number
    default: 1.03
  - name: write_artifacts
    type: boolean
    default: true
  - name: brix_model_path
    type: string
returns:
  - status
  - field_reports
  - artifacts
  - send_text
---
# Vineyard Season Climate

Run `mode=report` for one configured field or every field. Read only observed
weather from `goidanich.db`; never merge forecast rows into received rainfall
or seasonal exposure.

The result includes:

- season and monthly rainfall, rain days, maximum daily rain and dry spells;
- mean/minimum/maximum, daily range, day/night temperature and heat events;
- day/night humidity, high-humidity duration and VPD;
- Winkler GDD10, Huglin heat accumulation and September cool-night index;
- the most recent or preharvest 30-day window;
- per-variable data coverage and a calibration-ready quality feature vector.

Use `mode=model_info` to return definitions without reading the database. Read
[references/metrics.md](references/metrics.md) before interpreting indices or
building a Brix calibration model.

## Period selection

Use explicit `start` and `end` when the user names a period. Otherwise start at
the field's `leaf_10cm_mm_dd` metadata or April 1 and stop at the explicit
harvest date, configured season end, or today for an ongoing season. Preserve
the returned period and coverage in the answer.

## Sugar and grape quality

Describe weather as ripening context, not measured grape composition. Weather
alone cannot identify Brix or final grape quality because vine water status,
yield, canopy, soil, irrigation, variety, phenology and management also affect
the result.

Return a numerical sugar estimate only when the skill finds an explicitly
validated, field-matched Brix model with complete coefficients, training count
and validation RMSE. Otherwise preserve `sugar_estimate.available=false` and
explain which field measurements are required for calibration.

## Output use

Answer from `field_reports` and `send_text`; do not recalculate statistics in
the LLM. JSON and Markdown artifacts are written under `results/` when
`write_artifacts=true`. Treat incomplete variable coverage as a limitation of
the corresponding statistic, not as zero rainfall or normal conditions.
