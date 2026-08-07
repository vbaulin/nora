#!/usr/bin/env python3
"""Vineyard Guard research pack for the nora research agent.

This file contains no analysis code. Every vineyard question is expressed as
parameters for the engine's domain-neutral analyses, which is the point: the
canopy-wetness question, the station-criterion question and the alert-quality
question are ordinary shapes that happen to be wearing agronomy this time.

Domain-specific *language* stays in `proactive_field_agent`, which remains the
adapter that talks to the farmer. The pack only makes the questions visible to
the general engine so the board can research them during idle time.

The pack registers nothing when the private Goidanich checkout is absent, so a
board without the vineyard app simply has one fewer domain.
"""

import json
import os
import re
from pathlib import Path

# Mirrors black_rot.INFECTION_THRESHOLD and WETNESS_RH_THRESHOLD in Goidanich.
BLACK_ROT_INFECTION_THRESHOLD = 85.0
WETNESS_RH_THRESHOLD = 95.0

DEFAULT_REPO = "/root/.picoclaw/workspace/goidanich"
DEFAULT_STATE_DIR = "/root/.picoclaw/workspace/proactive_field"


def repo_path(context):
    incoming = (context or {}).get("params_in") or {}
    return str(incoming.get("repo_path") or os.environ.get("GOIDANICH_REPO") or DEFAULT_REPO)


def state_dir(context):
    incoming = (context or {}).get("params_in") or {}
    return str(incoming.get("state_dir") or DEFAULT_STATE_DIR)


def configured_fields(repo):
    """Read field ids and names without requiring a YAML parser on the board."""
    path = Path(repo) / "agent_config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:  # the test and desktop configurations are JSON-compatible
        parsed = json.loads(text)
        fields = parsed.get("fields") or []
        return [
            {"id": str(item["id"]), "name": str(item.get("name") or item["id"])}
            for item in fields if isinstance(item, dict) and item.get("id")
        ]
    except ValueError:
        pass
    try:
        import yaml
        parsed = yaml.safe_load(text) or {}
        fields = parsed.get("fields") or []
        return [
            {"id": str(item["id"]), "name": str(item.get("name") or item["id"])}
            for item in fields if isinstance(item, dict) and item.get("id")
        ]
    except Exception:
        pass
    fields = []
    for match in re.finditer(r"^\s*-\s+id:\s*(.+)$", text, flags=re.MULTILINE):
        identifier = match.group(1).strip().strip("'\"")
        if identifier:
            fields.append({"id": identifier, "name": identifier})
    return fields


def black_rot_source(repo, field_id, columns):
    return {
        "kind": "sqlite",
        "path": str(Path(repo) / "goidanich.db"),
        "table": "black_rot_daily_predictions",
        "columns": columns,
        "time_column": "day",
        "where": "field_id = ?",
        "where_values": [field_id],
        "label": f"black_rot_daily_predictions[{field_id}]",
        "limit": 2000,
    }


