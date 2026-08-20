#!/usr/bin/env python3
"""Seasonal vineyard climate statistics from the board weather cache."""

from __future__ import annotations

import json
import importlib.util
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


TEMP_CODE = 32
HUMIDITY_CODE = 33
RAIN_CODE = 35
SOLAR_CODE = 36
DEFAULT_REPO = "/root/.picoclaw/workspace/goidanich"
MODEL_FEATURES = (
    "gdd_base10_c_days",
    "huglin_index",
    "rain_total_mm",
    "preharvest_30d_rain_mm",
    "temperature_mean_c",
    "night_temperature_mean_c",
    "mean_diurnal_range_c",
    "humidity_mean_pct",
    "night_humidity_mean_pct",
    "heat_days_ge_35c",
    "longest_dry_spell_days",
)
def env_name(name: str) -> str:
    return "SKILL_" + name.upper().replace("-", "_")


def read_params() -> dict:
    raw = sys.stdin.read().strip()
    params = json.loads(raw) if raw else {}
    for key in (
        "mode", "repo_path", "db_path", "config_path", "field", "station",
        "start", "end", "season_year", "timezone", "harvest_date",
        "huglin_k", "write_artifacts", "brix_model_path", "fetch_history",
        "history_timeout",
    ):
        value = os.environ.get(env_name(key))
        if value not in (None, "") and key not in params:
            params[key] = value
    return params


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to discover configured fields") from exc
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_day(value, fallback=None):
    if value in (None, ""):
        return fallback
    return date.fromisoformat(str(value)[:10])


def day_from_mm_dd(year: int, value: str, fallback: str) -> date:
    text = str(value or fallback).strip()
    month, day = (int(part) for part in text.split("-", 1))
    return date(year, month, day)


def parse_timestamp(value: str, local_tz: ZoneInfo) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz)


def solar_is_day(timestamp: datetime, latitude: float, longitude: float) -> bool:
    """Classify daylight using the NOAA fractional-year solar approximation."""
    day_number = timestamp.timetuple().tm_yday
    hour = timestamp.hour + timestamp.minute / 60.0
    gamma = 2.0 * math.pi / 365.0 * (day_number - 1 + (hour - 12.0) / 24.0)
    equation = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    offset_hours = (timestamp.utcoffset() or timedelta()).total_seconds() / 3600.0
    solar_minutes = hour * 60.0 + equation + 4.0 * longitude - 60.0 * offset_hours
    hour_angle = math.radians((solar_minutes / 4.0) - 180.0)
    latitude_rad = math.radians(latitude)
    cos_zenith = (
        math.sin(latitude_rad) * math.sin(declination)
        + math.cos(latitude_rad) * math.cos(declination) * math.cos(hour_angle)
    )
    return cos_zenith > 0.0


def safe_mean(values):
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return mean(finite) if finite else None


def rounded(value, digits=1):
    return None if value is None else round(float(value), digits)


def saturation_vapour_pressure(temp_c):
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def vpd_kpa(temp_c, humidity_pct):
    return saturation_vapour_pressure(temp_c) * max(0.0, 1.0 - humidity_pct / 100.0)


def field_records(config: dict, requested=None):
    fields = config.get("fields") or []
    if isinstance(fields, dict):
        fields = [dict(value, id=key) for key, value in fields.items()]
    if not requested or str(requested).lower() in {"all", "*"}:
        return list(fields)
    needle = str(requested).strip().lower()
    matches = []
    for item in fields:
        identities = (item.get("id"), item.get("name"), item.get("location"))
        if any(str(value or "").strip().lower() == needle for value in identities):
            matches.append(item)
    return matches


def field_coordinates(field):
    coordinates = field.get("coordinates") or {}
    metadata = field.get("metadata") or {}
    latitude = coordinates.get("latitude", metadata.get("lat"))
    longitude = coordinates.get("longitude", metadata.get("lon"))
    if latitude is None or longitude is None:
        raise ValueError(f"missing coordinates for field {field.get('id') or field.get('name')}")
    return float(latitude), float(longitude)


def field_station(field, override=None):
    metadata = field.get("metadata") or {}
    station = override or field.get("station_code") or metadata.get("station_code")
    if not station:
        raise ValueError(f"missing station for field {field.get('id') or field.get('name')}")
    return str(station)


def resolve_period(field, params, today):
    metadata = field.get("metadata") or {}
    year = int(params.get("season_year") or parse_day(params.get("end"), today).year)
    start = parse_day(params.get("start")) or day_from_mm_dd(
        year, params.get("season_start_mm_dd") or metadata.get("leaf_10cm_mm_dd"), "04-01"
    )
    explicit_harvest = parse_day(params.get("harvest_date") or metadata.get("harvest_date"))
    nominal_end = parse_day(params.get("end"))
    if nominal_end is None:
        nominal_end = explicit_harvest or day_from_mm_dd(
            year, params.get("season_end_mm_dd") or metadata.get("season_end_mm_dd"), "09-30"
        )
        if year == today.year:
            nominal_end = min(nominal_end, today)
    if nominal_end < start:
        raise ValueError(f"end date {nominal_end} precedes start date {start}")
    return start, nominal_end, explicit_harvest


