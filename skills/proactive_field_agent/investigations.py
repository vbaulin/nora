#!/usr/bin/env python3
"""Bounded field investigations for the proactive field agent.

An open question is not a reason to ask the farmer for hardware. Before any
message is written, each detected pattern becomes an investigation over
evidence the board already holds: the disease model series in the Goidanich
SQLite database, peer board signals, confirmed farmer observations, and the
board's own alert history.

Every investigation records the question it asked, the method it ran, the
sample it used, what it concluded, and what it cannot establish. Only a
question that stayed open *and* would change a field decision reaches the
farmer, and it arrives with the finding attached and the cheapest resolution
first. A hardware purchase is never the first option and is never repeated.
"""

import datetime as dt
import hashlib
import json
import math
import sqlite3
from pathlib import Path

# VitiMeteo black-rot model constants mirrored from the Goidanich model. They
# are duplicated deliberately: the board must be able to interpret stored model
# output without importing the disease repository.
INFECTION_THRESHOLD = 85.0
WETNESS_RH_THRESHOLD = 95.0
NEAR_SATURATION_RH_THRESHOLD = 90.0

DEFAULT_WINDOW_DAYS = 120
MIN_WETNESS_SAMPLE_DAYS = 14
COVERAGE_TOLERANCE_DAYS = 2
SYSTEMATIC_NEAR_SATURATION_HOURS = 12

PEER_WINDOW_DAYS = 14
LOCAL_PEER_RADIUS_KM = 5.0
REGIONAL_PEER_RADIUS_KM = 15.0
RECENT_INSPECTION_DAYS = 7

MIN_CALIBRATION_LABELS = 4
CALIBRATION_WINDOW_DAYS = 180

VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_NOT_MATERIAL = "not_material"
VERDICT_RESOLVED_LOCAL = "resolved_local"
VERDICT_MATERIAL = "material_unresolved"

TOPIC_WETNESS = "leaf_wetness_proxy"
TOPIC_PEER = "peer_signal_divergence"
TOPIC_CALIBRATION = "alert_calibration"

