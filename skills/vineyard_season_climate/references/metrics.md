# Metric definitions

Use the board's observed hourly cache. Do not combine forecasts with observed
season totals.

## Water exposure

- **Seasonal and monthly rain:** sum precipitation variable 35 over the stated
  period.
- **Rain day:** daily total at least 1 mm.
- **Substantial rain day:** daily total at least 10 mm.
- **Dry spell:** consecutive days with less than 1 mm; a missing precipitation
  day interrupts the sequence.

## Temperature and humidity

- Calculate mean, minimum and maximum temperature from hourly observations.
- Separate day and night using calculated solar elevation at the field
  coordinates. Solar elevation above zero is classified as day.
- Report daily heat events, tropical nights, frost nights, relative-humidity
  duration and vapour-pressure deficit.

## Bioclimatic indices

- **Winkler growing-degree days:** `sum(max(0, Tmean - 10 C))`.
- **Huglin index:** April-September sum of
  `max(0, ((Tmean - 10) + (Tmax - 10))/2) * k`. The default latitude
  coefficient is 1.03 and can be overridden.
- **Cool-night index:** mean September daily minimum temperature when September
  observations are available.

Indices calculated before the end of the season are partial accumulations.
Preserve the stated period and data-coverage fields in every interpretation.

## Grape composition

Weather affects berry growth, water balance, ripening rate, acid respiration
and disease microclimate, but it does not uniquely determine soluble solids.
Do not convert heat or rainfall directly into Brix.

The skill may emit Brix only when a field-matched JSON model:

1. is explicitly marked `validated: true`;
2. supplies coefficients for every declared climate feature;
3. reports its training observation count and validation RMSE; and
4. matches the requested field identity.

Without that model, return the climate feature vector for later calibration and
set `sugar_estimate.available=false`.