def fetch_observations(
    conn, station, start, end, local_tz, latitude, longitude, row_cache=None,
):
    # Bound the query before timestamp parsing. Multi-field boards commonly
    # share one weather station; parsing the station's full archive once per
    # field is prohibitively slow on the board's small RISC-V CPU.
    query_start = (start - timedelta(days=1)).isoformat()
    query_end = (end + timedelta(days=2)).isoformat()
    cache_key = (station, query_start, query_end, str(local_tz))
    rows = row_cache.get(cache_key) if row_cache is not None else None
    if rows is None:
        raw_rows = conn.execute(
            """
            SELECT codi_variable, data_lectura, valor_lectura
            FROM meteo_raw
            WHERE codi_estacio=? AND codi_variable IN (?, ?, ?, ?)
              AND data_lectura>=? AND data_lectura<?
            ORDER BY data_lectura
            """,
            (
                station, TEMP_CODE, HUMIDITY_CODE, RAIN_CODE, SOLAR_CODE,
                query_start, query_end,
            ),
        ).fetchall()
        rows = [
            (int(variable), parse_timestamp(raw_timestamp, local_tz), float(raw_value))
            for variable, raw_timestamp, raw_value in raw_rows
        ]
        if row_cache is not None:
            row_cache[cache_key] = rows
    observations = defaultdict(dict)
    source_rows = defaultdict(int)
    source_slots = defaultdict(set)
    for variable, timestamp, value in rows:
        if timestamp.date() < start or timestamp.date() > end:
            continue
        key = timestamp.replace(minute=0, second=0, microsecond=0)
        source_rows[variable] += 1
        source_slots[variable].add(key)
        if variable == RAIN_CODE:
            observations[key]["rain"] = observations[key].get("rain", 0.0) + value
        elif variable == SOLAR_CODE:
            observations[key]["solar_sum"] = observations[key].get("solar_sum", 0.0) + value
            observations[key]["solar_count"] = observations[key].get("solar_count", 0) + 1
        elif variable == TEMP_CODE:
            observations[key]["temp_sum"] = observations[key].get("temp_sum", 0.0) + value
            observations[key]["temp_count"] = observations[key].get("temp_count", 0) + 1
        elif variable == HUMIDITY_CODE:
            observations[key]["humidity_sum"] = observations[key].get("humidity_sum", 0.0) + value
            observations[key]["humidity_count"] = observations[key].get("humidity_count", 0) + 1
    for timestamp, values in observations.items():
        values["is_day"] = solar_is_day(timestamp, latitude, longitude)
        if values.get("temp_count"):
            values["temp"] = values["temp_sum"] / values["temp_count"]
        if values.get("humidity_count"):
            values["humidity"] = values["humidity_sum"] / values["humidity_count"]
        if values.get("solar_count"):
            values["solar_w_m2"] = values["solar_sum"] / values["solar_count"]
    return observations, {"rows": source_rows, "slots": source_slots}


def extraterrestrial_radiation_mj(latitude, day):
    """FAO-56 daily extraterrestrial radiation on a horizontal surface."""
    latitude_rad = math.radians(latitude)
    day_number = day.timetuple().tm_yday
    inverse_distance = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_number / 365.0)
    declination = 0.409 * math.sin(2.0 * math.pi * day_number / 365.0 - 1.39)
    sunset_angle = math.acos(max(-1.0, min(1.0, -math.tan(latitude_rad) * math.tan(declination))))
    return (
        24.0 * 60.0 / math.pi * 0.0820 * inverse_distance
        * (
            sunset_angle * math.sin(latitude_rad) * math.sin(declination)
            + math.cos(latitude_rad) * math.cos(declination) * math.sin(sunset_angle)
        )
    )


def daily_records(observations, start, end, latitude=None):
    grouped = defaultdict(list)
    for timestamp, values in observations.items():
        grouped[timestamp.date()].append((timestamp, values))
    records = []
    cursor = start
    while cursor <= end:
        rows = grouped.get(cursor, [])
        temps = [values.get("temp") for _, values in rows if values.get("temp") is not None]
        humidity = [values.get("humidity") for _, values in rows if values.get("humidity") is not None]
        rain_values = [values.get("rain") for _, values in rows if values.get("rain") is not None]
        solar_values = [
            values.get("solar_w_m2") for _, values in rows
            if values.get("solar_w_m2") is not None
        ]
        solar_mj = sum(solar_values) * 3600.0 / 1_000_000.0 if solar_values else None
        extraterrestrial_mj = (
            extraterrestrial_radiation_mj(latitude, cursor)
            if latitude is not None else None
        )
        records.append({
            "day": cursor,
            "tmean": safe_mean(temps),
            "tmin": min(temps) if temps else None,
            "tmax": max(temps) if temps else None,
            "humidity_mean": safe_mean(humidity),
            "rain": sum(rain_values) if rain_values else None,
            "solar_mj_m2": solar_mj,
            "clearness_index": (
                solar_mj / extraterrestrial_mj
                if solar_mj is not None and extraterrestrial_mj else None
            ),
            "temp_samples": len(temps),
            "humidity_samples": len(humidity),
            "rain_samples": len(rain_values),
            "solar_samples": len(solar_values),
        })
        cursor += timedelta(days=1)
    return records