CONFIRMED_SYMPTOM_TYPES = {
    "detected_black_rot", "detected_mildew", "grade_1", "grade_2",
    "grade_3", "grade_4", "disease",
}
CLEAN_INSPECTION_TYPES = {"clean_inspection", "no_symptoms"}
FALSE_ALARM_TYPES = {"false_alarm"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso_now():
    return utcnow().isoformat()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_day(value):
    text = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def parse_moment(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def table_columns(connection, table):
    if connection is None:
        return []
    try:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def open_field_db(repo_path):
    """Open the Goidanich database read-only; return None when unavailable."""
    source = Path(repo_path or "") / "goidanich.db"
    if not source.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    return connection


def haversine_km(first, second):
    try:
        lat1, lon1 = float(first[0]), float(first[1])
        lat2, lon2 = float(second[0]), float(second[1])
    except (TypeError, ValueError, IndexError):
        return None
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    inner = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return round(2 * radius * math.asin(min(1.0, math.sqrt(inner))), 3)


def ensure_tables(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS investigations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT,
            topic TEXT NOT NULL,
            question TEXT NOT NULL,
            method TEXT NOT NULL,
            window_start TEXT,
            window_end TEXT,
            sample_size INTEGER NOT NULL DEFAULT 0,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            findings_json TEXT NOT NULL,
            limitations_json TEXT NOT NULL,
            options_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            internal_actions_json TEXT NOT NULL,
            open_question TEXT,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_investigations_field_topic
            ON investigations(field_id, topic, created_at DESC);
        """
    )
    connection.commit()


def investigation_dict(row):
    item = dict(row)
    for column, key in (
        ("findings_json", "findings"),
        ("limitations_json", "limitations"),
        ("options_json", "options"),
        ("evidence_json", "evidence"),
        ("internal_actions_json", "internal_actions"),
    ):
        try:
            item[key] = json.loads(item.pop(column))
        except (KeyError, ValueError):
            item[key] = []
    return item


def store_investigation(connection, finding):
    """Insert a finding, or refresh the window of an unchanged conclusion."""
    now = iso_now()
    fingerprint = digest({
        "field_id": finding.get("field_id"),
        "topic": finding["topic"],
        "verdict": finding["verdict"],
        "headline": finding.get("headline") or {},
    })
    existing = connection.execute(
        "SELECT * FROM investigations WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    values = (
        finding.get("window_end"), int(finding.get("sample_size") or 0),
        float(finding.get("confidence") or 0.0),
        json_text(finding.get("findings") or {}),
        json_text(finding.get("limitations") or []),
        json_text(finding.get("options") or []),
        json_text(finding.get("evidence") or []),
        json_text(finding.get("internal_actions") or []),
        finding.get("open_question"), now,
    )
    if existing:
        connection.execute(
            """
            UPDATE investigations SET
                window_end=?, sample_size=?, confidence=?, findings_json=?,
                limitations_json=?, options_json=?, evidence_json=?,
                internal_actions_json=?, open_question=?, updated_at=?
            WHERE fingerprint=?
            """,
            values + (fingerprint,),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM investigations WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        record = investigation_dict(row)
        record["created"] = False
        return record
    connection.execute(
        """
        INSERT INTO investigations(
            field_id, topic, question, method, window_start, window_end,
            sample_size, verdict, confidence, findings_json, limitations_json,
            options_json, evidence_json, internal_actions_json, open_question,
            status, fingerprint, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            finding.get("field_id"), finding["topic"], finding["question"],
            finding["method"], finding.get("window_start"), finding.get("window_end"),
            int(finding.get("sample_size") or 0), finding["verdict"],
            float(finding.get("confidence") or 0.0),
            json_text(finding.get("findings") or {}),
            json_text(finding.get("limitations") or []),
            json_text(finding.get("options") or []),
            json_text(finding.get("evidence") or []),
            json_text(finding.get("internal_actions") or []),
            finding.get("open_question"), "open", fingerprint, now, now,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM investigations WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    record = investigation_dict(row)
    record["created"] = True
    return record


def investigation_by_id(connection, investigation_id):
    row = connection.execute(
        "SELECT * FROM investigations WHERE id=?", (int(investigation_id),)
    ).fetchone()
    return investigation_dict(row) if row else None


def list_investigations(connection, field_id=None, topic=None, limit=20):
    clauses = []
    values = []
    if field_id:
        clauses.append("field_id=?")
        values.append(field_id)
    if topic:
        clauses.append("topic=?")
        values.append(topic)
    query = "SELECT * FROM investigations"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT ?"
    values.append(int(limit))
    return [investigation_dict(row) for row in connection.execute(query, values)]


def mark_investigation(connection, investigation_id, status):
    connection.execute(
        "UPDATE investigations SET status=?, updated_at=? WHERE id=?",
        (status, iso_now(), int(investigation_id)),
    )
    connection.commit()


def wetness_rows(field_db, field_id, window_days=DEFAULT_WINDOW_DAYS):
    """Daily black-rot model rows with both the confirmed and upper-bound index."""
    columns = set(table_columns(field_db, "black_rot_daily_predictions"))
    required = {
        "day", "infection_index", "potential_infection_index",
        "near_saturation_hours", "measured_wet_hours", "humidity_wet_hours",
    }
    if not required.issubset(columns):
        return None
    optional = [
        name for name in ("rain_wet_hours", "rain", "max_humi", "infection_event")
        if name in columns
    ]
    selected = [
        "MAX(infection_index) AS infection_index",
        "MAX(potential_infection_index) AS potential_infection_index",
        "MAX(near_saturation_hours) AS near_saturation_hours",
        "MAX(measured_wet_hours) AS measured_wet_hours",
        "MAX(humidity_wet_hours) AS humidity_wet_hours",
    ] + [f"MAX({name}) AS {name}" for name in optional]
    try:
        last = field_db.execute(
            "SELECT MAX(day) FROM black_rot_daily_predictions WHERE field_id=?",
            (field_id,),
        ).fetchone()[0]
    except sqlite3.Error:
        return None
    last_day = parse_day(last)
    if not last_day:
        return []
    start = (last_day - dt.timedelta(days=int(window_days))).isoformat()
    try:
        rows = field_db.execute(
            "SELECT day, " + ", ".join(selected) +
            " FROM black_rot_daily_predictions WHERE field_id=? AND day>=?"
            " GROUP BY day ORDER BY day",
            (field_id, start),
        ).fetchall()
    except sqlite3.Error:
        return None
    return [dict(row) for row in rows]


def investigate_leaf_wetness(ctx):
    """Does the unmeasured-wetness assumption change any decision in this field?

    The board holds both the confirmed VitiMeteo index (rain or RH>=95%) and a
    conservative upper bound that also counts near-saturated air. The question
    is not whether a sensor would be nice; it is whether the two series ever
    disagree in a way that changes what the farmer would do.
    """
    profile = ctx["profile"]
    field_id = profile["field_id"]
    watch_now = any(
        bool(item["payload"].get("black_rot_wetness_uncertain_watch"))
        for item in ctx.get("observations") or []
        if item.get("kind") == "disease_state:black_rot"
    )
    rows = wetness_rows(ctx.get("field_db"), field_id, ctx.get("window_days", DEFAULT_WINDOW_DAYS))
    question = (
        "Does the unmeasured canopy-wetness assumption change any black-rot "
        "decision in this field?"
    )
    base = {
        "topic": TOPIC_WETNESS,
        "field_id": field_id,
        "question": question,
        "limitations": [
            "A humidity proxy cannot prove canopy wetness; this bounds the effect, it does not measure it.",
            "Model output only; no infection was confirmed in the field by this analysis.",
        ],
        "evidence": [{
            "source_ref": f"{ctx.get('repo_path')}/goidanich.db:black_rot_daily_predictions",
            "field_id": field_id,
        }],
    }
    if rows is None:
        if not watch_now:
            return None
        return dict(base, **{
            "method": "Requested the stored daily black-rot series; the confirmed/upper-bound comparison is unavailable on this board.",
            "verdict": VERDICT_INSUFFICIENT,
            "confidence": 0.0,
            "sample_size": 0,
            "findings": {"reason": "black_rot_daily_predictions missing or pre-migration"},
            "headline": {"reason": "series_unavailable"},
            "options": [],
            "internal_actions": [{
                "action": "refresh_black_rot_series",
                "detail": "Run the black-rot model so the confirmed and upper-bound indices can be compared.",
            }],
        })
    if not rows:
        return None

    days = len(rows)
    window_start = rows[0]["day"]
    window_end = rows[-1]["day"]
    measured_days = sum(1 for row in rows if as_int(row.get("measured_wet_hours")) > 0)
    near_saturation_hours = sum(as_int(row.get("near_saturation_hours")) for row in rows)
    rh95_hours = sum(as_int(row.get("humidity_wet_hours")) for row in rows)
    rain_wet_hours = sum(as_int(row.get("rain_wet_hours")) for row in rows)
    confirmed_days = sorted(
        parse_day(row["day"]) for row in rows
        if as_float(row.get("infection_index")) >= INFECTION_THRESHOLD
    )
    confirmed_days = [day for day in confirmed_days if day]

    uncertain = [
        row for row in rows
        if as_float(row.get("infection_index")) < INFECTION_THRESHOLD
        and as_float(row.get("potential_infection_index")) >= INFECTION_THRESHOLD
        and as_int(row.get("near_saturation_hours")) > 0
    ]

    def covered_by_confirmed_signal(row):
        day = parse_day(row["day"])
        if not day:
            return False
        return any(
            abs((day - other).days) <= COVERAGE_TOLERANCE_DAYS
            for other in confirmed_days
        )

    covered = [row for row in uncertain if covered_by_confirmed_signal(row)]
    open_days = [row for row in uncertain if row not in covered]
    max_potential = max((as_float(row.get("potential_infection_index")) for row in open_days), default=0.0)
    max_primary = max((as_float(row.get("infection_index")) for row in open_days), default=0.0)
    systematic = rh95_hours == 0 and near_saturation_hours >= SYSTEMATIC_NEAR_SATURATION_HOURS

    findings = {
        "days_analyzed": days,
        "measured_wetness_days": measured_days,
        "uncertain_days": len(uncertain),
        "uncertain_days_covered_by_confirmed_signal": len(covered),
        "unresolved_days": len(open_days),
        "unresolved_day_list": [row["day"] for row in open_days][:10],
        "max_upper_bound_index": round(max_potential, 1),
        "max_confirmed_index_on_unresolved_days": round(max_primary, 1),
        "infection_threshold": INFECTION_THRESHOLD,
        "hours_rh_at_or_above_95": rh95_hours,
        "hours_rh_between_90_and_95": near_saturation_hours,
        "rain_wet_hours": rain_wet_hours,
        "station_never_reaches_wetness_threshold": systematic,
    }
    method = (
        f"Compared the confirmed VitiMeteo infection index against the upper-bound index "
        f"over {days} modelled days ({window_start} to {window_end}), then checked whether "
        f"each ambiguous day was already covered by a confirmed threshold crossing within "
        f"{COVERAGE_TOLERANCE_DAYS} days."
    )
    common = dict(base, **{
        "method": method,
        "window_start": window_start,
        "window_end": window_end,
        "sample_size": days,
        "findings": findings,
    })

    if measured_days:
        return dict(common, **{
            "verdict": VERDICT_RESOLVED_LOCAL,
            "confidence": 1.0,
            "headline": {"measured": True},
            "options": [],
            "internal_actions": [],
        })
    if days < MIN_WETNESS_SAMPLE_DAYS:
        return dict(common, **{
            "verdict": VERDICT_INSUFFICIENT,
            "confidence": 0.2,
            "headline": {"days": days},
            "options": [],
            "internal_actions": [],
        })
    if not uncertain:
        return dict(common, **{
            "verdict": VERDICT_NOT_MATERIAL,
            "confidence": min(1.0, round(days / 60.0, 2)),
            "headline": {"uncertain_days": 0},
            "options": [],
            "internal_actions": [],
        })
    if not open_days:
        return dict(common, **{
            "verdict": VERDICT_NOT_MATERIAL,
            "confidence": min(1.0, round(days / 60.0, 2)),
            "headline": {"uncertain_days": len(uncertain), "unresolved_days": 0},
            "options": [],
            "internal_actions": [],
        })

    options = [{"id": "same_day_canopy_check", "cost": "none", "params": {}}]
    peer = ctx.get("wetness_reference_peer")
    if peer:
        options.append({"id": "peer_reference_series", "cost": "none", "params": peer})
    if ctx.get("hardware_option_allowed", True):
        options.append({"id": "leaf_wetness_sensor", "cost": "hardware", "params": {}})
    internal_actions = []
    if systematic:
        internal_actions.append({
            "action": "queue_research",
            "query": (
                "leaf wetness proxy threshold validation relative humidity 90 95 percent "
                "grapevine black rot Guignardia bidwellii VitiMeteo"
            ),
            "reason": (
                "The station never reached the RH>=95% wetness criterion while accumulating "
                "near-saturation hours, so the proxy threshold itself is the open question."
            ),
        })
    return dict(common, **{
        "verdict": VERDICT_MATERIAL,
        "confidence": min(0.9, round(0.4 + 0.1 * len(open_days), 2)),
        "headline": {
            "unresolved_days": len(open_days),
            "systematic": systematic,
        },
        "open_question": (
            "whether near-saturation hours actually wet the canopy in this field, or whether "
            "the RH>=95% criterion is simply unreachable at this station"
            if systematic else
            "whether near-saturation hours actually wet the canopy in this field"
        ),
        "options": options,
        "internal_actions": internal_actions,
    })


def local_disease_state(observations, disease):
    for item in observations or []:
        if item.get("kind") == f"disease_state:{disease}":
            return item.get("payload") or {}
    return {}


def local_alert_value(payload, disease):
    if disease == "downy_mildew":
        value = max(
            as_float(payload.get("goidanich_daily_risk")),
            as_float(payload.get("rossi_risk")),
        )
        return value, value >= 50.0, "%"
    if disease == "powdery_mildew":
        value = as_float(payload.get("powdery_uc_risk"))
        return value, value >= 50.0 or bool(payload.get("powdery_pmi_treatment_due")), "%"
    if disease == "black_rot":
        value = as_float(payload.get("black_rot_infection_index"))
        forecast = as_float(payload.get("forecast_max"))
        return value, max(value, forecast) >= INFECTION_THRESHOLD, "dh"
    return 0.0, False, ""


def peer_events(field_db, coordinates, window_days=PEER_WINDOW_DAYS, now=None):
    """Confirmed disease signals pulled from other boards, with distance."""
    if not table_columns(field_db, "peer_signals"):
        return None
    moment = now or utcnow()
    since = (moment - dt.timedelta(days=int(window_days))).isoformat()
    try:
        rows = field_db.execute(
            "SELECT timestamp, peer_id, signal_type, value, metadata, disease_id "
            "FROM peer_signals WHERE timestamp>=? ORDER BY timestamp DESC LIMIT 400",
            (since,),
        ).fetchall()
    except sqlite3.Error:
        return None
    topology = {}
    if table_columns(field_db, "topology"):
        try:
            for row in field_db.execute(
                "SELECT id, name, lat, lon, distance_km FROM topology"
            ):
                topology[str(row["id"])] = dict(row)
        except sqlite3.Error:
            topology = {}
    events = []
    for row in rows:
        if str(row["signal_type"] or "").lower() not in {"contagion", "disease"}:
            continue
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        peer_id = str(row["peer_id"] or "")
        known = topology.get(peer_id) or {}
        distance = None
        if metadata.get("latitude") is not None and metadata.get("longitude") is not None:
            distance = haversine_km(coordinates, (metadata.get("latitude"), metadata.get("longitude")))
        if distance is None and known.get("lat") is not None:
            distance = haversine_km(coordinates, (known.get("lat"), known.get("lon")))
        if distance is None and known.get("distance_km") is not None:
            distance = as_float(known.get("distance_km"), None)
        events.append({
            "peer_id": peer_id,
            "peer_name": str(known.get("name") or metadata.get("board_id") or peer_id),
            "day": str(row["timestamp"] or "")[:10],
            "disease": str(row["disease_id"] or metadata.get("disease_id") or ""),
            "severity": as_float(row["value"]),
            "event_type": str(metadata.get("event_type") or "disease"),
            "distance_km": distance,
        })
    return events


def recent_confirmed_inspection(connection, field_id, days=RECENT_INSPECTION_DAYS, now=None):
    moment = now or utcnow()
    since = (moment - dt.timedelta(days=int(days))).isoformat()
    row = connection.execute(
        "SELECT occurred_at, operation_type FROM operations "
        "WHERE field_id=? AND occurred_at>=? ORDER BY occurred_at DESC LIMIT 1",
        (field_id, since),
    ).fetchone()
    return dict(row) if row else None


def last_confirmed_inspection(connection, field_id):
    row = connection.execute(
        "SELECT occurred_at, operation_type FROM operations "
        "WHERE field_id=? ORDER BY occurred_at DESC LIMIT 1",
        (field_id,),
    ).fetchone()
    return dict(row) if row else None


def investigate_peer_divergence(ctx):
    """Do nearby boards see something this field's model does not?

    A neighbour confirmation is evidence about that parcel. It raises the prior
    for this one, it never confirms anything here. The investigation states the
    disagreement in distance, dates and model values, and asks for the one
    cheap measurement that settles it: a targeted inspection.
    """
    profile = ctx["profile"]
    field_id = profile["field_id"]
    coordinates = ctx.get("coordinates")
    events = peer_events(ctx.get("field_db"), coordinates, now=ctx.get("now"))
    if events is None or not coordinates:
        return None
    base = {
        "topic": TOPIC_PEER,
        "field_id": field_id,
        "question": "Do nearby boards report confirmed disease that this field's model does not predict?",
        "limitations": [
            "A peer confirmation is evidence about that parcel, not this one; it raises prior probability only.",
            "Peer distance is derived from reported coordinates and can be approximate.",
        ],
        "evidence": [{
            "source_ref": f"{ctx.get('repo_path')}/goidanich.db:peer_signals",
            "events": len(events),
        }],
        "method": (
            f"Compared confirmed peer board events from the last {PEER_WINDOW_DAYS} days "
            "against the current local model value for the same disease."
        ),
        "window_end": str(ctx.get("now") or utcnow())[:10],
    }
    if not events:
        return None

    located = [item for item in events if item.get("distance_km") is not None]
    near = [item for item in located if item["distance_km"] <= REGIONAL_PEER_RADIUS_KM]
    if not located:
        return dict(base, **{
            "verdict": VERDICT_INSUFFICIENT,
            "confidence": 0.2,
            "sample_size": len(events),
            "findings": {
                "peer_events": len(events),
                "reason": "no peer event carried a resolvable location",
            },
            "headline": {"reason": "no_located_peer"},
            "options": [],
            "internal_actions": [],
        })
    if not near:
        nearest = min(item["distance_km"] for item in located)
        return dict(base, **{
            "verdict": VERDICT_NOT_MATERIAL,
            "confidence": 0.5,
            "sample_size": len(located),
            "findings": {
                "peer_events": len(located),
                "nearest_km": round(nearest, 1),
                "regional_radius_km": REGIONAL_PEER_RADIUS_KM,
                "reason": "the nearest confirmed peer event is outside the regional radius",
            },
            "headline": {"reason": "outside_regional_radius"},
            "options": [],
            "internal_actions": [],
        })

    by_disease = {}
    for item in near:
        by_disease.setdefault(item["disease"] or "unknown", []).append(item)
    divergent = []
    agreeing = []
    for disease, items in sorted(by_disease.items()):
        payload = local_disease_state(ctx.get("observations"), disease)
        value, in_alert, unit = local_alert_value(payload, disease)
        nearest = min(item["distance_km"] for item in items)
        summary = {
            "disease": disease,
            "peer_events": len(items),
            "peer_boards": sorted({item["peer_name"] for item in items}),
            "nearest_km": round(nearest, 1),
            "first_day": min(item["day"] for item in items),
            "last_day": max(item["day"] for item in items),
            "local_value": round(value, 1),
            "local_unit": unit,
            "local_in_alert": in_alert,
            "local_model_available": bool(payload),
        }
        if payload and not in_alert and nearest <= LOCAL_PEER_RADIUS_KM:
            divergent.append(summary)
        else:
            agreeing.append(summary)

    inspection = recent_confirmed_inspection(ctx["connection"], field_id, now=ctx.get("now"))
    last_inspection = last_confirmed_inspection(ctx["connection"], field_id)
    findings = {
        "peer_events_in_window": len(near),
        "divergent": divergent,
        "consistent": agreeing,
        "recent_local_inspection": inspection,
        "last_local_inspection_day": str((last_inspection or {}).get("occurred_at") or "")[:10] or None,
        "local_radius_km": LOCAL_PEER_RADIUS_KM,
    }
    common = dict(base, **{"sample_size": len(near), "findings": findings})
    if not divergent or inspection:
        return dict(common, **{
            "verdict": VERDICT_NOT_MATERIAL,
            "confidence": 0.6,
            "headline": {
                "divergent": [item["disease"] for item in divergent],
                "inspected": bool(inspection),
            },
            "options": [],
            "internal_actions": [],
        })
    lead = divergent[0]
    return dict(common, **{
        "verdict": VERDICT_MATERIAL,
        "confidence": 0.6,
        "headline": {
            "divergent": [item["disease"] for item in divergent],
            "nearest_km": lead["nearest_km"],
        },
        "open_question": (
            "whether the confirmed regional signal is already present in this parcel"
        ),
        "options": [
            {"id": "targeted_inspection", "cost": "none", "params": {"disease": lead["disease"]}},
            {"id": "share_peer_context", "cost": "none", "params": {}},
        ],
        "internal_actions": [],
    })


def investigate_alert_calibration(ctx):
    """Are the board's own alerts earning the farmer's attention?

    The board audits the alerts it already sent against the confirmed outcomes
    that came back. A run of clean inspections is a result about the board, not
    about the farmer, and the correction it justifies is fewer messages.
    """
    connection = ctx["connection"]
    profile = ctx["profile"]
    field_id = profile["field_id"]
    moment = ctx.get("now") or utcnow()
    since = (moment - dt.timedelta(days=CALIBRATION_WINDOW_DAYS)).isoformat()
    alerts = connection.execute(
        "SELECT id, kind, notified_at FROM proposals "
        "WHERE field_id=? AND kind='field_check' AND notified_at IS NOT NULL "
        "AND notified_at>=? ORDER BY notified_at",
        (field_id, since),
    ).fetchall()
    if not alerts:
        return None
    operations = connection.execute(
        "SELECT operation_type, occurred_at FROM operations "
        "WHERE field_id=? AND occurred_at>=? ORDER BY occurred_at",
        (field_id, since),
    ).fetchall()
    outcomes = []
    for row in operations:
        kind = str(row["operation_type"] or "").strip().lower()
        if kind in CONFIRMED_SYMPTOM_TYPES:
            outcomes.append((row["occurred_at"], "confirmed"))
        elif kind in CLEAN_INSPECTION_TYPES:
            outcomes.append((row["occurred_at"], "clean"))
        elif kind in FALSE_ALARM_TYPES:
            outcomes.append((row["occurred_at"], "false_alarm"))
    answered = 0
    tally = {"confirmed": 0, "clean": 0, "false_alarm": 0}
    used = set()
    for alert in alerts:
        sent = parse_moment(alert["notified_at"])
        if not sent:
            continue
        for index, (occurred_at, label) in enumerate(outcomes):
            if index in used:
                continue
            occurred = parse_moment(occurred_at)
            if not occurred or occurred < sent:
                continue
            if (occurred - sent).days > RECENT_INSPECTION_DAYS:
                continue
            used.add(index)
            answered += 1
            tally[label] += 1
            break
    findings = {
        "alerts_sent": len(alerts),
        "alerts_answered": answered,
        "confirmed_symptoms": tally["confirmed"],
        "clean_inspections": tally["clean"],
        "false_alarms": tally["false_alarm"],
        "window_days": CALIBRATION_WINDOW_DAYS,
        "response_window_days": RECENT_INSPECTION_DAYS,
    }
    base = {
        "topic": TOPIC_CALIBRATION,
        "field_id": field_id,
        "question": "Do the alerts this board sends match what the farmer finds in the field?",
        "method": (
            f"Matched every notified field check in the last {CALIBRATION_WINDOW_DAYS} days "
            f"against confirmed farmer outcomes recorded within {RECENT_INSPECTION_DAYS} days of the message."
        ),
        "limitations": [
            "A clean inspection calibrates this field on that date; it does not prove the model wrong in general.",
            "An unanswered alert is not counted as either a hit or a miss.",
        ],
        "evidence": [{"source_ref": "proactive_field.db:proposals+operations", "alerts": len(alerts)}],
        "window_end": str(moment)[:10],
        "sample_size": answered,
        "findings": findings,
    }
    if answered < MIN_CALIBRATION_LABELS:
        return dict(base, **{
            "verdict": VERDICT_INSUFFICIENT,
            "confidence": 0.2,
            "headline": {"answered": answered},
            "options": [],
            "internal_actions": [],
        })
    negatives = tally["clean"] + tally["false_alarm"]
    if tally["confirmed"] == 0 and negatives >= MIN_CALIBRATION_LABELS:
        return dict(base, **{
            "verdict": VERDICT_MATERIAL,
            "confidence": min(0.9, round(0.5 + 0.05 * negatives, 2)),
            "headline": {"answered": answered, "confirmed": 0},
            "open_question": "whether this field's alert threshold is set too low for local conditions",
            "options": [
                {"id": "raise_alert_threshold", "cost": "none", "params": {}},
                {"id": "keep_alert_threshold", "cost": "none", "params": {}},
            ],
            "internal_actions": [],
        })
    return dict(base, **{
        "verdict": VERDICT_NOT_MATERIAL,
        "confidence": 0.6,
        "headline": {"answered": answered, "confirmed": tally["confirmed"]},
        "options": [],
        "internal_actions": [],
    })


INVESTIGATORS = (
    investigate_leaf_wetness,
    investigate_peer_divergence,
    investigate_alert_calibration,
)


def field_coordinates(profile):
    raw = (profile.get("profile") or {}).get("coordinates") or {}
    latitude = raw.get("latitude", raw.get("lat"))
    longitude = raw.get("longitude", raw.get("lon"))
    if latitude is None or longitude is None:
        return None
    return (as_float(latitude, None), as_float(longitude, None))


def run_investigations(connection, profile, repo_path, observations, now=None,
                       window_days=DEFAULT_WINDOW_DAYS, hardware_option_allowed=True,
                       wetness_reference_peer=None):
    """Run every investigator for one field and store the findings."""
    ensure_tables(connection)
    field_db = open_field_db(repo_path)
    ctx = {
        "connection": connection,
        "field_db": field_db,
        "profile": profile,
        "repo_path": repo_path,
        "observations": observations or [],
        "now": now or utcnow(),
        "window_days": window_days,
        "coordinates": field_coordinates(profile),
        "hardware_option_allowed": hardware_option_allowed,
        "wetness_reference_peer": wetness_reference_peer,
    }
    records = []
    try:
        for investigator in INVESTIGATORS:
            try:
                finding = investigator(ctx)
            except sqlite3.Error as exc:
                finding = None
                records.append({"topic": getattr(investigator, "__name__", "unknown"),
                                "error": str(exc), "verdict": VERDICT_INSUFFICIENT})
                continue
            if finding:
                records.append(store_investigation(connection, finding))
    finally:
        if field_db is not None:
            try:
                field_db.close()
            except sqlite3.Error:
                pass
    return records


# ---------------------------------------------------------------------------
# Farmer-facing rendering
#
# The message must show the work: what was checked, over how much data, what
# came out, and what remains open. Options are ordered by cost and the farmer
# is always allowed to answer "nothing for now".
# ---------------------------------------------------------------------------

OPTION_TEXTS = {
    "same_day_canopy_check": {
        "ca": "que un matí d'avís mireu si les fulles són mullades a primera hora (amb 3 observacions puc calibrar el llindar d'aquest camp)",
        "es": "que en una mañana de aviso mire si las hojas están mojadas a primera hora (con 3 observaciones puedo calibrar el umbral de este campo)",
        "en": "on a flagged morning, check whether the leaves are wet at first light (three observations calibrate this field's threshold)",
    },
    "peer_reference_series": {
        "ca": "que demani al tauler de {peer_name} ({distance_km} km) la seva sèrie d'humectació mesurada per comparar-la amb la nostra humitat",
        "es": "que pida al tablero de {peer_name} ({distance_km} km) su serie de humectación medida para compararla con nuestra humedad",
        "en": "let me request the measured wetness series from the {peer_name} board ({distance_km} km) and compare it with our humidity",
    },
    "leaf_wetness_sensor": {
        "ca": "instal·lar un sensor d'humectació foliar en aquest camp, si voleu una resposta permanent; no cal per continuar",
        "es": "instalar un sensor de humectación foliar en este campo, si quiere una respuesta permanente; no hace falta para continuar",
        "en": "install a leaf-wetness sensor in this field if you want a permanent answer; it is not needed to carry on",
    },
    "targeted_inspection": {
        "ca": "una inspecció dirigida de deu minuts a la zona més exposada i m'expliqueu què hi trobeu",
        "es": "una inspección dirigida de diez minutos en la zona más expuesta y me cuenta qué encuentra",
        "en": "a ten-minute targeted inspection of the most exposed area, and tell me what you find",
    },
    "share_peer_context": {
        "ca": "que us enviï les dates i distàncies exactes dels avisos veïns perquè decidiu vosaltres",
        "es": "que le envíe las fechas y distancias exactas de los avisos vecinos para que decida usted",
        "en": "let me send you the exact dates and distances of the neighbouring reports so you decide",
    },
    "deeper_analysis": {
        "ca": "que hi dediqui més temps jo mateix: repetir l'anàlisi sobre una finestra molt més llarga del registre i dir-vos si el patró es manté",
        "es": "que le dedique más tiempo yo mismo: repetir el análisis sobre una ventana mucho más larga del registro y decirle si el patrón se mantiene",
        "en": "let me spend more of my own time on it: repeat the analysis over a much longer window and tell you whether the pattern holds",
    },
    "run_measurement_task": {
        "ca": "que prepari un estudi de seguiment per comprovar-ho amb dades noves durant les properes setmanes (me'l deixo escrit i el reviseu abans que s'engegui)",
        "es": "que prepare un estudio de seguimiento para comprobarlo con datos nuevos durante las próximas semanas (lo dejo escrito y usted lo revisa antes de que arranque)",
        "en": "let me draft a follow-up study that checks this against new data over the coming weeks (I write it down and you review it before anything runs)",
    },
    "forecast_from_relationship": {
        "ca": "que us avisi per endavant la propera vegada que això torni a passar, dient-vos el dia previst i per què",
        "es": "que le avise por adelantado la próxima vez que esto vuelva a ocurrir, diciéndole el día previsto y por qué",
        "en": "warn me ahead of time the next time this happens, with the expected day and the reason",
    },
    "keep_watching": {
        "ca": "que segueixi vigilant-ho i us avisi si torna a passar",
        "es": "que siga vigilándolo y le avise si vuelve a ocurrir",
        "en": "keep watching it and tell me if it happens again",
    },
    "start_measurement": {
        "ca": "començar a mesurar-ho, si us sembla que val la pena; sense aquesta dada la pregunta es queda oberta",
        "es": "empezar a medirlo, si le parece que vale la pena; sin ese dato la pregunta se queda abierta",
        "en": "start measuring it, if you think it is worth it; without that value the question stays open",
    },
    "start_insect_counts": {
        "ca": "començar a registrar recomptes de trampes o observacions d'insectes, que és l'única manera que ho pugui comprovar",
        "es": "empezar a registrar conteos de trampas u observaciones de insectos, que es la única forma de que pueda comprobarlo",
        "en": "start recording trap counts or insect observations, which is the only way I could ever test it",
    },
    "check_source": {
        "ca": "que comproveu si l'aparell o la tasca que genera aquestes dades segueix funcionant",
        "es": "que compruebe si el aparato o la tarea que genera esos datos sigue funcionando",
        "en": "check whether the device or task producing this data is still running",
    },
    "compare_second_source": {
        "ca": "comparar-ho amb una segona font de dades quan n'hi hagi una de disponible",
        "es": "compararlo con una segunda fuente de datos cuando haya una disponible",
        "en": "compare it against a second source of the same quantity when one exists",
    },
    "confirm_context_change": {
        "ca": "que em digueu si va canviar alguna cosa en aquelles dates (posició, feina al camp, manteniment)",
        "es": "que me diga si cambió algo en esas fechas (posición, trabajo en campo, mantenimiento)",
        "en": "tell me whether anything changed around those dates (position, field work, maintenance)",
    },
    "observe_at_next_event": {
        "ca": "que feu una observació directa la propera vegada que passi",
        "es": "que haga una observación directa la próxima vez que ocurra",
        "en": "make one direct observation the next time it happens",
    },
    "raise_alert_threshold": {
        "ca": "pujar el llindar d'avís d'aquest camp perquè només us escrigui en senyals més forts",
        "es": "subir el umbral de aviso de este campo para escribirle solo con señales más fuertes",
        "en": "raise this field's alert threshold so I only write for stronger signals",
    },
    "keep_alert_threshold": {
        "ca": "deixar el llindar com està perquè preferiu veure tots els avisos",
        "es": "dejar el umbral como está porque prefiere ver todos los avisos",
        "en": "keep the threshold as it is because you prefer to see every alert",
    },
}

TEXTS = {
    "ca": {
        "wetness_material_title": "Humectació del dosser a {name}: què he comprovat",
        "wetness_material": (
            "{name}: abans d'escriure-us he analitzat {days} dies de model ({start} a {end}). "
            "En {uncertain} dies la humitat va quedar entre 90% i 95% sense pluja{covered}. "
            "Queden {open} dies sense resoldre "
            "(el límit superior arriba a {max_upper:.0f} graus-hora contra {max_lower:.0f} confirmats, "
            "llindar {threshold:.0f}): {open_days}. {systematic}"
            "El que no puc resoldre amb les meves dades és {question}."
        ),
        "wetness_covered_clause": (
            ", i en {covered} d'ells el senyal confirmat de pluja va creuar igualment el llindar, "
            "de manera que no canviaven cap decisió"
        ),
        "wetness_closed_title": "Humectació del dosser a {name}: tancat",
        "wetness_closed": (
            "{name}: tanco la comprovació d'humectació. He revisat {days} dies ({start} a {end}): "
            "{uncertain} amb ambigüitat, i en tots ells el senyal confirmat de pluja va creuar el llindar "
            "igualment en un marge de dos dies. Conclusió: aquesta temporada la incertesa d'humectació "
            "no ha canviat cap decisió de tractament en aquest camp i no proposo cap sensor. "
            "Reobriré la qüestió només si apareixen dies ambigus sense resoldre."
        ),
        "wetness_measured_title": "Humectació del dosser a {name}: resolt",
        "wetness_measured": (
            "{name}: aquest camp ja té hores d'humectació mesurades ({measured} dies), "
            "de manera que el model utilitza la mesura i no el proxy d'humitat. Tanco la qüestió."
        ),
        "wetness_systematic": (
            "A més, en {days} dies l'estació no ha registrat ni una hora amb humitat ≥95% tot i "
            "{near_hours} hores entre 90% i 95%: això apunta al llindar del model en aquesta estació, "
            "no a un fet puntual, i ja he obert una consulta de fonts sobre aquest llindar. "
        ),
        "peer_material_title": "Senyal de taulers veïns a prop de {name}",
        "peer_material": (
            "{name}: {events} avís(os) confirmat(s) de {boards} a {nearest} km entre el {first} i el {last} "
            "({disease}). El meu model per a aquest camp dona {local_value}{unit}, per sota del llindar d'avís, "
            "i no consta cap inspecció confirmada des de {last_inspection}. "
            "Una confirmació d'un altre tauler és evidència d'aquella parcel·la, no d'aquesta: "
            "puja la probabilitat a priori, no confirma res aquí. "
            "El que no puc resoldre des del tauler és {question}."
        ),
        "peer_closed_title": "Taulers veïns a prop de {name}: tancat",
        "peer_closed": "{name}: tanco l'avís dels taulers veïns. {reason}",
        "calibration_material_title": "Revisió dels meus propis avisos a {name}",
        "calibration_material": (
            "{name}: he auditat els {alerts} avisos que us he enviat i les {answered} respostes confirmades: "
            "{clean} inspeccions netes, {false_alarm} falsos avisos i {confirmed} amb símptomes compatibles. "
            "Amb aquest registre, el meu llindar actual us fa mirar el camp més sovint del que el resultat justifica. "
            "El que no puc decidir jo sol és {question}."
        ),
        "options_intro": "Opcions, de menys a més cost:",
        "closing": (
            "Amb quina voleu començar? Si ara no us va bé cap, responeu «cap» i ho deixo tancat; "
            "només us ho tornaré a plantejar si el patró canvia."
        ),
        "no_hardware_note": "No proposo comprar res per resoldre-ho.",
    },
    "es": {
        "wetness_material_title": "Humedad del dosel en {name}: qué he comprobado",
        "wetness_material": (
            "{name}: antes de escribirle he analizado {days} días de modelo ({start} a {end}). "
            "En {uncertain} días la humedad quedó entre 90% y 95% sin lluvia{covered}. "
            "Quedan {open} días sin resolver "
            "(el límite superior llega a {max_upper:.0f} grados-hora frente a {max_lower:.0f} confirmados, "
            "umbral {threshold:.0f}): {open_days}. {systematic}"
            "Lo que no puedo resolver con mis datos es {question}."
        ),
        "wetness_covered_clause": (
            ", y en {covered} de ellos la señal confirmada de lluvia cruzó igualmente el umbral, "
            "así que no cambiaban ninguna decisión"
        ),
        "wetness_closed_title": "Humedad del dosel en {name}: cerrado",
        "wetness_closed": (
            "{name}: cierro la comprobación de humectación. He revisado {days} días ({start} a {end}): "
            "{uncertain} con ambigüedad, y en todos ellos la señal confirmada de lluvia cruzó el umbral "
            "igualmente en un margen de dos días. Conclusión: esta temporada la incertidumbre de humectación "
            "no ha cambiado ninguna decisión de tratamiento en este campo y no propongo ningún sensor. "
            "Reabriré la cuestión solo si aparecen días ambiguos sin resolver."
        ),
        "wetness_measured_title": "Humedad del dosel en {name}: resuelto",
        "wetness_measured": (
            "{name}: este campo ya tiene horas de humectación medidas ({measured} días), "
            "así que el modelo usa la medida y no el proxy de humedad. Cierro la cuestión."
        ),
        "wetness_systematic": (
            "Además, en {days} días la estación no ha registrado ni una hora con humedad ≥95% pese a "
            "{near_hours} horas entre 90% y 95%: eso apunta al umbral del modelo en esta estación, "
            "no a un hecho puntual, y ya he abierto una consulta de fuentes sobre ese umbral. "
        ),
        "peer_material_title": "Señal de tableros vecinos cerca de {name}",
        "peer_material": (
            "{name}: {events} aviso(s) confirmado(s) de {boards} a {nearest} km entre el {first} y el {last} "
            "({disease}). Mi modelo para este campo da {local_value}{unit}, por debajo del umbral de aviso, "
            "y no consta ninguna inspección confirmada desde {last_inspection}. "
            "Una confirmación de otro tablero es evidencia de aquella parcela, no de esta: "
            "sube la probabilidad a priori, no confirma nada aquí. "
            "Lo que no puedo resolver desde el tablero es {question}."
        ),
        "peer_closed_title": "Tableros vecinos cerca de {name}: cerrado",
        "peer_closed": "{name}: cierro el aviso de los tableros vecinos. {reason}",
        "calibration_material_title": "Revisión de mis propios avisos en {name}",
        "calibration_material": (
            "{name}: he auditado los {alerts} avisos que le he enviado y las {answered} respuestas confirmadas: "
            "{clean} inspecciones limpias, {false_alarm} falsas alarmas y {confirmed} con síntomas compatibles. "
            "Con ese registro, mi umbral actual le hace mirar el campo más a menudo de lo que el resultado justifica. "
            "Lo que no puedo decidir yo solo es {question}."
        ),
        "options_intro": "Opciones, de menos a más coste:",
        "closing": (
            "¿Con cuál quiere empezar? Si ahora no le encaja ninguna, responda «ninguna» y lo dejo cerrado; "
            "solo se lo volveré a plantear si el patrón cambia."
        ),
        "no_hardware_note": "No propongo comprar nada para resolverlo.",
    },
    "en": {
        "wetness_material_title": "Canopy wetness at {name}: what I checked",
        "wetness_material": (
            "{name}: before writing to you I analysed {days} modelled days ({start} to {end}). "
            "On {uncertain} days humidity sat between 90% and 95% without rain{covered}. "
            "{open} days remain unresolved "
            "(upper bound reaches {max_upper:.0f} degree-hours against {max_lower:.0f} confirmed, "
            "threshold {threshold:.0f}): {open_days}. {systematic}"
            "What I cannot settle from my own data is {question}."
        ),
        "wetness_covered_clause": (
            ", and on {covered} of them the confirmed rain signal crossed the threshold anyway, "
            "so they changed no decision"
        ),
        "wetness_closed_title": "Canopy wetness at {name}: closed",
        "wetness_closed": (
            "{name}: I am closing the canopy-wetness check. I reviewed {days} days ({start} to {end}): "
            "{uncertain} were ambiguous, and on every one of them the confirmed rain signal crossed the "
            "threshold anyway within two days. Conclusion: this season the wetness uncertainty changed no "
            "treatment decision in this field, and I am not proposing a sensor. "
            "I will reopen the question only if unresolved ambiguous days appear."
        ),
        "wetness_measured_title": "Canopy wetness at {name}: resolved",
        "wetness_measured": (
            "{name}: this field already records measured wetness hours ({measured} days), so the model uses "
            "the measurement rather than the humidity proxy. I am closing the question."
        ),
        "wetness_systematic": (
            "In addition, across {days} days the station never recorded a single hour at or above 95% humidity "
            "despite {near_hours} hours between 90% and 95%: that points at the model threshold for this "
            "station rather than an isolated event, and I have opened a source query about that threshold. "
        ),
        "peer_material_title": "Neighbouring board signal near {name}",
        "peer_material": (
            "{name}: {events} confirmed report(s) from {boards} at {nearest} km between {first} and {last} "
            "({disease}). My model for this field gives {local_value}{unit}, below the alert threshold, "
            "and no confirmed inspection is recorded since {last_inspection}. "
            "A peer confirmation is evidence about that parcel, not this one: it raises the prior, "
            "it confirms nothing here. What I cannot settle from the board is {question}."
        ),
        "peer_closed_title": "Neighbouring boards near {name}: closed",
        "peer_closed": "{name}: I am closing the neighbouring-board alert. {reason}",
        "calibration_material_title": "Review of my own alerts at {name}",
        "calibration_material": (
            "{name}: I audited the {alerts} alerts I sent you and the {answered} confirmed replies: "
            "{clean} clean inspections, {false_alarm} false alarms and {confirmed} with compatible symptoms. "
            "On that record my current threshold sends you into the field more often than the outcome justifies. "
            "What I cannot decide alone is {question}."
        ),
        "options_intro": "Options, cheapest first:",
        "closing": (
            "Which would you like to start with? If none of them suit you now, reply \"none\" and I will close it; "
            "I will only raise it again if the pattern changes."
        ),
        "no_hardware_note": "I am not proposing that you buy anything to settle it.",
    },
}

DISEASE_LABELS = {
    "ca": {
        "downy_mildew": "míldiu",
        "powdery_mildew": "oïdi",
        "black_rot": "Black rot de la vinya (Guignardia bidwellii)",
    },
    "es": {
        "downy_mildew": "mildiu",
        "powdery_mildew": "oídio",
        "black_rot": "Black rot de la vid (Guignardia bidwellii)",
    },
    "en": {
        "downy_mildew": "downy mildew",
        "powdery_mildew": "powdery mildew",
        "black_rot": "grapevine black rot (Guignardia bidwellii)",
    },
}

PEER_CLOSURE_REASONS = {
    "ca": {
        "inspected": "Consta una inspecció confirmada posterior en aquest camp.",
        "distant": "El senyal confirmat més proper ja queda fora del radi regional que faig servir.",
        "agreed": "El model local i els taulers veïns ja coincideixen.",
    },
    "es": {
        "inspected": "Consta una inspección confirmada posterior en este campo.",
        "distant": "La señal confirmada más cercana ya queda fuera del radio regional que uso.",
        "agreed": "El modelo local y los tableros vecinos ya coinciden.",
    },
    "en": {
        "inspected": "A later confirmed inspection is recorded for this field.",
        "distant": "The nearest confirmed signal is now outside the regional radius I use.",
        "agreed": "The local model and the neighbouring boards now agree.",
    },
}

OPEN_QUESTIONS = {
    "ca": {
        "wetness": "si aquestes hores a 90-95% mullen realment el dosser en aquest camp",
        "wetness_systematic": (
            "si aquestes hores a 90-95% mullen el dosser o si el llindar de 95% és inabastable en aquesta estació"
        ),
        "peer": "si el senyal regional confirmat ja és present en aquesta parcel·la",
        "calibration": "quants avisos voleu rebre en aquest camp",
    },
    "es": {
        "wetness": "si esas horas al 90-95% mojan realmente el dosel en este campo",
        "wetness_systematic": (
            "si esas horas al 90-95% mojan el dosel o si el umbral del 95% es inalcanzable en esta estación"
        ),
        "peer": "si la señal regional confirmada ya está presente en esta parcela",
        "calibration": "cuántos avisos quiere recibir en este campo",
    },
    "en": {
        "wetness": "whether those 90-95% hours actually wet the canopy in this field",
        "wetness_systematic": (
            "whether those 90-95% hours wet the canopy, or whether the 95% threshold is unreachable at this station"
        ),
        "peer": "whether the confirmed regional signal is already present in this parcel",
        "calibration": "how many alerts you want to receive for this field",
    },
}


# A finding raised by the general engine, about a monitor rather than a field.
# The board found it on its own time; the farmer is told what it saw, over how
# much data, and what it cannot settle alone.
ANOMALY_TEXTS = {
    "ca": {
        "title": "He detectat una anomalia al registre: {subject}",

        "intro": "{name}: revisant el registre del tauler he trobat una cosa a «{subject}».",
        "intro_self": "{name}: revisant el registre del tauler he trobat una cosa.",
        "sample": "He analitzat {samples} mostres.",
        "open": "El que no puc resoldre sol és {question}.",
        "options_intro": "Opcions:",
        "closing": "Voleu que hi continuï? Si no us interessa, responeu «cap» i ho tanco.",
        "data_gap": "La font va deixar d'enregistrar el {last_day} i encara no ha tornat.",
        "level_shift": "El nivell va passar de {before} a {after}, molt més del que varia normalment.",
        "ceiling_saturation": "Els valors s'acumulen contra {top} en lloc de superar-lo, cosa que sol indicar un límit de l'aparell.",
        "ceiling_criterion": "El canal no ha arribat mai al llindar de {criterion} tot i acostar-s'hi {approached} vegades.",
        "source_disagreement": "Dues fonts que haurien de coincidir difereixen en {periods} períodes.",
        "outcome_calibration": "Dels {alerts} avisos que he enviat, {negative} no van trobar res.",
        "relationship_forecast": "{driver} va superar el seu llindar alt el {crossed} ({value}). Per la relació que vau confirmar en aquest camp ({rho} sobre {samples} dies), això apuntaria a {response} cap al {predicted}; és una projecció d'aquesta relació, no una mesura.",
        "lagged_association": "{driver} va precedir {response} {lag} dies abans, de manera consistent al llarg de {samples} dies (correlació {rho}).",
        "baseline_deviation": "Aquesta temporada {metric} és {current}, davant una mediana de {baseline} en les {periods} temporades anteriors.",
        "coverage_gaps": "Hi ha {missing} mesures que em falten per respondre preguntes que ja m'he plantejat. La més útil seria {best}: em permetria respondre {unlocked} pregunta/es que ara no puc.",
        "generic": "El patró es manté al llarg del registre.",
        "open_level_shift": "què va canviar en aquelles dates",
        "open_ceiling_saturation": "si l'aparell està arribant al seu límit",
        "open_ceiling_criterion": "si aquest llindar és assolible en aquest lloc",
        "open_data_gap": "si la font es va aturar o si l'experiment simplement es va acabar",
        "open_source_disagreement": "quina de les dues fonts reflecteix el que passa aquí",
        "open_outcome_calibration": "quants avisos voleu rebre",
    },
    "es": {
        "title": "He detectado una anomalía en el registro: {subject}",

        "intro": "{name}: revisando el registro del tablero he encontrado algo en «{subject}».",
        "intro_self": "{name}: revisando el registro del tablero he encontrado algo.",
        "sample": "He analizado {samples} muestras.",
        "open": "Lo que no puedo resolver solo es {question}.",
        "options_intro": "Opciones:",
        "closing": "¿Quiere que siga? Si no le interesa, responda «ninguna» y lo cierro.",
        "data_gap": "La fuente dejó de registrar el {last_day} y aún no ha vuelto.",
        "level_shift": "El nivel pasó de {before} a {after}, mucho más de lo que varía normalmente.",
        "ceiling_saturation": "Los valores se acumulan contra {top} en lugar de superarlo, lo que suele indicar un límite del aparato.",
        "ceiling_criterion": "El canal nunca alcanzó el umbral de {criterion} pese a acercarse {approached} veces.",
        "source_disagreement": "Dos fuentes que deberían coincidir difieren en {periods} períodos.",
        "outcome_calibration": "De los {alerts} avisos que he enviado, {negative} no encontraron nada.",
        "relationship_forecast": "{driver} superó su umbral alto el {crossed} ({value}). Por la relación que confirmó en este campo ({rho} sobre {samples} días), esto apuntaría a {response} hacia el {predicted}; es una proyección de esa relación, no una medida.",
        "lagged_association": "{driver} precedió a {response} {lag} días antes, de forma consistente a lo largo de {samples} días (correlación {rho}).",
        "baseline_deviation": "Esta temporada {metric} es {current}, frente a una mediana de {baseline} en las {periods} temporadas anteriores.",
        "coverage_gaps": "Hay {missing} medidas que me faltan para responder preguntas que ya me he planteado. La más útil sería {best}: me permitiría responder {unlocked} pregunta(s) que ahora no puedo.",
        "generic": "El patrón se mantiene a lo largo del registro.",
        "open_level_shift": "qué cambió en esas fechas",
        "open_ceiling_saturation": "si el aparato está llegando a su límite",
        "open_ceiling_criterion": "si ese umbral es alcanzable en este sitio",
        "open_data_gap": "si la fuente se detuvo o si el experimento simplemente terminó",
        "open_source_disagreement": "cuál de las dos fuentes refleja lo que pasa aquí",
        "open_outcome_calibration": "cuántos avisos quiere recibir",
    },
    "en": {
        "title": "I found an anomaly in the record: {subject}",

        "intro": "{name}: going through the board's own record I found something in \"{subject}\".",
        "intro_self": "{name}: going through the board's own record I found something.",
        "sample": "I analysed {samples} samples.",
        "open": "What I cannot settle alone is {question}.",
        "options_intro": "Options:",
        "closing": "Would you like me to carry on? If it does not interest you, reply \"none\" and I will close it.",
        "data_gap": "The source stopped recording on {last_day} and has not come back.",
        "level_shift": "The level moved from {before} to {after}, far more than it normally varies.",
        "ceiling_saturation": "Values pile up against {top} instead of passing it, which usually means a limit of the device.",
        "ceiling_criterion": "The channel never reached the {criterion} threshold despite approaching it {approached} times.",
        "source_disagreement": "Two sources that should agree differ across {periods} periods.",
        "outcome_calibration": "Of the {alerts} alerts I sent, {negative} found nothing.",
        "relationship_forecast": "{driver} crossed its high threshold on {crossed} ({value}). By the relationship you confirmed in this field ({rho} over {samples} days), that would point at {response} around {predicted}; it is a projection of that relationship, not a measurement.",
        "lagged_association": "{driver} preceded {response} by {lag} days, consistently across {samples} days (correlation {rho}).",
        "baseline_deviation": "This season {metric} is {current}, against a median of {baseline} across the {periods} previous seasons.",
        "coverage_gaps": "There are {missing} measurements I lack for questions I have already framed. The most useful would be {best}: it would let me answer {unlocked} question(s) I cannot answer now.",
        "generic": "The pattern holds across the record.",
        "open_level_shift": "what changed around those dates",
        "open_ceiling_saturation": "whether the device is reaching its limit",
        "open_ceiling_criterion": "whether that threshold is reachable at this site",
        "open_data_gap": "whether the source stopped or the experiment simply ended",
        "open_source_disagreement": "which of the two sources reflects what happens here",
        "open_outcome_calibration": "how many alerts you want to receive",
    },
}


def anomaly_open_question(language, finding):
    """The open question in the reader's language, or nothing at all.

    An analysis states its open question in English for the record. Dropping
    that sentence is better than pasting it untranslated into a message written
    in someone else's language.
    """
    texts = ANOMALY_TEXTS[language_key(language)]
    analysis = finding.get("analysis")
    if analysis == "ceiling_saturation":
        criterion = (finding.get("metrics") or {}).get("criterion")
        analysis = "ceiling_criterion" if criterion is not None else "ceiling_saturation"
    return texts.get(f"open_{analysis}")


SERIES_LABELS = {
    "ca": {
        "season.rain_total_mm": "la pluja de la temporada",
        "indices.gdd_base10": "la calor acumulada",
    },
    "es": {
        "season.rain_total_mm": "la lluvia de la temporada",
        "indices.gdd_base10": "el calor acumulado",
    },
    "en": {},
}


def localized_series(language, label):
    """Say a derived or model-audit series in the reader's language when known.

    Automatically discovered labels remain source identifiers until a domain
    adapter can resolve their metadata; no relationship is inferred here.
    """
    text = str(label or "")
    table = SERIES_LABELS.get(language_key(language)) or {}
    for english, translated in table.items():
        if text.lower().startswith(english):
            remainder = text[len(english):].strip()
            return f"{translated} {remainder}".strip() if remainder else translated
    return text


def display_subject(subject, field_name):
    """What to call the subject in a message, rather than its internal id."""
    text = str(subject or "").strip()
    if text.startswith("vineyard:"):
        return field_name or text.split(":", 1)[1]
    return text


def anomaly_summary(language, finding):
    """One sentence describing what the board saw, from the finding's numbers."""
    key = language_key(language)
    texts = ANOMALY_TEXTS[key]
    metrics = finding.get("metrics") or {}
    analysis = finding.get("analysis")
    try:
        if analysis == "relationship_forecast":
            return texts["relationship_forecast"].format(
                driver=localized_series(language, metrics.get("driver", "?")),
                response=localized_series(language, metrics.get("response") or "?"),
                crossed=metrics.get("crossed_on", "?"),
                value=metrics.get("driver_value", "?"),
                predicted=metrics.get("predicted_day", "?"),
                rho=metrics.get("relationship_rho", "?"),
                samples=metrics.get("relationship_samples", "?"),
            )
        if analysis == "lagged_association":
            return texts["lagged_association"].format(
                driver=localized_series(language, metrics.get("driver", "?")),
                response=localized_series(language, metrics.get("response", "?")),
                lag=metrics.get("strongest_lag_days", "?"),
                rho=metrics.get("strongest_rho", "?"),
                samples=finding.get("sample_size", 0),
            )
        if analysis == "baseline_deviation":
            return texts["baseline_deviation"].format(
                metric=localized_series(language, metrics.get("metric", "?")),
                current=metrics.get("current_value", "?"),
                baseline=metrics.get("baseline_median", "?"),
                periods=metrics.get("baseline_periods", 0),
            )
        if analysis == "data_gap":
            return texts["data_gap"].format(
                last_day=str(metrics.get("last_record_at") or "")[:10] or "?",
            )
        if analysis == "level_shift":
            return texts["level_shift"].format(
                before=metrics.get("median_before"), after=metrics.get("median_after"),
            )
        if analysis == "ceiling_saturation":
            if metrics.get("criterion") is not None:
                return texts["ceiling_criterion"].format(
                    criterion=metrics.get("criterion"),
                    approached=metrics.get("samples_approaching_criterion", 0),
                )
            return texts["ceiling_saturation"].format(top=metrics.get("observed_max"))
        if analysis == "source_disagreement":
            return texts["source_disagreement"].format(
                periods=metrics.get("periods_beyond_tolerance", 0),
            )
        if analysis == "outcome_calibration":
            return texts["outcome_calibration"].format(
                alerts=metrics.get("alerts_sent", 0), negative=metrics.get("negative", 0),
            )
        if analysis == "coverage_gaps":
            return texts["coverage_gaps"].format(
                missing=len(metrics.get("missing_measurements") or []),
                best=metrics.get("best_single_addition") or "?",
                unlocked=metrics.get("questions_unlocked_by_it", 0),
            )
    except (KeyError, IndexError, ValueError):
        pass
    return texts["generic"]


def render_anomaly(language, field_name, finding):
    """Build the farmer-facing message for a finding raised by the engine."""
    key = language_key(language)
    texts = ANOMALY_TEXTS[key]
    subject = str(finding.get("subject") or "?")
    shown = display_subject(subject, field_name)
    parts = [
        texts["intro_self"].format(name=field_name) if shown == field_name
        else texts["intro"].format(name=field_name, subject=shown),
        anomaly_summary(language, finding),
        texts["sample"].format(samples=finding.get("sample_size", 0)),
    ]
    open_question = anomaly_open_question(language, finding)
    if open_question:
        parts.append(texts["open"].format(question=open_question))
    options = render_options(language, finding.get("options") or [])
    if options:
        parts.append(f"{texts['options_intro']} {options}.")
    parts.append(texts["closing"])
    return {
        "title": texts["title"].format(subject=shown),
        "message": " ".join(parts),
    }


def language_key(language):
    key = str(language or "en").lower()[:2]
    return key if key in TEXTS else "en"


def render_options(language, options):
    key = language_key(language)
    parts = []
    for index, option in enumerate(options or []):
        template = OPTION_TEXTS.get(option.get("id"), {}).get(key)
        if not template:
            continue
        try:
            text = template.format(**(option.get("params") or {}))
        except (KeyError, IndexError):
            continue
        parts.append(f"{index + 1}) {text}")
    return "; ".join(parts)


def render_report(language, field_name, record):
    """Build the farmer-facing title and message for one investigation."""
    key = language_key(language)
    texts = TEXTS[key]
    findings = record.get("findings") or {}
    topic = record.get("topic")
    verdict = record.get("verdict")
    options = record.get("options") or []
    body = None
    title = None
    if topic == TOPIC_WETNESS and verdict == VERDICT_RESOLVED_LOCAL:
        title = texts["wetness_measured_title"].format(name=field_name)
        body = texts["wetness_measured"].format(
            name=field_name, measured=findings.get("measured_wetness_days", 0),
        )
    elif topic == TOPIC_WETNESS and verdict == VERDICT_NOT_MATERIAL:
        title = texts["wetness_closed_title"].format(name=field_name)
        body = texts["wetness_closed"].format(
            name=field_name,
            days=findings.get("days_analyzed", 0),
            start=record.get("window_start") or "",
            end=record.get("window_end") or "",
            uncertain=findings.get("uncertain_days", 0),
        )
    elif topic == TOPIC_WETNESS and verdict == VERDICT_MATERIAL:
        systematic = ""
        if findings.get("station_never_reaches_wetness_threshold"):
            systematic = texts["wetness_systematic"].format(
                days=findings.get("days_analyzed", 0),
                near_hours=findings.get("hours_rh_between_90_and_95", 0),
            )
        question_key = (
            "wetness_systematic"
            if findings.get("station_never_reaches_wetness_threshold") else "wetness"
        )
        covered_count = findings.get("uncertain_days_covered_by_confirmed_signal", 0)
        covered = (
            texts["wetness_covered_clause"].format(covered=covered_count)
            if covered_count else ""
        )
        title = texts["wetness_material_title"].format(name=field_name)
        body = texts["wetness_material"].format(
            name=field_name,
            days=findings.get("days_analyzed", 0),
            start=record.get("window_start") or "",
            end=record.get("window_end") or "",
            uncertain=findings.get("uncertain_days", 0),
            covered=covered,
            open=findings.get("unresolved_days", 0),
            open_days=", ".join(findings.get("unresolved_day_list") or []),
            max_upper=as_float(findings.get("max_upper_bound_index")),
            max_lower=as_float(findings.get("max_confirmed_index_on_unresolved_days")),
            threshold=as_float(findings.get("infection_threshold"), INFECTION_THRESHOLD),
            systematic=systematic,
            question=OPEN_QUESTIONS[key][question_key],
        )
    elif topic == TOPIC_PEER and verdict == VERDICT_NOT_MATERIAL:
        if findings.get("recent_local_inspection"):
            reason = "inspected"
        elif findings.get("reason") == "the nearest confirmed peer event is outside the regional radius":
            reason = "distant"
        else:
            reason = "agreed"
        title = texts["peer_closed_title"].format(name=field_name)
        body = texts["peer_closed"].format(
            name=field_name, reason=PEER_CLOSURE_REASONS[key][reason],
        )
    elif topic == TOPIC_PEER and verdict == VERDICT_MATERIAL:
        lead = (findings.get("divergent") or [{}])[0]
        disease = lead.get("disease", "")
        title = texts["peer_material_title"].format(name=field_name)
        body = texts["peer_material"].format(
            name=field_name,
            events=lead.get("peer_events", 0),
            boards=", ".join(lead.get("peer_boards") or []),
            nearest=lead.get("nearest_km", "?"),
            first=lead.get("first_day", ""),
            last=lead.get("last_day", ""),
            disease=DISEASE_LABELS[key].get(disease, disease),
            local_value=lead.get("local_value", 0),
            unit=lead.get("local_unit", ""),
            last_inspection=findings.get("last_local_inspection_day") or "-",
            question=OPEN_QUESTIONS[key]["peer"],
        )
    elif topic == TOPIC_CALIBRATION and verdict == VERDICT_MATERIAL:
        title = texts["calibration_material_title"].format(name=field_name)
        body = texts["calibration_material"].format(
            name=field_name,
            alerts=findings.get("alerts_sent", 0),
            answered=findings.get("alerts_answered", 0),
            clean=findings.get("clean_inspections", 0),
            false_alarm=findings.get("false_alarms", 0),
            confirmed=findings.get("confirmed_symptoms", 0),
            question=OPEN_QUESTIONS[key]["calibration"],
        )
    if not body:
        return None
    rendered_options = render_options(language, options)
    if rendered_options:
        body = f"{body} {texts['options_intro']} {rendered_options}. {texts['closing']}"
    elif verdict == VERDICT_MATERIAL:
        body = f"{body} {texts['closing']}"
    if verdict == VERDICT_MATERIAL and not any(
        option.get("cost") == "hardware" for option in options
    ):
        body = f"{body} {texts['no_hardware_note']}"
    return {"title": title, "message": body}
