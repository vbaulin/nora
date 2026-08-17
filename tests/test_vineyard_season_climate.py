import importlib.util
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "vineyard_season_climate" / "scripts" / "analyze.py"
SPEC = importlib.util.spec_from_file_location("vineyard_season_climate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def weather_db():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE meteo_raw (
            id TEXT PRIMARY KEY,
            codi_estacio TEXT,
            codi_variable INTEGER,
            data_lectura TEXT,
            valor_lectura REAL
        )
        """
    )
    return connection


def add_weather(connection, timestamp, temp, humidity, rain, solar=0.0, suffix=""):
    for code, value in ((32, temp), (33, humidity), (35, rain), (36, solar)):
        connection.execute(
            "INSERT INTO meteo_raw VALUES (?, ?, ?, ?, ?)",
            (f"{timestamp}-{code}-{suffix}", "D9", code, timestamp, value),
        )


def test_hourly_aggregation_and_rain_totals_do_not_double_average():
    connection = weather_db()
    add_weather(connection, "2026-04-01T10:00:00+02:00", 20.0, 60.0, 0.4, 600.0, "a")
    add_weather(connection, "2026-04-01T10:30:00+02:00", 22.0, 70.0, 0.6, 800.0, "b")
    add_weather(connection, "2026-04-02T22:00:00+02:00", 12.0, 95.0, 2.0, 0.0, "c")
    observations, counts = MODULE.fetch_observations(
        connection,
        "D9",
        date(2026, 4, 1),
        date(2026, 4, 2),
        ZoneInfo("Europe/Madrid"),
        41.2,
        1.5,
    )
    first = observations[datetime(2026, 4, 1, 10, tzinfo=ZoneInfo("Europe/Madrid"))]
    assert first["temp"] == 21.0
    assert first["humidity"] == 65.0
    assert first["solar_w_m2"] == 700.0
    records = MODULE.daily_records(observations, date(2026, 4, 1), date(2026, 4, 2), 41.2)
    summary = MODULE.subset_statistics(records)
    assert summary["rain_total_mm"] == 3.0
    observed_coverage = MODULE.coverage(counts, date(2026, 4, 1), date(2026, 4, 2))
    assert observed_coverage["temperature_observation_rows"] == 3
    assert observed_coverage["temperature_hourly_slots"] == 2


def test_missing_precipitation_is_not_reported_as_zero():
    records = MODULE.daily_records({}, date(2026, 6, 1), date(2026, 6, 3))
    summary = MODULE.subset_statistics(records)
    assert summary["rain_total_mm"] is None
    assert summary["days_with_precipitation"] == 0


def test_brix_requires_validated_field_model(tmp_path):
    features = {name: 1.0 for name in MODULE.MODEL_FEATURES}
    unavailable = MODULE.sugar_estimate("field-1", features, None)
    assert unavailable["available"] is False

    model_path = tmp_path / "brix.json"
    model_path.write_text(json.dumps({
        "validated": True,
        "field_id": "field-1",
        "model_name": "test_linear_brix",
        "version": "1",
        "intercept": 10.0,
        "coefficients": {name: 0.1 for name in MODULE.MODEL_FEATURES},
        "training_observations": 40,
        "validation_rmse_brix": 0.8,
    }))
    estimate = MODULE.sugar_estimate("field-1", features, model_path)
    assert estimate["available"] is True
    assert estimate["estimate_brix"] == 11.1
    assert estimate["validation_rmse_brix"] == 0.8


def test_quality_context_retains_solar_vpd_and_recent_night_humidity():
    summary = {
        "indices": {"gdd_base10_c_days": 900.0, "huglin_index": 1400.0},
        "season": {
            "rain_total_mm": 210.0,
            "temperature_mean_c": 19.0,
            "mean_diurnal_range_c": 12.0,
            "humidity_mean_pct": 67.0,
            "heat_days_ge_35c": 4,
            "longest_dry_spell_days": 23,
            "solar_energy_total_mj_m2": 2400.0,
            "solar_energy_mean_daily_mj_m2": 20.0,
            "high_solar_days": 72,
        },
        "hourly": {
            "night_temperature_mean_c": 15.0,
            "night_humidity_mean_pct": 82.0,
            "hours_rh_ge_90pct": 160,
            "hours_rh_ge_95pct": 50,
            "vpd_mean_kpa": 0.8,
            "vpd_max_kpa": 3.1,
        },
    }
    preharvest = {
        "rain_total_mm": 18.0,
        "temperature_mean_c": 21.0,
        "solar_energy_total_mj_m2": 580.0,
        "heat_days_ge_35c": 1,
    }
    recent_hourly = {"night_humidity_mean_pct": 77.0}
    features = MODULE.quality_feature_vector(summary, preharvest, recent_hourly)
    assert features["solar_energy_total_mj_m2"] == 2400.0
    assert features["vpd_max_kpa"] == 3.1
    assert features["preharvest_30d_night_humidity_mean_pct"] == 77.0


def test_climate_metrics_are_persisted_as_research_series():
    connection = sqlite3.connect(":memory:")
    reports = [{
        "status": "success",
        "field_id": "field-1",
        "start": "2026-04-01",
        "end": "2026-08-17",
        "coverage": {"solar_pct": 98.0},
        "season": {"rain_total_mm": 122.5, "high_solar_days": 65},
        "hourly": {"vpd_mean_kpa": 0.9},
        "indices": {"gdd_base10_c_days": 1010.0},
        "preharvest_or_recent_30d": {"rain_total_mm": 8.0},
        "preharvest_or_recent_30d_hourly": {"night_humidity_mean_pct": 79.0},
    }]
    written = MODULE.persist_research_metrics(
        connection, reports, generated_at="2026-08-17T08:00:00+00:00"
    )
    assert written == 7
    row = connection.execute(
        "SELECT value, unit FROM season_climate_metrics "
        "WHERE field_id=? AND metric=?",
        ("field-1", "season.rain_total_mm"),
    ).fetchone()
    assert row == (122.5, "mm")


def test_missing_solar_channel_is_not_persisted_as_zero_exposure():
    connection = sqlite3.connect(":memory:")
    report = {
        "status": "success",
        "field_id": "field-1",
        "start": "2026-04-01",
        "end": "2026-08-17",
        "coverage": {"solar_hourly_slots": 0},
        "season": {
            "days_with_solar_radiation": 0,
            "solar_energy_total_mj_m2": 0.0,
            "high_solar_days": 0,
        },
    }
    MODULE.persist_research_metrics(connection, [report])
    metrics = {
        row[0] for row in connection.execute(
            "SELECT metric FROM season_climate_metrics"
        ).fetchall()
    }
    assert "season.solar_energy_total_mj_m2" not in metrics
    assert "season.days_with_solar_radiation" not in metrics


def test_daily_weather_history_is_backfilled_for_immediate_pattern_discovery():
    local_tz = ZoneInfo("Europe/Madrid")
    day = date(2026, 8, 16)
    timestamp = datetime(2026, 8, 16, 23, tzinfo=local_tz)
    records = [{
        "day": day,
        "rain": 3.2,
        "tmean": 25.0,
        "tmin": 20.0,
        "tmax": 31.0,
        "humidity_mean": 84.0,
        "solar_mj_m2": 21.5,
        "clearness_index": 0.7,
    }]
    snapshots = MODULE.daily_research_snapshots(records, {
        timestamp: {
            "temp": 23.0,
            "humidity": 96.0,
            "is_day": False,
        },
    })
    metrics = snapshots[0]["metrics"]
    assert metrics["weather.rain_mm"] == 3.2
    assert metrics["weather.solar_energy_mj_m2"] == 21.5
    assert metrics["weather.night_humidity_mean_pct"] == 96.0
    assert metrics["weather.hours_rh_ge_95pct"] == 1.0

    connection = sqlite3.connect(":memory:")
    report = {
        "status": "success",
        "field_id": "field-1",
        "start": day.isoformat(),
        "end": day.isoformat(),
        "_research_daily": snapshots,
    }
    MODULE.persist_research_metrics(connection, [report])
    stored = connection.execute(
        "SELECT value FROM season_climate_metrics WHERE metric=?",
        ("weather.night_humidity_mean_pct",),
    ).fetchone()
    assert stored == (96.0,)


def test_harvest_date_is_not_inferred_from_weather_or_literature_alone():
    result = MODULE.harvest_readiness("Chardonnay", {"available": False})
    assert result["available"] is False
    assert result["recommended_harvest_date"] is None
    assert "titratable acidity and pH" in result["missing_evidence"]
    assert "candidate" in result["literature_role"].lower()
