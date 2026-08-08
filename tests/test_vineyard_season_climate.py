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