def dry_spell(records, threshold=1.0):
    longest = 0
    current = 0
    for record in records:
        rain = record["rain"]
        if rain is None:
            current = 0
        elif rain < threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def subset_statistics(records):
    rain_records = [record for record in records if record["rain"] is not None]
    temp_records = [record for record in records if record["tmean"] is not None]
    humidity_records = [record for record in records if record["humidity_mean"] is not None]
    max_rain_record = max(rain_records, key=lambda row: row["rain"], default=None)
    solar_records = [row for row in records if row.get("solar_mj_m2") is not None]
    return {
        "days": len(records),
        "days_with_temperature": len(temp_records),
        "days_with_humidity": len(humidity_records),
        "days_with_precipitation": len(rain_records),
        "rain_total_mm": rounded(sum(row["rain"] for row in rain_records)) if rain_records else None,
        "rain_days_ge_1mm": sum(row["rain"] >= 1.0 for row in rain_records),
        "rain_days_ge_10mm": sum(row["rain"] >= 10.0 for row in rain_records),
        "max_daily_rain_mm": rounded(max_rain_record["rain"] if max_rain_record else None),
        "max_daily_rain_day": max_rain_record["day"].isoformat() if max_rain_record else None,
        "longest_dry_spell_days": dry_spell(records),
        "temperature_mean_c": rounded(safe_mean(row["tmean"] for row in temp_records)),
        "temperature_min_c": rounded(min((row["tmin"] for row in temp_records), default=None)),
        "temperature_max_c": rounded(max((row["tmax"] for row in temp_records), default=None)),
        "mean_daily_min_c": rounded(safe_mean(row["tmin"] for row in temp_records)),
        "mean_daily_max_c": rounded(safe_mean(row["tmax"] for row in temp_records)),
        "mean_diurnal_range_c": rounded(safe_mean(
            row["tmax"] - row["tmin"] for row in temp_records
            if row["tmax"] is not None and row["tmin"] is not None
        )),
        "heat_days_ge_30c": sum(row["tmax"] is not None and row["tmax"] >= 30.0 for row in records),
        "heat_days_ge_35c": sum(row["tmax"] is not None and row["tmax"] >= 35.0 for row in records),
        "tropical_nights_ge_20c": sum(row["tmin"] is not None and row["tmin"] >= 20.0 for row in records),
        "frost_nights_le_0c": sum(row["tmin"] is not None and row["tmin"] <= 0.0 for row in records),
        "humidity_mean_pct": rounded(safe_mean(row["humidity_mean"] for row in humidity_records)),
        "days_with_solar_radiation": len(solar_records),
        "solar_energy_total_mj_m2": rounded(sum(row["solar_mj_m2"] for row in solar_records)),
        "solar_energy_mean_daily_mj_m2": rounded(safe_mean(row["solar_mj_m2"] for row in solar_records)),
        "high_solar_days": sum(
            row.get("clearness_index") is not None and row["clearness_index"] >= 0.65
            for row in solar_records
        ),
        "high_solar_day_definition": "daily global irradiation / extraterrestrial irradiation >= 0.65",
    }


def calculate_indices(records, huglin_k):
    gdd = 0.0
    huglin = 0.0
    for row in records:
        if row["tmean"] is None:
            continue
        gdd += max(0.0, row["tmean"] - 10.0)
        if row["tmax"] is not None and date(row["day"].year, 4, 1) <= row["day"] <= date(row["day"].year, 9, 30):
            huglin += max(
                0.0,
                ((row["tmean"] - 10.0) + (row["tmax"] - 10.0)) / 2.0,
            ) * huglin_k
    september_minima = [
        row["tmin"] for row in records if row["day"].month == 9 and row["tmin"] is not None
    ]
    return {
        "gdd_base10_c_days": rounded(gdd),
        "huglin_index": rounded(huglin),
        "huglin_latitude_coefficient": huglin_k,
        "cool_night_index_september_c": rounded(safe_mean(september_minima)),
        "cool_night_days_available": len(september_minima),
    }


def hourly_statistics(observations):
    temperatures = []
    day_temperatures = []
    night_temperatures = []
    humidity = []
    day_humidity = []
    night_humidity = []
    vpds = []
    for values in observations.values():
        temp = values.get("temp")
        rh = values.get("humidity")
        is_day = bool(values.get("is_day"))
        if temp is not None:
            temperatures.append(temp)
            (day_temperatures if is_day else night_temperatures).append(temp)
        if rh is not None:
            humidity.append(rh)
            (day_humidity if is_day else night_humidity).append(rh)
        if temp is not None and rh is not None:
            vpds.append(vpd_kpa(temp, rh))
    return {
        "day_temperature_mean_c": rounded(safe_mean(day_temperatures)),
        "night_temperature_mean_c": rounded(safe_mean(night_temperatures)),
        "night_temperature_min_c": rounded(min(night_temperatures) if night_temperatures else None),
        "day_humidity_mean_pct": rounded(safe_mean(day_humidity)),
        "night_humidity_mean_pct": rounded(safe_mean(night_humidity)),
        "hours_rh_ge_90pct": sum(value >= 90.0 for value in humidity),
        "hours_rh_ge_95pct": sum(value >= 95.0 for value in humidity),
        "hours_temp_ge_30c": sum(value >= 30.0 for value in temperatures),
        "hours_temp_ge_35c": sum(value >= 35.0 for value in temperatures),
        "vpd_mean_kpa": rounded(safe_mean(vpds), 2),
        "vpd_max_kpa": rounded(max(vpds) if vpds else None, 2),
        "daylight_method": "NOAA fractional-year solar elevation; elevation > 0 degrees",
    }


