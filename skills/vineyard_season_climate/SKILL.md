---
name: vineyard-season-climate
description: Calculate observed vineyard weather statistics from the local Goidanich SQLite cache, including rainfall, solar exposure, day/night temperature and humidity, extremes, dry spells, VPD, growing-degree days, Huglin index, cool-night index, recent preharvest conditions, and data completeness. Use for seasonal climate summaries, vintage comparisons, grape and wine quality context, rainfall or radiation received by a field, and evidence-based questions about phenology, berry sugar/Brix, maturity, or harvest timing.
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
  - name: fetch_history
    type: boolean
    default: true
  - name: history_timeout
    type: integer
    default: 30
returns:
  - status
  - field_reports
  - artifacts
  - send_text
  - research_metrics_written
---
# Vineyard Season Climate

Run `mode=report` for one configured field or every field. Read only observed
weather from `goidanich.db`; never merge forecast rows into received rainfall
or seasonal exposure.

The result includes:

- season and monthly rainfall, rain days, maximum daily rain and dry spells;
- matched comparisons against the preceding 30 days and the same calendar
  window one year earlier, each carrying source-specific coverage so sparse
  history is omitted rather than interpreted;
- mean/minimum/maximum, daily range, day/night temperature and heat events;
- day/night humidity, high-humidity duration and VPD;
- measured global solar irradiation and explicitly defined high-solar days;
- Winkler GDD10, Huglin heat accumulation and September cool-night index;
- the most recent or preharvest 30-day window;
- per-variable data coverage and a calibration-ready quality feature vector;
- `harvest_readiness`, which states whether local evidence can support a date;
- compact observed day-level weather history in `season_climate_metrics`,
  discoverable by the domain-neutral autonomous research engine; cumulative
seasonal summaries remain in the JSON and Markdown artifacts.

Comparison windows first use `meteo_raw`. When coverage is incomplete and
`fetch_history=true`, the skill calls the board's existing Meteocat/XEMA
observed-history loader and inserts only the missing weather rows. It does not
run a disease model during this retrieval. Network or archive failure is stored
under `history_retrieval`; the current report still succeeds and simply omits
unsupported comparisons.

Use `mode=model_info` to return definitions without reading the database. Read
[references/metrics.md](references/metrics.md) before interpreting indices or
building a Brix calibration model. Read
[references/harvest_evidence.md](references/harvest_evidence.md) before adding a
phenology or harvest-date model.

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

## Phenology and harvest timing

The skill may use variety-specific literature as a candidate prior, never as a
field instruction. A transferable harvest model must report its cultivar and
site population, training sample count, held-out error in days, phenological
stage definitions, maturity target, and the local measurements used for the
current field.

Keep `harvest_readiness.available=false` until dated phenology, serial berry
sugar, titratable acidity, pH, berry weight or crop-load context, and intended
wine style are available. Weather can constrain a maturity window; it cannot
define the optimum composition by itself.

## Output use

Answer from `field_reports` and `send_text`; do not recalculate statistics in
the LLM. JSON and Markdown artifacts are written under `results/` when
`write_artifacts=true`. Treat incomplete variable coverage as a limitation of
the corresponding statistic, not as zero rainfall or normal conditions.