def field_coordinates(repo, field_id):
    """Coordinates for one field, when the configuration is JSON-compatible."""
    try:
        parsed = json.loads((Path(repo) / "agent_config.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for item in parsed.get("fields") or []:
        if isinstance(item, dict) and str(item.get("id")) == field_id:
            coordinates = item.get("coordinates") or {}
            latitude = coordinates.get("latitude")
            longitude = coordinates.get("longitude")
            if latitude is not None and longitude is not None:
                return [latitude, longitude]
    return None


def declare_questions(context):
    """The questions this domain always wants answered, one set per field."""
    repo = repo_path(context)
    database = Path(repo) / "goidanich.db"
    if not database.exists():
        return []
    questions = []
    for field in configured_fields(repo):
        field_id = field["id"]
        # Do the neighbours see black rot that this field's model does not?
        coordinates = field_coordinates(repo, field_id)
        if coordinates:
            questions.append({
                "subject": f"vineyard:{field_id}",
                "claim": (
                    f"neighbouring boards report confirmed disease near {field['name']} "
                    "while the local model stays below its alert threshold"
                ),
                "analysis": "neighbour_reports",
                "priority": 65,
                "params": {
                    "events": {
                        "kind": "sqlite",
                        "path": str(Path(repo) / "goidanich.db"),
                        "table": "peer_signals",
                        "columns": ["peer_id", "signal_type", "value", "metadata", "disease_id"],
                        "time_column": "timestamp",
                        "label": "peer board reports",
                        "limit": 400,
                    },
                    "origin": coordinates,
                    "time_key": "timestamp",
                    "label_key": "signal_type",
                    "accepted_labels": ["contagion", "disease"],
                    "metadata_key": "metadata",
                    "reporter_key": "peer_id",
                    "local_source": black_rot_source(repo, field_id, ["infection_index"]),
                    "local_key": "infection_index",
                    "alert_threshold": BLACK_ROT_INFECTION_THRESHOLD,
                    "local_radius_km": 5.0,
                    "regional_radius_km": 15.0,
                    "window_days": 14,
                    "open_question": (
                        "whether the confirmed regional signal is already present in this parcel"
                    ),
                },
            })
        # Is this season unlike the ones before it? The season-climate skill
        # already computes the averages and writes one artifact per year, so
        # the research engine reads those rather than recomputing anything.
        # Weekly: refreshing a season of weather is not an hourly job.
        for metric, label in (
            ("season.rain_total_mm", "rainfall"),
            ("indices.gdd_base10", "accumulated heat"),
        ):
            questions.append({
                "subject": f"vineyard:{field_id}",
                "claim": (
                    f"this season's {label} at {field['name']} is unlike previous seasons"
                ),
                "analysis": "baseline_deviation",
                "priority": 45,
                "params": {
                    "source": {
                        "kind": "glob",
                        "pattern": str(
                            Path(repo) / "results" / f"season_climate_{field_id}_*.json"
                        ),
                        "label": "season climate artifacts",
                        "limit": 40,
                        "refresh": {
                            "kind": "skill",
                            "name": "vineyard_season_climate",
                            "timeout": 170,
                            "params": {
                                "mode": "report",
                                "repo_path": repo,
                                "field": field_id,
                                "write_artifacts": True,
                            },
                        },
                    },
                    "key": metric,
                    # The report dates its season rather than naming a year.
                    "period_key": "end",
                    "period_slice": 4,
                    "min_interval_seconds": 7 * 24 * 3600,
                    "min_baseline": 3,
                    "open_question": (
                        f"what an unusual season for {label} means for this field"
                    ),
                },
            })
        # Can the forecast that drives the risk projection be trusted lately?
        questions.append({
            "subject": f"vineyard:{field_id}",
            "claim": (
                f"the weather forecast for {field['name']} has been drifting away from "
                "what the station later measured"
            ),
            "analysis": "source_disagreement",
            "priority": 50,
            "params": {
                "primary": {
                    "kind": "sqlite",
                    "path": str(Path(repo) / "goidanich.db"),
                    "table": "weather_forecast_daily",
                    "columns": ["temp"],
                    "time_column": "day",
                    "where": "field_id = ?",
                    "where_values": [field_id],
                    "label": "forecast temperature",
                    "limit": 2000,
                },
                "reference": black_rot_source(repo, field_id, ["temp"]),
                "key": "temp",
                "time_key": "day",
                "tolerance": 2.0,
                "disagreement_share_limit": 0.3,
                "open_question": (
                    "whether the forecast source still reflects this station"
                ),
                "options": [
                    {"id": "deeper_analysis", "cost": "none", "params": {}},
                ],
            },
        })
        questions.append({
            "subject": f"vineyard:{field_id}",
            "claim": (
                "the unmeasured canopy-wetness assumption changes a black-rot decision "
                f"in {field['name']}"
            ),
            "analysis": "threshold_materiality",
            "priority": 60,
            "params": {
                "source": black_rot_source(repo, field_id, [
                    "infection_index", "potential_infection_index", "measured_wet_hours",
                ]),
                "lower_key": "infection_index",
                "upper_key": "potential_infection_index",
                "threshold": BLACK_ROT_INFECTION_THRESHOLD,
                "time_key": "day",
                "resolved_key": "measured_wet_hours",
                "coverage_tolerance": 2,
                "open_question": (
                    "whether near-saturation hours actually wet the canopy in this field"
                ),
                "options": [
                    {"id": "observe_at_next_event", "cost": "none", "params": {}},
                ],
            },
        })
        questions.append({
            "subject": f"vineyard:{field_id}",
            "claim": (
                f"the {WETNESS_RH_THRESHOLD:g}% humidity criterion is unreachable at the "
                f"station serving {field['name']}"
            ),
            "analysis": "ceiling_saturation",
            "priority": 55,
            "params": {
                "source": black_rot_source(repo, field_id, ["max_humi"]),
                "key": "max_humi",
                "criterion": WETNESS_RH_THRESHOLD,
                "time_key": "day",
                "open_question": (
                    "whether the wetness criterion is reachable at this station at all"
                ),
                "options": [
                    {"id": "compare_second_source", "cost": "none", "params": {}},
                ],
            },
        })
    return questions


def calibration_sources(context):
    """Where the engine finds this domain's alerts and confirmed outcomes."""
    state = Path(state_dir(context))
    database = state / "proactive_field.db"
    if not database.exists():
        return {}
    repo = repo_path(context)
    sources = {}
    for field in configured_fields(repo):
        sources[f"vineyard:{field['id']}"] = {
            "alerts": {
                "kind": "sqlite", "path": str(database), "table": "proposals",
                "columns": ["notified_at", "kind"], "time_column": "notified_at",
                "where": "field_id = ?", "where_values": [field["id"]],
                "label": "proactive proposals",
            },
            "outcomes": {
                "kind": "sqlite", "path": str(database), "table": "operations",
                "columns": ["occurred_at", "operation_type"], "time_column": "occurred_at",
                "where": "field_id = ?", "where_values": [field["id"]],
                "label": "confirmed farmer outcomes",
            },
            "time_key": "notified_at",
            "outcome_time_key": "occurred_at",
            "outcome_key": "operation_type",
            "positive_labels": [
                "detected_black_rot", "detected_mildew",
                "grade_1", "grade_2", "grade_3", "grade_4",
            ],
            "negative_labels": ["clean_inspection", "false_alarm"],
            "min_labels": 4,
            "open_question": "how many alerts this field should produce",
            "options": [
                {"id": "raise_alert_threshold", "cost": "none", "params": {}},
                {"id": "keep_alert_threshold", "cost": "none", "params": {}},
            ],
        }
    return sources


def evidence_paths(context):
    """Files whose mtime tells the engine whether anything here is new."""
    repo = Path(repo_path(context))
    state = Path(state_dir(context))
    return [
        str(path) for path in (
            repo / "goidanich.db",
            repo / "agent_config.yaml",
            state / "proactive_field.db",
        )
    ]


PACK = {
    "name": "vineyard_guard",
    "description": (
        "Grapevine disease boards: canopy-wetness uncertainty, station criteria, "
        "and the quality of the board's own alerts."
    ),
    "questions": declare_questions,
    "calibration_sources": calibration_sources,
    "evidence_paths": evidence_paths,
    "journal_dirs": ["/tmp/monitors/vineyard"],
}