def monthly_statistics(records):
    by_month = defaultdict(list)
    for row in records:
        by_month[row["day"].strftime("%Y-%m")].append(row)
    return {month: subset_statistics(rows) for month, rows in sorted(by_month.items())}


def monthly_day_night_statistics(observations):
    by_month = defaultdict(dict)
    for timestamp, values in observations.items():
        by_month[timestamp.strftime("%Y-%m")][timestamp] = values
    return {month: hourly_statistics(rows) for month, rows in sorted(by_month.items())}


def quality_feature_vector(summary, preharvest, preharvest_hourly):
    hourly = summary["hourly"]
    indices = summary["indices"]
    season = summary["season"]
    return {
        "gdd_base10_c_days": indices["gdd_base10_c_days"],
        "huglin_index": indices["huglin_index"],
        "rain_total_mm": season["rain_total_mm"],
        "preharvest_30d_rain_mm": preharvest["rain_total_mm"],
        "temperature_mean_c": season["temperature_mean_c"],
        "night_temperature_mean_c": hourly["night_temperature_mean_c"],
        "mean_diurnal_range_c": season["mean_diurnal_range_c"],
        "humidity_mean_pct": season["humidity_mean_pct"],
        "night_humidity_mean_pct": hourly["night_humidity_mean_pct"],
        "heat_days_ge_35c": season["heat_days_ge_35c"],
        "longest_dry_spell_days": season["longest_dry_spell_days"],
        "solar_energy_total_mj_m2": season["solar_energy_total_mj_m2"],
        "solar_energy_mean_daily_mj_m2": season["solar_energy_mean_daily_mj_m2"],
        "high_solar_days": season["high_solar_days"],
        "hours_rh_ge_90pct": hourly["hours_rh_ge_90pct"],
        "hours_rh_ge_95pct": hourly["hours_rh_ge_95pct"],
        "vpd_mean_kpa": hourly["vpd_mean_kpa"],
        "vpd_max_kpa": hourly["vpd_max_kpa"],
        "preharvest_30d_temperature_mean_c": preharvest["temperature_mean_c"],
        "preharvest_30d_night_humidity_mean_pct": preharvest_hourly["night_humidity_mean_pct"],
        "preharvest_30d_solar_energy_total_mj_m2": preharvest["solar_energy_total_mj_m2"],
        "preharvest_30d_heat_days_ge_35c": preharvest["heat_days_ge_35c"],
    }


def sugar_estimate(field_id, feature_vector, model_path):
    default = {
        "available": False,
        "estimate_brix": None,
        "reason": (
            "Weather describes ripening conditions but does not identify berry sugar. "
            "A field-calibrated model with measured Brix labels is required."
        ),
        "required_calibration": (
            "Repeated Brix observations across phenological dates and preferably multiple vintages, "
            "with yield, irrigation/water status, canopy, variety and harvest context."
        ),
    }
    if not model_path:
        return default
    path = Path(model_path)
    if not path.exists():
        default["reason"] = f"Configured Brix model does not exist: {path}"
        return default
    model = json.loads(path.read_text(encoding="utf-8"))
    if not model.get("validated"):
        default["reason"] = "Brix model exists but is not marked validated."
        return default
    if model.get("field_id") not in (None, field_id):
        default["reason"] = "Brix model field identity does not match the requested field."
        return default
    coefficients = model.get("coefficients") or {}
    missing = [
        name for name in MODEL_FEATURES
        if name not in coefficients or feature_vector.get(name) is None
    ]
    if missing:
        default["reason"] = (
            "Validated Brix model is missing coefficients or inputs: " + ", ".join(missing)
        )
        return default
    estimate = float(model.get("intercept", 0.0))
    for name in MODEL_FEATURES:
        estimate += float(coefficients[name]) * float(feature_vector[name])
    return {
        "available": True,
        "estimate_brix": rounded(estimate, 2),
        "method": model.get("model_name") or "field_calibrated_weather_model",
        "model_version": model.get("version"),
        "validation_rmse_brix": model.get("validation_rmse_brix"),
        "training_observations": model.get("training_observations"),
        "reason": "Estimate produced by an explicitly validated field model.",
    }


def harvest_readiness(variety, sugar):
    """Describe whether an evidence-based harvest-date estimate is possible."""
    missing = [
        "dated phenological stage observations",
        "repeated berry sugar measurements",
        "titratable acidity and pH",
        "berry weight or yield/load context",
        "the intended wine style",
    ]
    if not sugar.get("available"):
        missing.insert(1, "a locally validated berry-sugar model")
    return {
        "available": False,
        "recommended_harvest_date": None,
        "status": "requires_local_maturity_observations",
        "variety": variety or None,
        "missing_evidence": missing,
        "literature_role": (
            "Variety literature may define candidate phenology and maturity priors, but it "
            "cannot replace local measurements or validate a harvest date for this field."
        ),
        "reason": (
            "Weather exposure constrains ripening, but technological and phenolic maturity "
            "also depend on crop load, canopy, water status, berry composition and wine style."
        ),
    }


def daily_research_snapshots(records, observations):
    """Build compact observed drivers for generic lag and association tests."""
    observations_by_day = defaultdict(dict)
    for timestamp, values in observations.items():
        observations_by_day[timestamp.date()][timestamp] = values
    snapshots = []
    for record in records:
        day_observations = observations_by_day.get(record["day"], {})
        hourly = hourly_statistics(day_observations)
        has_temperature = any(
            values.get("temp") is not None for values in day_observations.values()
        )
        has_humidity = any(
            values.get("humidity") is not None for values in day_observations.values()
        )
        metrics = {}
        for name, value in (
            ("weather.rain_mm", record.get("rain")),
            ("weather.temperature_mean_c", record.get("tmean")),
            ("weather.temperature_min_c", record.get("tmin")),
            ("weather.temperature_max_c", record.get("tmax")),
            ("weather.humidity_mean_pct", record.get("humidity_mean")),
            ("weather.solar_energy_mj_m2", record.get("solar_mj_m2")),
            ("weather.clearness_index", record.get("clearness_index")),
        ):
            if value is not None:
                metrics[name] = float(value)
        if has_temperature:
            for name in (
                "day_temperature_mean_c", "night_temperature_mean_c",
                "night_temperature_min_c", "hours_temp_ge_30c", "hours_temp_ge_35c",
            ):
                value = hourly.get(name)
                if value is not None:
                    metrics[f"weather.{name}"] = float(value)
        if has_humidity:
            for name in (
                "day_humidity_mean_pct", "night_humidity_mean_pct",
                "hours_rh_ge_90pct", "hours_rh_ge_95pct",
            ):
                value = hourly.get(name)
                if value is not None:
                    metrics[f"weather.{name}"] = float(value)
        if has_temperature and has_humidity:
            for name in ("vpd_mean_kpa", "vpd_max_kpa"):
                value = hourly.get(name)
                if value is not None:
                    metrics[f"weather.{name}"] = float(value)
        if metrics:
            snapshots.append({"day": record["day"].isoformat(), "metrics": metrics})
    return snapshots


def metric_unit(metric):
    name = metric.rsplit(".", 1)[-1]
    if "gdd" in name:
        return "degC_days"
    if name.endswith("_mm"):
        return "mm"
    if name.endswith("_c"):
        return "degC"
    if name.endswith("_pct") or name.endswith("pct"):
        return "percent"
    if name.endswith("_kpa"):
        return "kPa"
    if name.endswith("_mj_m2"):
        return "MJ/m2"
    if "hour" in name or name.endswith("_slots"):
        return "hours_or_slots"
    if "day" in name:
        return "days"
    if name.endswith("_rows") or name == "days":
        return "count"
    if "index" in name:
        return "index"
    return "count_or_dimensionless"


def persist_research_metrics(connection, reports, generated_at=None):
    """Expose climate outputs to the generic autonomous research catalogue."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS season_climate_metrics (
            field_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY(field_id, observed_at, metric)
        )
        """
    )
    # Schema versions before 2026-08-17 also stored cumulative metrics here.
    # Those values have unlike units and windows, so keep this relation purely
    # day-level and leave cumulative summaries in the report artifacts.
    connection.execute(
        "DELETE FROM season_climate_metrics WHERE metric NOT LIKE 'weather.%'"
    )
    written = 0
    for report in reports:
        for snapshot in report.get("_research_daily") or []:
            for path, value in sorted((snapshot.get("metrics") or {}).items()):
                connection.execute(
                    """
                    INSERT INTO season_climate_metrics(
                        field_id, observed_at, period_start, period_end,
                        metric, value, unit, generated_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(field_id, observed_at, metric) DO UPDATE SET
                        value=excluded.value,
                        unit=excluded.unit,
                        generated_at=excluded.generated_at
                    """,
                    (
                        report["field_id"], snapshot["day"], snapshot["day"], snapshot["day"],
                        path, value, metric_unit(path), generated_at,
                    ),
                )
                written += 1
    connection.commit()
    return written


def coverage(source_counts, start, end):
    expected = max(1, ((end - start).days + 1) * 24)
    source_rows = source_counts["rows"]
    source_slots = source_counts["slots"]
    temp_slots = len(source_slots.get(TEMP_CODE, set()))
    humidity_slots = len(source_slots.get(HUMIDITY_CODE, set()))
    precipitation_slots = len(source_slots.get(RAIN_CODE, set()))
    solar_slots = len(source_slots.get(SOLAR_CODE, set()))
    return {
        "expected_hourly_slots": expected,
        "temperature_observation_rows": source_rows.get(TEMP_CODE, 0),
        "humidity_observation_rows": source_rows.get(HUMIDITY_CODE, 0),
        "precipitation_observation_rows": source_rows.get(RAIN_CODE, 0),
        "solar_observation_rows": source_rows.get(SOLAR_CODE, 0),
        "temperature_hourly_slots": temp_slots,
        "humidity_hourly_slots": humidity_slots,
        "precipitation_hourly_slots": precipitation_slots,
        "solar_hourly_slots": solar_slots,
        "temperature_pct": rounded(100.0 * temp_slots / expected),
        "humidity_pct": rounded(100.0 * humidity_slots / expected),
        "precipitation_pct": rounded(100.0 * precipitation_slots / expected),
        "solar_pct": rounded(100.0 * solar_slots / expected),
    }


def shifted_year(day, years=-1):
    """Shift a date while keeping leap-day windows valid."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def comparison_window(
    conn, station, start, end, local_tz, latitude, longitude, row_cache,
):
    observations, source_counts = fetch_observations(
        conn, station, start, end, local_tz, latitude, longitude, row_cache,
    )
    records = daily_records(observations, start, end, latitude)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "coverage": coverage(source_counts, start, end),
        "daily": subset_statistics(records),
        "hourly": hourly_statistics(observations),
    }


def comparison_coverage_is_sufficient(window, threshold=70.0):
    values = window.get("coverage") if isinstance(window.get("coverage"), dict) else {}
    return all(
        float(values.get(name) or 0.0) >= threshold
        for name in ("temperature_pct", "humidity_pct", "precipitation_pct")
    )


def fetch_historical_observations(conn, repo_path, station, start, end, timeout=30):
    """Fill only meteo_raw through the board's existing XEMA history loader."""
    loader_path = Path(repo_path) / "board_fill_gaps.py"
    if not loader_path.exists():
        return {"ok": False, "reason": f"history loader missing: {loader_path}"}
    spec = importlib.util.spec_from_file_location("vineyard_history_loader", loader_path)
    if spec is None or spec.loader is None:
        return {"ok": False, "reason": "history loader cannot be imported"}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.fetch_weather(station, start.isoformat(), end.isoformat(), int(timeout))
    inserted = module.insert_weather(conn, rows)
    conn.commit()
    return {
        "ok": True,
        "provider": "meteocat_xema_observed_history",
        "rows_fetched": len(rows),
        "rows_inserted_attempted": inserted,
    }


def comparison_window_with_backfill(
    conn, repo_path, station, start, end, local_tz, latitude, longitude,
    row_cache, fetch_history=True, timeout=30,
):
    window = comparison_window(
        conn, station, start, end, local_tz, latitude, longitude, row_cache,
    )
    if comparison_coverage_is_sufficient(window) or not fetch_history:
        window["history_retrieval"] = {
            "attempted": False,
            "reason": "cached coverage sufficient" if comparison_coverage_is_sufficient(window)
            else "history retrieval disabled",
        }
        return window
    retrieval_cache = None
    retrieval_key = (station, start.isoformat(), end.isoformat())
    if row_cache is not None:
        retrieval_cache = row_cache.setdefault(("__history_retrieval__",), {})
        prior_retrieval = retrieval_cache.get(retrieval_key)
        if prior_retrieval is not None:
            window["history_retrieval"] = dict(
                prior_retrieval, attempted=False, reused=True,
            )
            return window
    try:
        retrieval = fetch_historical_observations(
            conn, repo_path, station, start, end, timeout,
        )
        if row_cache is not None:
            query_start = (start - timedelta(days=1)).isoformat()
            query_end = (end + timedelta(days=2)).isoformat()
            row_cache.pop((station, query_start, query_end, str(local_tz)), None)
        if retrieval_cache is not None:
            retrieval_cache[retrieval_key] = retrieval
        window = comparison_window(
            conn, station, start, end, local_tz, latitude, longitude, row_cache,
        )
        window["history_retrieval"] = dict(retrieval, attempted=True)
    except Exception as exc:
        retrieval = {
            "attempted": True,
            "ok": False,
            "reason": str(exc)[:500],
        }
        window["history_retrieval"] = retrieval
        if retrieval_cache is not None:
            retrieval_cache[retrieval_key] = retrieval
    return window


def human_summary(report):
    season = report["season"]
    hourly = report["hourly"]
    indices = report["indices"]
    sugar = report["sugar_estimate"]
    sugar_text = (
        f"Estimated sugar: {sugar['estimate_brix']} Brix ({sugar.get('method')})."
        if sugar["available"] else "Sugar estimate: unavailable until a field-calibrated Brix model is validated."
    )
    harvest_text = (
        f"Estimated harvest date: {report['harvest_readiness']['recommended_harvest_date']}."
        if report["harvest_readiness"]["available"] else
        "Harvest-date estimate: unavailable until field maturity observations support a validated model."
    )
    return (
        f"Season climate - {report['field_name']} ({report['start']} to {report['end']})\n"
        f"Rain: {season['rain_total_mm']} mm; longest dry spell: {season['longest_dry_spell_days']} days.\n"
        f"Temperature: mean {season['temperature_mean_c']} C, min {season['temperature_min_c']} C, "
        f"max {season['temperature_max_c']} C; night mean {hourly['night_temperature_mean_c']} C.\n"
        f"Humidity: mean {season['humidity_mean_pct']}%, night mean {hourly['night_humidity_mean_pct']}%; "
        f"RH >=95% for {hourly['hours_rh_ge_95pct']} hourly observations.\n"
        f"Solar exposure: {season['solar_energy_total_mj_m2']} MJ/m2 over "
        f"{season['days_with_solar_radiation']} observed days; mean VPD {hourly['vpd_mean_kpa']} kPa.\n"
        f"Heat accumulation: GDD10 {indices['gdd_base10_c_days']} C-days; Huglin {indices['huglin_index']}.\n"
        f"{sugar_text}\n{harvest_text}"
    )


def markdown_report(report):
    lines = [
        f"# Seasonal climate: {report['field_name']}", "",
        f"Period: {report['start']} to {report['end']} ({report['period_status']}).", "",
        report["send_text"], "", "## Monthly statistics", "",
        "| Month | Rain (mm) | Day/night temp (C) | Min/max (C) | Day/night RH (%) | RH >=95% (h) | Solar (MJ/m2) | High-solar days | Dry spell (days) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for month, row in report["monthly"].items():
        day_night = report["monthly_day_night"][month]
        lines.append(
            f"| {month} | {row['rain_total_mm']} | "
            f"{day_night['day_temperature_mean_c']} / {day_night['night_temperature_mean_c']} | "
            f"{row['temperature_min_c']} / {row['temperature_max_c']} | "
            f"{day_night['day_humidity_mean_pct']} / {day_night['night_humidity_mean_pct']} | "
            f"{day_night['hours_rh_ge_95pct']} | {row['solar_energy_total_mj_m2']} | "
            f"{row['high_solar_days']} | {row['longest_dry_spell_days']} |"
        )
    lines.extend([
        "", "## Interpretation boundary", "",
        "These variables describe climatic exposure and ripening context. They do not, by themselves, "
        "determine grape quality, disease presence, harvest date, or berry sugar.", "",
    ])
    return "\n".join(lines)


def analyze_field(conn, field, params, local_tz, today, row_cache=None):
    field_id = str(field.get("id") or "field")
    field_name = str(field.get("name") or field.get("location") or field_id)
    latitude, longitude = field_coordinates(field)
    station = field_station(field, params.get("station"))
    start, end, explicit_harvest = resolve_period(field, params, today)
    observations, source_counts = fetch_observations(
        conn, station, start, end, local_tz, latitude, longitude, row_cache
    )
    records = daily_records(observations, start, end, latitude)
    season = subset_statistics(records)
    hourly = hourly_statistics(observations)
    indices = calculate_indices(records, float(params.get("huglin_k") or 1.03))
    preharvest_start = max(start, end - timedelta(days=29))
    preharvest_records = [row for row in records if row["day"] >= preharvest_start]
    preharvest_observations = {
        timestamp: values for timestamp, values in observations.items()
        if timestamp.date() >= preharvest_start
    }
    preharvest = subset_statistics(preharvest_records)
    preharvest_hourly = hourly_statistics(preharvest_observations)
    previous_30d_end = preharvest_start - timedelta(days=1)
    previous_30d_start = previous_30d_end - timedelta(days=29)
    previous_year_start = shifted_year(preharvest_start)
    previous_year_end = shifted_year(end)
    fetch_history = as_bool(params.get("fetch_history"), True)
    history_timeout = int(params.get("history_timeout") or 30)
    comparison_windows = {
        "preceding_30d": comparison_window_with_backfill(
            conn, params["repo_path"], station,
            previous_30d_start, previous_30d_end,
            local_tz, latitude, longitude, row_cache,
            fetch_history, history_timeout,
        ),
        "same_30d_previous_year": comparison_window_with_backfill(
            conn, params["repo_path"], station,
            previous_year_start, previous_year_end,
            local_tz, latitude, longitude, row_cache,
            fetch_history, history_timeout,
        ),
    }
    summary = {"season": season, "hourly": hourly, "indices": indices}
    feature_vector = quality_feature_vector(summary, preharvest, preharvest_hourly)
    configured_model = params.get("brix_model_path")
    if not configured_model:
        candidate = Path(params["repo_path"]) / "models" / f"brix_{field_id}.json"
        configured_model = str(candidate) if candidate.exists() else None
    report = {
        "status": "success" if observations else "no_data",
        "field_id": field_id,
        "field_name": field_name,
        "station": station,
        "variety": field.get("variety") or (field.get("metadata") or {}).get("variety"),
        "coordinates": {"latitude": latitude, "longitude": longitude},
        "timezone": str(local_tz),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_status": "harvest-bounded" if explicit_harvest else ("ongoing season" if end == today else "configured season"),
        "coverage": coverage(source_counts, start, end),
        "season": season,
        "hourly": hourly,
        "indices": indices,
        "preharvest_or_recent_30d": dict(preharvest, start=preharvest_start.isoformat(), end=end.isoformat()),
        "preharvest_or_recent_30d_hourly": preharvest_hourly,
        "comparison_windows": comparison_windows,
        "monthly": monthly_statistics(records),
        "monthly_day_night": monthly_day_night_statistics(observations),
        "quality_context_features": feature_vector,
        "sugar_estimate": sugar_estimate(field_id, feature_vector, configured_model),
        "interpretation": (
            "Weather metrics quantify climatic exposure relevant to vine water balance, heat load, "
            "acid retention, ripening rate and disease microclimate. They are not a direct measurement "
            "of grape composition or final wine quality."
        ),
        "_research_daily": daily_research_snapshots(records, observations),
    }
    report["harvest_readiness"] = harvest_readiness(
        report["variety"], report["sugar_estimate"]
    )
    report["send_text"] = human_summary(report)
    return report


def write_artifacts(repo_path, reports, year):
    results_dir = Path(repo_path) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for report in reports:
        slug = "".join(character if character.isalnum() or character in "-_" else "_" for character in report["field_id"])
        json_path = results_dir / f"season_climate_{slug}_{year}.json"
        markdown_path = results_dir / f"season_climate_{slug}_{year}.md"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        markdown_path.write_text(markdown_report(report) + "\n", encoding="utf-8")
        artifacts.append({"field_id": report["field_id"], "json": str(json_path), "markdown": str(markdown_path)})
    return artifacts


def model_info():
    return {
        "status": "success",
        "mode": "model_info",
        "observed_variables": {
            "temperature": {"code": TEMP_CODE, "unit": "C"},
            "relative_humidity": {"code": HUMIDITY_CODE, "unit": "%"},
            "precipitation": {"code": RAIN_CODE, "unit": "mm per observation interval"},
            "solar_irradiance": {"code": SOLAR_CODE, "unit": "W/m2"},
        },
        "indices": {
            "gdd_base10": "Sum of max(0, daily mean temperature - 10 C).",
            "huglin": "April-September heat sum using daily mean and maximum temperature and latitude coefficient k.",
            "cool_night": "Mean daily minimum temperature in September when available.",
            "vpd": "Saturation vapour pressure deficit derived from coincident temperature and RH.",
        },
        "sugar_policy": (
            "Do not infer Brix from weather alone. Emit an estimate only from a field-matched model "
            "explicitly marked validated and accompanied by validation error and training sample count."
        ),
        "harvest_policy": (
            "Cultivar literature is a candidate prior. Emit a harvest date only from a locally "
            "validated phenology/composition model with current field maturity measurements and "
            "held-out error in days."
        ),
        "research_series": (
            "Report mode writes covered numeric variables to season_climate_metrics for generic "
            "cross-series discovery."
        ),
    }


def main():
    params = read_params()
    mode = str(params.get("mode") or "report").strip().lower().replace("-", "_")
    if mode == "model_info":
        print(json.dumps(model_info(), ensure_ascii=False))
        return 0
    if mode not in {"report", "summary"}:
        raise ValueError(f"unsupported mode: {mode}")
    repo_path = Path(params.get("repo_path") or DEFAULT_REPO)
    params["repo_path"] = str(repo_path)
    db_path = Path(params.get("db_path") or repo_path / "goidanich.db")
    config_path = Path(params.get("config_path") or repo_path / "agent_config.yaml")
    config = load_yaml(config_path)
    fields = field_records(config, params.get("field"))
    if not fields and params.get("station"):
        fields = [{
            "id": params.get("field") or "field",
            "name": params.get("field") or "Field",
            "station_code": params["station"],
            "coordinates": {
                "latitude": params.get("latitude"),
                "longitude": params.get("longitude"),
            },
        }]
    if not fields:
        raise ValueError("no configured field matched the request")
    if not db_path.exists():
        raise FileNotFoundError(f"weather database not found: {db_path}")
    local_tz = ZoneInfo(str(params.get("timezone") or "Europe/Madrid"))
    today = datetime.now(local_tz).date()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meteo_raw_station_time_variable
            ON meteo_raw(codi_estacio, data_lectura, codi_variable)
            """
        )
        row_cache = {}
        reports = [
            analyze_field(conn, field, params, local_tz, today, row_cache)
            for field in fields
        ]
        research_metrics_written = persist_research_metrics(conn, reports)
    for report in reports:
        report.pop("_research_daily", None)
    year = int(params.get("season_year") or reports[0]["end"][:4])
    artifacts = write_artifacts(repo_path, reports, year) if as_bool(params.get("write_artifacts"), True) else []
    output = {
        "status": "success" if all(row["status"] == "success" for row in reports) else "partial",
        "mode": mode,
        "field_scope": params.get("field") or "all",
        "field_reports": reports,
        "artifacts": artifacts,
        "research_metrics_written": research_metrics_written,
        "send_text": "\n\n".join(report["send_text"] for report in reports),
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
