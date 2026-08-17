#!/usr/bin/env python3
"""Evidence-linked proactive field memory and proposal loop.

The implementation is intentionally standard-library only. It is designed for
the 256 MB LicheeRV Nano and complements, rather than replaces, PicoClaw,
nano-os-agent, Vineyard Guard, and the deterministic Telegram outbox.
"""

import datetime as dt
import hashlib
import html
import ipaddress
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
import unicodedata
from pathlib import Path

# The skill directory is on sys.path when run.sh executes this file, but not
# when a test loads it by path, so make the sibling module importable either way.
_SKILL_DIR = str(Path(__file__).resolve().parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
# The research engine is a sibling skill. It is optional: a board without it
# keeps working, it simply stops learning from refusals it collected here.
_ENGINE_DIR = str(Path(_SKILL_DIR).parent / "research_agent")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

import investigations  # noqa: E402  (requires the sys.path bootstrap above)


DEFAULT_REPO = "/root/.picoclaw/workspace/goidanich"
DEFAULT_STATE_DIR = "/root/.picoclaw/workspace/proactive_field"
SCHEMA_VERSION = 4
DEFAULT_NOTIFICATION_THRESHOLD = 70
# A material research finding is already filtered by the research engine and
# the adapter. Once it becomes a farmer-facing proposal, placing it below the
# delivery threshold makes the entire research loop observationally silent.
RESEARCH_NOTIFICATION_PRIORITY = DEFAULT_NOTIFICATION_THRESHOLD
ALLOWED_DECISIONS = {"accepted", "rejected", "deferred", "corrected"}
INVESTIGATION_KIND_PREFIX = "investigation:"
# A rejected proposal is a decision, not a delay. The topic stays closed for a
# season unless the underlying finding changes.
REJECTED_COOLDOWN_DAYS = 180
# A hardware option may be offered once per season per field, and only inside a
# finding that also offers cheaper ways to answer the same question.
HARDWARE_OPTION_COOLDOWN_DAYS = 180
DISEASE_OPERATION_TYPES = {
    "treatment", "spray", "application", "inspection", "scouting",
    "clean_inspection", "disease_observation",
}
TREATMENT_OPERATION_TYPES = {
    "treatment", "treated", "spray", "application",
}
OUTCOME_OPERATION_TYPES = {
    "inspection", "scouting", "clean_inspection", "false_alarm",
    "detected_mildew", "detected_black_rot", "disease_observation",
    "follow_up_observation", "operation_outcome",
}
FOLLOW_UP_DELAYS = {
    "treatment": 3,
    "treated": 3,
    "spray": 3,
    "application": 3,
    "irrigation": 3,
    "fertilization": 5,
    "pruning": 7,
    "mowing": 7,
    "soil_work": 7,
    "cover_crop": 7,
    "sensor_installation": 7,
    "planting": 10,
    "harvest": 2,
}
NANO_PROBLEM_VERDICTS = {"discard", "partial", "failed", "fail", "error", "blocked"}
NANO_SUCCESS_VERDICTS = {"keep", "pass", "passed", "success"}
SEARCH_CREDENTIAL_KEYS = ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso_now():
    return utcnow().isoformat()


def read_params():
    raw = sys.stdin.read().strip()
    params = json.loads(raw) if raw else {}
    if not isinstance(params, dict):
        raise ValueError("skill input must be a JSON object")
    env_map = {
        "mode": "SKILL_MODE",
        "repo_path": "SKILL_REPO_PATH",
        "state_dir": "SKILL_STATE_DIR",
        "field": "SKILL_FIELD",
        "query": "SKILL_QUERY",
        "proposal_id": "SKILL_PROPOSAL_ID",
        "decision": "SKILL_DECISION",
        "note": "SKILL_NOTE",
        "search_env": "SKILL_SEARCH_ENV",
    }
    for key, env_name in env_map.items():
        if key not in params and os.environ.get(env_name):
            params[key] = os.environ[env_name]
    return params


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def parse_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def trace(state_dir, event, data):
    path = Path(state_dir) / "traces.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > 1024 * 1024:
            previous = path.with_suffix(".jsonl.1")
            if previous.exists():
                previous.unlink()
            path.replace(previous)
        safe_data = dict(data or {})
        for key in list(safe_data):
            if any(token in key.lower() for token in ("token", "key", "secret", "password")):
                safe_data[key] = "[redacted]"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": iso_now(), "event": event, "data": safe_data}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def connect_db(state_dir):
    path = Path(state_dir)
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path / "proactive_field.db"))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS field_profiles (
            field_id TEXT PRIMARY KEY,
            board_id TEXT,
            name TEXT NOT NULL,
            location TEXT,
            variety TEXT,
            language TEXT,
            profile_json TEXT NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            effective_day TEXT,
            source_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            freshness TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_observations_field_kind
            ON observations(field_id, kind, observed_at DESC);
        CREATE TABLE IF NOT EXISTS operations (
            event_id TEXT PRIMARY KEY,
            field_id TEXT NOT NULL,
            disease_id TEXT,
            operation_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_operations_field_time
            ON operations(field_id, occurred_at DESC);
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            value_json TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(field_id, subject, predicate, source_ref)
        );
        CREATE TABLE IF NOT EXISTS research_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT,
            query TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(field_id, query)
        );
        CREATE TABLE IF NOT EXISTS research_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            snippet TEXT,
            provider TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            FOREIGN KEY(request_id) REFERENCES research_requests(id)
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            field_id TEXT,
            kind TEXT NOT NULL,
            target TEXT NOT NULL,
            priority INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            rationale TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            requires_confirmation INTEGER NOT NULL,
            status TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            cooldown_until TEXT,
            notified_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_proposals_status_priority
            ON proposals(status, priority DESC, created_at);
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            note TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(proposal_id) REFERENCES proposals(id)
        );
        """
    )
    investigations.ensure_tables(connection)
    # Schema v4 repairs proposals created by the earlier priority mismatch.
    # The update is idempotent and deliberately limited to unsent research
    # findings; declined, completed, or already-delivered records are untouched.
    connection.execute(
        "UPDATE proposals SET priority=?, updated_at=? "
        "WHERE kind LIKE 'research:%' AND status='pending' "
        "AND notified_at IS NULL AND priority<?",
        (
            RESEARCH_NOTIFICATION_PRIORITY,
            iso_now(),
            RESEARCH_NOTIFICATION_PRIORITY,
        ),
    )
    connection.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def load_yaml(path):
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (ImportError, OSError, ValueError):
        # JSON is valid YAML but the dependency-free fallback below only reads
        # the indented board/fields subset. Without this a JSON-formatted
        # configuration on a board with no PyYAML reports no configured fields
        # at all, which reads as an empty vineyard rather than a parse failure.
        try:
            return json.loads(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            pass
        return load_yaml_subset(path)


def scalar(text):
    value = text.strip().strip("'\"")
    if value.lower() in {"true", "yes"}:
        return True
    if value.lower() in {"false", "no"}:
        return False
    if value.lower() in {"null", "none", "~"}:
        return None
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def load_yaml_subset(path):
    """Parse the board/notifications/fields subset without a YAML dependency."""
    result = {"board": {}, "notifications": {}, "fields": []}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    section = ""
    current = None
    subsection = ""
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            current = None
            subsection = ""
            continue
        if section in {"board", "notifications"} and indent >= 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[section][key.strip()] = scalar(value)
            continue
        if section != "fields":
            continue
        match = re.match(r"-\s+id:\s*(.+)", stripped)
        if match:
            current = {"id": scalar(match.group(1)), "metadata": {}, "coordinates": {}}
            result["fields"].append(current)
            subsection = ""
            continue
        if not current or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not value.strip() and key in {"metadata", "coordinates"}:
            subsection = key
            continue
        target = current.get(subsection) if indent >= 6 and subsection in {"metadata", "coordinates"} else current
        target[key] = scalar(value)
    return result


def field_profiles(repo_path):
    config = load_yaml(os.path.join(repo_path, "agent_config.yaml"))
    board = config.get("board") or {}
    notifications = config.get("notifications") or {}
    language = notifications.get("language") or board.get("preferred_language") or "en"
    profiles = []
    for raw in config.get("fields") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        coordinates = raw.get("coordinates") if isinstance(raw.get("coordinates"), dict) else {}
        combined = dict(metadata)
        combined.update({key: value for key, value in raw.items() if key not in {"metadata"}})
        combined["coordinates"] = coordinates
        profiles.append({
            "field_id": str(raw["id"]),
            "board_id": str(board.get("id") or ""),
            "name": str(raw.get("name") or raw.get("location") or raw["id"]),
            "location": str(raw.get("location") or metadata.get("location") or ""),
            "variety": str(raw.get("variety") or metadata.get("variety") or ""),
            "language": str(raw.get("language") or language),
            "profile": combined,
        })
    return profiles


def save_profiles(connection, profiles):
    changed = 0
    now = iso_now()
    for profile in profiles:
        fingerprint = digest(profile["profile"])
        previous = connection.execute(
            "SELECT profile_fingerprint FROM field_profiles WHERE field_id=?",
            (profile["field_id"],),
        ).fetchone()
        if not previous or previous["profile_fingerprint"] != fingerprint:
            changed += 1
        connection.execute(
            """
            INSERT INTO field_profiles(
                field_id, board_id, name, location, variety, language,
                profile_json, profile_fingerprint, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(field_id) DO UPDATE SET
                board_id=excluded.board_id, name=excluded.name,
                location=excluded.location, variety=excluded.variety,
                language=excluded.language, profile_json=excluded.profile_json,
                profile_fingerprint=excluded.profile_fingerprint,
                updated_at=excluded.updated_at
            """,
            (
                profile["field_id"], profile["board_id"], profile["name"],
                profile["location"], profile["variety"], profile["language"],
                json_text(profile["profile"]), fingerprint, now,
            ),
        )
    connection.commit()
    return changed


def state_disease(path, state):
    disease = str(state.get("disease") or "").strip()
    if disease:
        return disease
    name = path.name.lower()
    if "black_rot" in name:
        return "black_rot"
    if "powdery" in name:
        return "powdery_mildew"
    if "downy" in name:
        return "downy_mildew"
    return "unknown"


def state_field(state):
    latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    agent = state.get("agent") if isinstance(state.get("agent"), dict) else {}
    return str(state.get("field") or latest.get("field_id") or agent.get("id") or "")


def state_freshness(state):
    flags = state.get("model_layer_freshness") if isinstance(state.get("model_layer_freshness"), dict) else {}
    required = parse_date(flags.get("required_end") or state.get("end"))
    latest = parse_date(flags.get("latest_history_day") or (state.get("latest") or {}).get("day"))
    today = dt.datetime.now().astimezone().date()
    current_day = bool(latest and latest >= today - dt.timedelta(days=1))
    explicit_false = any(
        flags.get(key) is False
        for key in ("history_current", "prediction_ok", "forecast_current", "forecast_refresh_ok")
        if key in flags
    )
    if required and latest and latest < required:
        explicit_false = True
    return "current" if current_day and not explicit_false else "stale"


def compact_state(path, state):
    latest = state.get("latest") if isinstance(state.get("latest"), dict) else {}
    forecast = state.get("forecast_prediction") if isinstance(state.get("forecast_prediction"), dict) else {}
    disease = state_disease(path, state)
    payload = {
        "disease": disease,
        "updated_at": state.get("updated_at"),
        "day": latest.get("day") or state.get("end"),
        "goidanich_daily_risk": as_float(latest.get("baseline_risk")),
        "rossi_risk": as_float(latest.get("rossi_risk")),
        "powdery_uc_risk": as_float(latest.get("powdery_risk")),
        "powdery_pmi": as_float(latest.get("powdery_pmi")),
        "powdery_pmi_treatment_due": bool(latest.get("powdery_pmi_treatment_due")),
        "powdery_pmi_action": latest.get("powdery_pmi_action"),
        "black_rot_infection_index": as_float(latest.get("black_rot_infection_index")),
        "black_rot_inoculum_status": latest.get("black_rot_inoculum_status"),
        "black_rot_wetness_uncertain_watch": bool(latest.get("black_rot_wetness_uncertain_watch")),
        "forecast_available": bool(forecast.get("available")),
        "forecast_severity": forecast.get("severity"),
        "forecast_max": as_float(
            forecast.get("max_risk")
            or forecast.get("max_index")
            or forecast.get("max_infection_index")
        ),
        "forecast_max_day": forecast.get("max_day"),
        "forecast_first_watch_day": forecast.get("first_watch_day") or forecast.get("first_infection_day"),
        "plot_path": state.get("plot_path") or state.get("plot"),
    }
    if disease in {"downy_mildew", "powdery_mildew"}:
        payload["trained"] = bool(latest.get("trained"))
    return {key: value for key, value in payload.items() if value is not None}


def discover_states(repo_path, configured, selected_field=None):
    results_dir = Path(repo_path) / "results"
    chosen = {}
    if not results_dir.is_dir():
        return []
    configured_ids = {profile["field_id"] for profile in configured}
    for path in results_dir.glob("dashboard_state*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        field_id = state_field(state)
        if not field_id or field_id not in configured_ids:
            continue
        if selected_field and field_id != selected_field:
            continue
        disease = state_disease(path, state)
        if disease not in {"downy_mildew", "powdery_mildew", "black_rot"}:
            continue
        key = (field_id, disease)
        timestamp = parse_datetime(state.get("updated_at")) or dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
        if key not in chosen or timestamp > chosen[key][0]:
            chosen[key] = (timestamp, path, state)
    observations = []
    for (field_id, disease), (_, path, state) in sorted(chosen.items()):
        compact = compact_state(path, state)
        observations.append({
            "field_id": field_id,
            "kind": f"disease_state:{disease}",
            "observed_at": state.get("updated_at") or iso_now(),
            "effective_day": compact.get("day"),
            "source_type": "dashboard_state",
            "source_ref": str(path),
            "freshness": state_freshness(state),
            "payload": compact,
        })
    return observations


def tail_json_lines(path, max_bytes=128 * 1024, limit=100):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read(max_bytes)
    except OSError:
        return []
    if size > max_bytes:
        data = data.split(b"\n", 1)[-1]
    rows = []
    for raw in data.decode("utf-8", "replace").splitlines()[-limit:]:
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def discover_nano_experiments(nano_root, configured, selected_field=None):
    field_ids = [profile["field_id"] for profile in configured]
    candidates = [
        Path(nano_root) / "experiments.jsonl",
        Path("/tmp/experiments.jsonl"),
    ]
    observations = []
    seen = set()
    for path in candidates:
        if not path.exists():
            continue
        for entry in tail_json_lines(path):
            reference = json_text(entry)
            metrics = entry.get("metrics_after") if isinstance(entry.get("metrics_after"), dict) else {}
            field_id = str(metrics.get("field_id") or metrics.get("field") or "")
            if field_id not in field_ids:
                matches = [candidate for candidate in field_ids if candidate in reference]
                field_context = " ".join(
                    str(entry.get(key) or "") for key in ("task_id", "task_name", "summary")
                ).lower()
                contextual_single_field = (
                    len(field_ids) == 1 and any(
                        token in field_context
                        for token in ("field", "vineyard", "vine", "grape", "canopy", "plant")
                    )
                )
                field_id = matches[0] if len(matches) == 1 else (field_ids[0] if contextual_single_field else "")
            if not field_id or (selected_field and field_id != selected_field):
                continue
            identity = (str(path), entry.get("id"), entry.get("timestamp"), entry.get("task_id"))
            if identity in seen:
                continue
            seen.add(identity)
            timestamp = entry.get("timestamp") or iso_now()
            parsed = parse_datetime(timestamp)
            freshness = "current" if parsed and parsed >= utcnow() - dt.timedelta(days=7) else "stale"
            payload = {
                "experiment_id": entry.get("id"),
                "task_id": entry.get("task_id"),
                "task_name": entry.get("task_name"),
                "hypothesis_ref": entry.get("hypothesis_ref"),
                "metrics_after": metrics,
                "steps_run": entry.get("steps_run"),
                "steps_passed": entry.get("steps_passed"),
                "duration": entry.get("duration"),
                "verdict": entry.get("verdict"),
                "summary": entry.get("summary"),
            }
            observations.append({
                "field_id": field_id,
                "kind": f"nano_experiment:{entry.get('task_id') or 'unknown'}",
                "observed_at": timestamp,
                "effective_day": str(timestamp)[:10],
                "source_type": "nano_experiment",
                "source_ref": str(path),
                "freshness": freshness,
                "payload": payload,
            })
    return observations


def store_observations(connection, observations):
    inserted = 0
    now = iso_now()
    for item in observations:
        fingerprint = digest({
            "field_id": item["field_id"],
            "kind": item["kind"],
            "source_ref": item["source_ref"],
            "payload": item["payload"],
        })
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO observations(
                field_id, kind, observed_at, effective_day, source_type,
                source_ref, freshness, payload_json, fingerprint, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["field_id"], item["kind"], item["observed_at"],
                item.get("effective_day"), item["source_type"], item["source_ref"],
                item["freshness"], json_text(item["payload"]), fingerprint, now,
            ),
        )
        inserted += int(cursor.rowcount > 0)
    connection.commit()
    return inserted


def table_columns(connection, table):
    try:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def ingest_operations(connection, repo_path, selected_field=None):
    source = Path(repo_path) / "goidanich.db"
    if not source.exists():
        return {"available": False, "inserted": 0, "reason": "goidanich.db missing"}
    inserted = 0
    try:
        external = sqlite3.connect(str(source))
        external.row_factory = sqlite3.Row
        columns = table_columns(external, "farmer_feedback")
        if not columns:
            return {"available": False, "inserted": 0, "reason": "farmer_feedback table missing"}
        selected = [name for name in (
            "timestamp", "feedback_type", "grade", "severity", "notes",
            "metadata", "field_id", "disease_id",
        ) if name in columns]
        query = "SELECT " + ",".join(selected) + " FROM farmer_feedback"
        values = []
        if selected_field and "field_id" in selected:
            query += " WHERE field_id=?"
            values.append(selected_field)
        if "timestamp" in selected:
            query += " ORDER BY timestamp DESC LIMIT 500"
        rows = external.execute(query, values).fetchall()
    except sqlite3.Error as exc:
        return {"available": False, "inserted": 0, "reason": str(exc)}
    finally:
        try:
            external.close()
        except UnboundLocalError:
            pass
    now = iso_now()
    for row in rows:
        payload = dict(row)
        if isinstance(payload.get("metadata"), str):
            try:
                payload["metadata"] = json.loads(payload["metadata"])
            except ValueError:
                pass
        field_id = str(payload.get("field_id") or "")
        if not field_id:
            continue
        occurred = str(payload.get("timestamp") or now)
        operation_type = str(payload.get("feedback_type") or "feedback")
        event_id = digest({"field": field_id, "occurred": occurred, "payload": payload})
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO operations(
                event_id, field_id, disease_id, operation_type, occurred_at,
                payload_json, source_ref, created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                event_id, field_id, str(payload.get("disease_id") or ""),
                operation_type, occurred, json_text(payload),
                f"{source}:farmer_feedback", now,
            ),
        )
        inserted += int(cursor.rowcount > 0)
    connection.commit()
    return {"available": True, "inserted": inserted, "rows_seen": len(rows)}


def upsert_fact(connection, field_id, subject, predicate, value, source_type, source_ref,
                confidence=1.0, status="confirmed"):
    now = iso_now()
    connection.execute(
        """
        INSERT INTO facts(
            field_id, subject, predicate, value_json, source_type, source_ref,
            confidence, status, first_seen_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(field_id, subject, predicate, source_ref) DO UPDATE SET
            value_json=excluded.value_json, confidence=excluded.confidence,
            status=excluded.status, updated_at=excluded.updated_at
        """,
        (
            field_id, subject, predicate, json_text(value), source_type,
            source_ref, float(confidence), status, now, now,
        ),
    )
    connection.commit()


def leaf_wetness_reply(value):
    """Interpret an explicit wet/dry field answer in the board languages."""
    text = normalized_lookup(value)
    if not text:
        return None
    wet_words = {
        "wet", "mullat", "mullats", "mullada", "mullades",
        "mojado", "mojados", "mojada", "mojadas", "humides", "humedas",
    }
    dry_words = {
        "dry", "sec", "secs", "seca", "seques", "seco", "secos", "secas",
    }
    words = set(text.split())
    if words & dry_words:
        return False
    if re.search(r"\b(no|not)\b.{0,24}\b(wet|mullat|mullats|mullada|mullades|mojado|mojados|mojada|mojadas)\b", text):
        return False
    if words & wet_words:
        return True
    if text in {"si", "yes", "correcte", "correcto", "correct"}:
        return True
    if text in {"no", "nope"}:
        return False
    return None


def ensure_leaf_wetness_observations(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS leaf_wetness_observations (
            field_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            wet INTEGER NOT NULL CHECK (wet IN (0, 1)),
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (field_id, observed_at, source_ref)
        )
        """
    )


def record_leaf_wetness_observation(connection, proposal, wet, note, params):
    """Persist direct farmer evidence locally and in the model database."""
    field_id = str(proposal.get("field_id") or "")
    observed_at = str(params.get("observed_at") or dt.datetime.now().astimezone().isoformat())
    source_ref = f"proposal:{proposal['id']}:leaf_wetness:{observed_at[:13]}"
    value = {
        "wet": bool(wet),
        "observed_at": observed_at,
        "note": note,
        "proposal_id": proposal["id"],
        "causal_claim": False,
    }
    upsert_fact(
        connection, field_id, "canopy", "leaf_wetness_observation", value,
        "farmer_confirmed", source_ref, confidence=1.0, status="confirmed",
    )

    repo_path = str(params.get("repo_path") or DEFAULT_REPO)
    database = os.path.join(repo_path, "goidanich.db")
    written_to_model_db = False
    if os.path.exists(database):
        with sqlite3.connect(database, timeout=15) as field_db:
            ensure_leaf_wetness_observations(field_db)
            field_db.execute(
                """
                INSERT INTO leaf_wetness_observations(
                    field_id, observed_at, wet, source, source_ref, note, created_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(field_id, observed_at, source_ref) DO UPDATE SET
                    wet=excluded.wet, note=excluded.note
                """,
                (
                    field_id, observed_at, int(bool(wet)), "farmer_confirmed",
                    source_ref, note, iso_now(),
                ),
            )
            field_db.commit()
        written_to_model_db = True
    return {
        **value,
        "field_id": field_id,
        "source_ref": source_ref,
        "model_database": database,
        "written_to_model_database": written_to_model_db,
    }


def close_wetness_research(connection, field_id):
    """Retire source-review prompts superseded by direct field evidence."""
    now = iso_now()
    rows = connection.execute(
        """
        SELECT id FROM research_requests
        WHERE field_id=? AND (
            reason LIKE 'The station never reached%'
            OR reason LIKE 'Repeated canopy-wetness uncertainty%'
            OR query LIKE '%leaf wetness%'
        )
        """,
        (field_id,),
    ).fetchall()
    request_ids = {int(row["id"]) for row in rows}
    if request_ids:
        placeholders = ",".join("?" for _ in request_ids)
        connection.execute(
            f"UPDATE research_requests SET status='resolved_by_field_evidence', updated_at=? "
            f"WHERE id IN ({placeholders})",
            [now] + sorted(request_ids),
        )
        proposals = connection.execute(
            "SELECT * FROM proposals WHERE field_id=? AND kind='research_review' "
            "AND status IN ('pending','notified','deferred')",
            (field_id,),
        ).fetchall()
        for row in proposals:
            proposal = proposal_dict(row)
            linked = {
                int(item["request_id"])
                for item in proposal.get("evidence") or []
                if isinstance(item, dict) and item.get("request_id")
            }
            if linked & request_ids:
                connection.execute(
                    "UPDATE proposals SET status='completed', updated_at=? WHERE id=?",
                    (now, proposal["id"]),
                )
    # Releases before the investigation engine used a farmer-facing alias for
    # this same question. Close both generations so a recovered observation
    # cannot produce a redundant next-day closure.
    connection.execute(
        """
        UPDATE proposals SET status='completed', updated_at=?
        WHERE field_id=?
          AND kind IN ('leaf_wetness_research', 'investigation:leaf_wetness_proxy')
          AND status IN ('pending','notified','deferred','accepted')
        """,
        (now, field_id),
    )
    connection.commit()
    return sorted(request_ids)


def backfill_leaf_wetness_decisions(connection, repo_path):
    """Recover explicit wet/dry replies recorded before evidence persistence."""
    rows = connection.execute(
        """
        SELECT d.*, p.id AS linked_proposal_id
        FROM decisions d JOIN proposals p ON p.id=d.proposal_id
        WHERE p.kind='investigation:leaf_wetness_proxy'
          AND d.decision='accepted' AND length(trim(COALESCE(d.note,'')))>0
        ORDER BY d.created_at
        """
    ).fetchall()
    recovered = []
    for row in rows:
        wet = leaf_wetness_reply(row["note"])
        if wet is None:
            continue
        proposal = proposal_by_id(connection, int(row["linked_proposal_id"]))
        if not proposal:
            continue
        prefix = f"proposal:{proposal['id']}:leaf_wetness:"
        exists = connection.execute(
            "SELECT 1 FROM facts WHERE field_id=? AND predicate='leaf_wetness_observation' "
            "AND source_ref LIKE ? LIMIT 1",
            (proposal.get("field_id"), prefix + "%"),
        ).fetchone()
        if exists:
            continue
        evidence = record_leaf_wetness_observation(
            connection, proposal, wet, str(row["note"]),
            {
                "repo_path": repo_path,
                "observed_at": row["created_at"],
            },
        )
        close_wetness_research(connection, proposal.get("field_id"))
        refresh_black_rot_from_observation(
            repo_path, proposal.get("field_id"), evidence["observed_at"],
        )
        recovered.append(evidence)
    return recovered


def refresh_black_rot_from_observation(repo_path, field_id, observed_at):
    script = os.path.join(repo_path, "black_rot.py")
    if not os.path.exists(script):
        return {"ok": False, "reason": "black_rot.py is unavailable"}
    command = [
        sys.executable, script, "--db", os.path.join(repo_path, "goidanich.db"),
        "--field", field_id, "--end", str(observed_at)[:10],
    ]
    try:
        proc = subprocess.run(
            command, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": str(exc), "command": command}
    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        payload = {}
    return {
        "ok": proc.returncode == 0 and bool(payload.get("ok")),
        "returncode": proc.returncode,
        "result": payload,
        "stderr": proc.stderr.decode("utf-8", "replace")[-1000:],
    }


def profile_facts(connection, profiles):
    for profile in profiles:
        source = "agent_config.yaml"
        if profile.get("variety"):
            upsert_fact(connection, profile["field_id"], "field", "variety", profile["variety"], "config", source)
        upsert_fact(connection, profile["field_id"], "field", "name", profile["name"], "config", source)
        for key in ("vine_age", "age", "planting_year", "rootstock", "training_system", "management", "irrigation"):
            value = profile["profile"].get(key)
            if value not in (None, ""):
                upsert_fact(connection, profile["field_id"], "field", key, value, "config", source)


def latest_observations(connection, field_id):
    rows = connection.execute(
        """
        SELECT o.* FROM observations o
        JOIN (
            SELECT kind, MAX(id) AS max_id FROM observations
            WHERE field_id=? GROUP BY kind
        ) latest ON latest.max_id=o.id
        ORDER BY o.kind
        """,
        (field_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result


def latest_operation(connection, field_id, operation_types=None):
    query = "SELECT * FROM operations WHERE field_id=?"
    values = [field_id]
    if operation_types:
        marks = ",".join("?" for _ in operation_types)
        query += f" AND lower(operation_type) IN ({marks})"
        values.extend([item.lower() for item in operation_types])
    query += " ORDER BY occurred_at DESC LIMIT 1"
    row = connection.execute(query, values).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def field_operations(connection, field_id):
    rows = connection.execute(
        "SELECT * FROM operations WHERE field_id=? ORDER BY occurred_at, event_id",
        (field_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except (TypeError, ValueError):
            item["payload"] = {}
        item["operation_type"] = str(item.get("operation_type") or "").lower()
        item["occurred_datetime"] = parse_datetime(item.get("occurred_at"))
        result.append(item)
    return result


def operation_outcome_after(operations, operation):
    occurred = operation.get("occurred_datetime")
    if not occurred:
        return None
    disease = str(operation.get("disease_id") or "")
    for candidate in operations:
        candidate_time = candidate.get("occurred_datetime")
        if not candidate_time or candidate_time <= occurred:
            continue
        if candidate.get("operation_type") not in OUTCOME_OPERATION_TYPES:
            continue
        candidate_disease = str(candidate.get("disease_id") or "")
        if disease and candidate_disease and disease != candidate_disease:
            continue
        return candidate
    return None


def derive_operation_insights(connection, profiles):
    """Consolidate confirmed event sequences without making a causal claim."""
    linked = 0
    for profile in profiles:
        operations = field_operations(connection, profile["field_id"])
        for operation in operations:
            if operation.get("operation_type") not in FOLLOW_UP_DELAYS:
                continue
            outcome = operation_outcome_after(operations, operation)
            if not outcome:
                continue
            source_ref = (
                f"operation-sequence:{operation['event_id']}:{outcome['event_id']}"
            )
            upsert_fact(
                connection,
                profile["field_id"],
                "operation_follow_up",
                f"observed_outcome_after_{operation['operation_type']}",
                {
                    "operation_event_id": operation["event_id"],
                    "operation_type": operation["operation_type"],
                    "operation_at": operation["occurred_at"],
                    "outcome_event_id": outcome["event_id"],
                    "outcome_type": outcome["operation_type"],
                    "outcome_at": outcome["occurred_at"],
                    "disease": operation.get("disease_id") or outcome.get("disease_id") or "",
                    "causal_claim": False,
                },
                "derived_confirmed_sequence",
                source_ref,
                confidence=1.0,
                status="observed_association",
            )
            linked += 1
    return linked


def pending_operation_follow_up(connection, field_id, now=None):
    now = now or utcnow()
    operations = field_operations(connection, field_id)
    for operation in reversed(operations):
        delay = FOLLOW_UP_DELAYS.get(operation.get("operation_type"))
        occurred = operation.get("occurred_datetime")
        if delay is None or not occurred:
            continue
        age = (now - occurred).total_seconds() / 86400.0
        if age < delay or age > 60:
            continue
        if operation_outcome_after(operations, operation):
            continue
        return operation
    return None


def queue_research(connection, field_id, query, reason, evidence):
    now = iso_now()
    connection.execute(
        """
        INSERT INTO research_requests(
            field_id, query, reason, evidence_json, status, attempts,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(field_id, query) DO NOTHING
        """,
        (field_id, query, reason, json_text(evidence), "queued", 0, now, now),
    )
    connection.commit()


def phrase(language, key, **values):
    lang = str(language or "en").lower()[:2]
    texts = {
        "ca": {
            "attention_title": "El camp {name} demana una comprovació",
            "attention": "{name}: {signal}. Abans de decidir cap tractament, confirmeu l'estat del dosser i la protecció recent. {question}",
            "profile_title": "Falta informació estable de {name}",
            "profile": "Per personalitzar les comparacions de {name}, confirmeu {missing}. No modificaré el perfil fins que ho confirmeu.",
            "model_title": "Cal una observació de camp per a {name}",
            "model": "El model après de {name} encara no té prou evidència local. Quan inspeccioneu, confirmeu si el dosser és net o si hi ha símptomes; aquesta dada alimentarà el model després de la vostra confirmació.",
            "operation_title": "Comprovació després d'una operació a {name}",
            "operation_follow_up": "{name}: consta {operation} el {day}, però encara no hi ha cap resultat posterior confirmat. Per aprendre què funciona en aquest camp sense confondre seqüència amb causa, indiqueu què heu observat i la data de l'observació.",
            "question": "Responeu amb el resultat: cap símptoma, símptomes compatibles, fals avís, o l'última aplicació (producte, dosi per ha, data i objectiu).",
        },
        "es": {
            "attention_title": "El campo {name} pide una comprobación",
            "attention": "{name}: {signal}. Antes de decidir un tratamiento, confirme el estado del dosel y la protección reciente. {question}",
            "profile_title": "Falta información estable de {name}",
            "profile": "Para personalizar las comparaciones de {name}, confirme {missing}. No modificaré el perfil hasta que lo confirme.",
            "model_title": "Hace falta una observación de campo para {name}",
            "model": "El modelo aprendido de {name} aún no tiene suficiente evidencia local. Tras la inspección, confirme si el dosel está limpio o si hay síntomas; el dato alimentará el modelo solo después de su confirmación.",
            "operation_title": "Comprobación después de una operación en {name}",
            "operation_follow_up": "{name}: consta {operation} el {day}, pero aún no hay un resultado posterior confirmado. Para aprender qué funciona en este campo sin confundir secuencia con causa, indique qué observó y la fecha de la observación.",
            "question": "Responda con el resultado: sin síntomas, síntomas compatibles, falsa alarma, o la última aplicación (producto, dosis por ha, fecha y objetivo).",
        },
        "en": {
            "attention_title": "Field {name} needs a check",
            "attention": "{name}: {signal}. Before deciding on treatment, confirm canopy condition and recent protection. {question}",
            "profile_title": "Stable information is missing for {name}",
            "profile": "To personalize comparisons for {name}, confirm {missing}. I will not change the profile until you confirm it.",
            "model_title": "A field observation is needed for {name}",
            "model": "The learned model for {name} still lacks local evidence. After scouting, confirm whether the canopy is clean or symptoms are present; the observation will train the model only after confirmation.",
            "operation_title": "Post-operation check for {name}",
            "operation_follow_up": "{name}: {operation} was recorded on {day}, but no later outcome has been confirmed. To learn what works in this field without confusing sequence with causation, report what you observed and the observation date.",
            "question": "Reply with the result: no symptoms, compatible symptoms, false alarm, or the latest application (product, dose per ha, date and target).",
        },
    }
    return texts.get(lang, texts["en"])[key].format(**values)


def signal_summary(observations, language):
    lang = str(language or "en").lower()[:2]
    labels = {
        "ca": {
            "downy": "míldiu", "powdery": "oïdi", "degree_hours": "graus-hora",
            "black_rot": "Black rot de la vinya (Guignardia bidwellii)", "today": "avui",
            "forecast": "previst el {day}", "unverified": "; pendent de confirmar al camp",
        },
        "es": {
            "downy": "mildiu", "powdery": "oídio", "degree_hours": "grados-hora",
            "black_rot": "Black rot de la vid (Guignardia bidwellii)", "today": "hoy",
            "forecast": "previsto el {day}", "unverified": "; pendiente de confirmar en campo",
        },
        "en": {
            "downy": "downy mildew", "powdery": "powdery mildew", "degree_hours": "degree-hours",
            "black_rot": "grapevine black rot (Guignardia bidwellii)", "today": "today",
            "forecast": "forecast for {day}", "unverified": "; pending field confirmation",
        },
    }.get(lang, {
        "downy": "downy mildew", "powdery": "powdery mildew", "degree_hours": "degree-hours",
        "black_rot": "grapevine black rot (Guignardia bidwellii)", "today": "today",
        "forecast": "forecast for {day}", "unverified": "; pending field confirmation",
    })
    signals = []
    evidence = []
    alert_diseases = []
    media = []
    alert = False
    wetness_watch = False
    untrained = False
    for item in observations:
        payload = item["payload"]
        disease = payload.get("disease")
        if item["freshness"] != "current":
            continue
        evidence_item = {
            "kind": item["kind"], "source_ref": item["source_ref"],
            "day": payload.get("day"), "fingerprint": item["fingerprint"],
            "disease": disease,
        }
        if payload.get("plot_path"):
            evidence_item["plot_path"] = payload["plot_path"]
        evidence.append(evidence_item)
        if disease in {"downy_mildew", "powdery_mildew"}:
            untrained = untrained or not bool(payload.get("trained", True))
        if disease == "downy_mildew":
            goi = as_float(payload.get("goidanich_daily_risk"), 0.0)
            rossi = as_float(payload.get("rossi_risk"), 0.0)
            if max(goi, rossi) >= 50.0:
                alert = True
                alert_diseases.append(disease)
                signals.append(f"{labels['downy']} Goidanich {goi:.1f}% / Rossi {rossi:.1f}%")
        elif disease == "powdery_mildew":
            uc = as_float(payload.get("powdery_uc_risk"), 0.0)
            pmi = as_float(payload.get("powdery_pmi"), 0.0)
            due = bool(payload.get("powdery_pmi_treatment_due"))
            if uc >= 50.0 or due:
                alert = True
                alert_diseases.append(disease)
                signals.append(f"{labels['powdery']} UC {uc:.1f}% / PMI {pmi:.1f}")
        elif disease == "black_rot":
            index = as_float(payload.get("black_rot_infection_index"), 0.0)
            inoculum = str(payload.get("black_rot_inoculum_status") or "unknown").lower()
            forecast_max = as_float(payload.get("forecast_max"), 0.0)
            forecast_day = str(payload.get("forecast_first_watch_day") or "").strip()
            wetness_watch = wetness_watch or bool(payload.get("black_rot_wetness_uncertain_watch"))
            if index >= 85.0 or (forecast_max >= 85.0 and forecast_day):
                alert = True
                alert_diseases.append(disease)
                signal_index = index if index >= 85.0 else forecast_max
                timing = labels["today"] if index >= 85.0 else labels["forecast"].format(day=forecast_day)
                uncertainty = labels["unverified"] if inoculum != "present" else ""
                signals.append(
                    f"{labels['black_rot']} {signal_index:.1f} "
                    f"{labels['degree_hours']} {timing}{uncertainty}"
                )
        if disease in alert_diseases and payload.get("plot_path"):
            media.append({
                "type": "photo",
                "path": payload["plot_path"],
                "source_path": payload["plot_path"],
                "caption": signals[-1] if signals else "",
                "mime_type": "image/png",
                "exists": Path(payload["plot_path"]).exists(),
                "disease": disease,
            })
    return {
        "alert": alert,
        "alert_diseases": sorted(set(alert_diseases)),
        "wetness_watch": wetness_watch,
        "untrained": untrained,
        "signals": signals,
        "evidence": evidence,
        "media": media,
    }


def nano_experiment_assessment(observations):
    issues = []
    successes = []
    for item in observations:
        if not item["kind"].startswith("nano_experiment:") or item["freshness"] != "current":
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        verdict = str(payload.get("verdict") or "").strip().lower()
        steps_run = as_float(payload.get("steps_run"))
        steps_passed = as_float(payload.get("steps_passed"))
        incomplete = (
            steps_run is not None and steps_passed is not None and
            steps_run > 0 and steps_passed < steps_run
        )
        evidence = {
            "kind": item["kind"],
            "source_ref": item["source_ref"],
            "fingerprint": item["fingerprint"],
            "experiment_id": payload.get("experiment_id"),
            "task_id": payload.get("task_id"),
            "task_name": payload.get("task_name"),
            "verdict": verdict or "unknown",
            "steps_run": payload.get("steps_run"),
            "steps_passed": payload.get("steps_passed"),
            "observed_at": item.get("observed_at"),
        }
        if verdict in NANO_PROBLEM_VERDICTS or incomplete:
            evidence["summary"] = str(payload.get("summary") or "")[:500]
            issues.append(evidence)
        elif verdict in NANO_SUCCESS_VERDICTS and not incomplete:
            evidence["metrics_after"] = payload.get("metrics_after") or {}
            successes.append(evidence)
    return {"issues": issues, "successes": successes}


def nano_research_query(issue):
    topic = str(issue.get("task_name") or issue.get("task_id") or "field sensor experiment")
    topic = re.sub(r"[^A-Za-z0-9À-ÿ _+./-]+", " ", topic)
    topic = re.sub(r"\s+", " ", topic).strip()[:160]
    return (
        f"LicheeRV Nano {topic} troubleshooting official documentation "
        "field sensor validation"
    )


def derive_nano_insights(connection, profiles):
    stored = 0
    for profile in profiles:
        assessment = nano_experiment_assessment(
            latest_observations(connection, profile["field_id"])
        )
        for success in assessment["successes"]:
            task = str(success.get("task_id") or "unknown")
            predicate = "validated_" + re.sub(r"[^a-z0-9]+", "_", task.lower()).strip("_")
            upsert_fact(
                connection,
                profile["field_id"],
                "nano_experiment",
                predicate,
                {
                    **success,
                    "interpretation": "one recorded experiment passed its declared checks",
                    "causal_claim": False,
                },
                "nano_experiment",
                f"nano-experiment:{success.get('fingerprint')}",
                confidence=1.0,
                status="observed_success",
            )
            stored += 1
    return stored


def missing_profile_items(profile):
    raw = profile["profile"]
    missing = []
    if not profile.get("variety"):
        missing.append("variety")
    if not any(raw.get(key) not in (None, "") for key in ("vine_age", "age", "planting_year")):
        missing.append("vine age or planting year")
    if raw.get("rootstock") in (None, ""):
        missing.append("rootstock")
    return missing


def localized_missing_items(items, language):
    lang = str(language or "en").lower()[:2]
    labels = {
        "ca": {
            "variety": "la varietat",
            "vine age or planting year": "l'edat de les vinyes o l'any de plantació",
            "rootstock": "el portaempelt",
        },
        "es": {
            "variety": "la variedad",
            "vine age or planting year": "la edad de las cepas o el año de plantación",
            "rootstock": "el portainjerto",
        },
    }.get(lang, {})
    return [labels.get(item, item) for item in items]


def localized_operation_description(operation, language):
    lang = str(language or "en").lower()[:2]
    labels = {
        "ca": {
            "treatment": "un tractament", "treated": "un tractament",
            "spray": "una aplicació", "application": "una aplicació",
            "irrigation": "un reg", "fertilization": "una fertilització",
            "pruning": "una poda", "mowing": "una sega",
            "soil_work": "un treball del sòl", "cover_crop": "un treball de coberta vegetal",
            "sensor_installation": "una instal·lació de sensor", "planting": "una plantació",
            "harvest": "una verema",
        },
        "es": {
            "treatment": "un tratamiento", "treated": "un tratamiento",
            "spray": "una aplicación", "application": "una aplicación",
            "irrigation": "un riego", "fertilization": "una fertilización",
            "pruning": "una poda", "mowing": "una siega",
            "soil_work": "un trabajo del suelo", "cover_crop": "un trabajo de cubierta vegetal",
            "sensor_installation": "una instalación de sensor", "planting": "una plantación",
            "harvest": "una vendimia",
        },
        "en": {
            "treatment": "a treatment", "treated": "a treatment",
            "spray": "an application", "application": "an application",
            "irrigation": "an irrigation", "fertilization": "a fertilization",
            "pruning": "a pruning operation", "mowing": "a mowing operation",
            "soil_work": "a soil operation", "cover_crop": "a cover-crop operation",
            "sensor_installation": "a sensor installation", "planting": "a planting operation",
            "harvest": "a harvest",
        },
    }
    operation_type = str(operation.get("operation_type") or "operation")
    text = labels.get(lang, labels["en"]).get(operation_type, operation_type.replace("_", " "))
    payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    treatment = metadata.get("treatment") if isinstance(metadata.get("treatment"), dict) else {}
    if not treatment and isinstance(payload.get("treatment"), dict):
        treatment = payload["treatment"]
    if not treatment and isinstance(payload.get("details"), dict):
        treatment = payload["details"]
    product = treatment.get("product") or payload.get("product")
    dose = treatment.get("dose") or treatment.get("dose_per_ha") or payload.get("dose")
    details = [str(value).strip() for value in (product, dose) if str(value or "").strip()]
    return text + (f" ({', '.join(details)})" if details else "")


def cooldown_exists(connection, field_id, kind):
    row = connection.execute(
        """
        SELECT id FROM proposals
        WHERE field_id=? AND kind=? AND (
            status IN ('pending','notified','deferred') OR
            (cooldown_until IS NOT NULL AND cooldown_until>?)
        ) LIMIT 1
        """,
        (field_id, kind, iso_now()),
    ).fetchone()
    return bool(row)


def create_proposal(connection, candidate):
    if cooldown_exists(connection, candidate.get("field_id"), candidate["kind"]):
        return None
    now = iso_now()
    cooldown_days = int(candidate.get("cooldown_days", 7))
    cooldown = (utcnow() + dt.timedelta(days=cooldown_days)).isoformat()
    dedupe_key = digest({
        "field": candidate.get("field_id"), "kind": candidate["kind"],
        "evidence": candidate.get("evidence") or [],
    })
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO proposals(
            field_id, kind, target, priority, title, message, rationale,
            evidence_json, confidence, requires_confirmation, status,
            dedupe_key, cooldown_until, notified_at, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            candidate.get("field_id"), candidate["kind"], candidate.get("target", "farmer"),
            int(candidate["priority"]), candidate["title"], candidate["message"],
            candidate["rationale"], json_text(candidate.get("evidence") or []),
            float(candidate.get("confidence", 0.8)), 1 if candidate.get("requires_confirmation", True) else 0,
            "pending", dedupe_key, cooldown, None, now, now,
        ),
    )
    connection.commit()
    if cursor.rowcount <= 0:
        return None
    return proposal_by_id(connection, cursor.lastrowid)


def proposal_by_id(connection, proposal_id):
    row = connection.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    return proposal_dict(row) if row else None


def proposal_dict(row):
    item = dict(row)
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["requires_confirmation"] = bool(item["requires_confirmation"])
    return item


def investigation_kind(topic):
    return f"{INVESTIGATION_KIND_PREFIX}{topic}"


def hardware_option_allowed(connection, field_id):
    """True while no hardware option has been offered or refused this season."""
    since = (utcnow() - dt.timedelta(days=HARDWARE_OPTION_COOLDOWN_DAYS)).isoformat()
    rows = connection.execute(
        "SELECT evidence_json FROM proposals "
        "WHERE field_id=? AND kind LIKE ? AND created_at>=?",
        (field_id, INVESTIGATION_KIND_PREFIX + "%", since),
    ).fetchall()
    for row in rows:
        try:
            evidence = json.loads(row["evidence_json"])
        except ValueError:
            continue
        for item in evidence:
            if isinstance(item, dict) and "hardware" in (item.get("option_costs") or []):
                return False
    return True


def wetness_reference_peer(repo_path, profile):
    """A neighbour board that measures leaf wetness, when one is configured.

    The comparison option is offered only when such a peer actually exists; the
    agent must not invite the farmer to request data nobody has.
    """
    config = load_yaml(os.path.join(repo_path, "neighbours.yaml"))
    coordinates = (profile.get("profile") or {}).get("coordinates") or {}
    origin = (coordinates.get("latitude"), coordinates.get("longitude"))
    for raw in (config.get("neighbours") or []):
        if not isinstance(raw, dict) or not raw.get("leaf_wetness_sensor"):
            continue
        peer_coordinates = raw.get("coordinates") if isinstance(raw.get("coordinates"), dict) else {}
        distance = investigations.haversine_km(
            origin, (peer_coordinates.get("latitude"), peer_coordinates.get("longitude")),
        )
        return {
            "peer_name": str(raw.get("name") or raw.get("id") or "veí"),
            "distance_km": f"{distance:.1f}" if distance is not None else "?",
        }
    return None


def run_field_investigations(connection, profile, repo_path, observations=None, now=None):
    field_id = profile["field_id"]
    return investigations.run_investigations(
        connection,
        profile,
        repo_path,
        observations if observations is not None else latest_observations(connection, field_id),
        now=now,
        hardware_option_allowed=hardware_option_allowed(connection, field_id),
        wetness_reference_peer=wetness_reference_peer(repo_path, profile),
    )


def open_topic_proposal(connection, field_id, kinds):
    """The last farmer-facing proposal on a topic that has not been closed yet."""
    placeholders = ",".join("?" for _ in kinds)
    row = connection.execute(
        f"SELECT * FROM proposals WHERE field_id=? AND kind IN ({placeholders}) "
        "AND target='farmer' AND notified_at IS NOT NULL AND status!='completed' "
        "ORDER BY created_at DESC LIMIT 1",
        [field_id] + list(kinds),
    ).fetchone()
    return proposal_dict(row) if row else None


def investigation_candidates(connection, profile, records):
    """Turn stored findings into farmer messages, or into nothing at all.

    Only an unresolved, decision-relevant finding is worth a message. A closed
    conclusion is sent once, and only when the farmer was already asked about
    that topic; otherwise the finding stays in evidence memory.
    """
    field_id = profile["field_id"]
    language = profile["language"]
    name = profile["name"]
    candidates = []
    for record in records:
        topic = record.get("topic")
        verdict = record.get("verdict")
        if not record.get("id") or not topic:
            continue
        kind = investigation_kind(topic)
        legacy_kinds = [kind]
        if topic == investigations.TOPIC_WETNESS:
            legacy_kinds.append("leaf_wetness_research")
        options = record.get("options") or []
        evidence = [{
            "investigation_id": record["id"],
            "topic": topic,
            "verdict": verdict,
            "question": record.get("question"),
            "method": record.get("method"),
            "sample_size": record.get("sample_size"),
            "options": [option.get("id") for option in options],
            "option_costs": sorted({option.get("cost") for option in options if option.get("cost")}),
            "limitations": record.get("limitations") or [],
        }] + (record.get("evidence") or [])
        if verdict == investigations.VERDICT_MATERIAL:
            rendered = investigations.render_report(language, name, record)
            if not rendered:
                continue
            candidates.append({
                "field_id": field_id, "kind": kind, "target": "farmer",
                "priority": 72, "title": rendered["title"], "message": rendered["message"],
                "rationale": (
                    "A bounded investigation over stored field evidence left a decision-relevant "
                    "question open; the farmer holds the cheapest way to close it."
                ),
                "evidence": evidence,
                "confidence": float(record.get("confidence") or 0.5),
                "requires_confirmation": True, "cooldown_days": 21,
                "investigation_id": record["id"],
            })
            continue
        if verdict not in {
            investigations.VERDICT_NOT_MATERIAL, investigations.VERDICT_RESOLVED_LOCAL,
        }:
            continue
        previous = open_topic_proposal(connection, field_id, legacy_kinds)
        if not previous:
            continue
        rendered = investigations.render_report(language, name, record)
        if not rendered:
            # The question is settled but not worth a message. Close the open
            # proposal anyway so the topic does not stay blocked forever.
            connection.execute(
                "UPDATE proposals SET status='completed', updated_at=? WHERE id=?",
                (iso_now(), previous["id"]),
            )
            connection.commit()
            continue
        candidates.append({
            "field_id": field_id, "kind": f"{kind}:closure", "target": "farmer",
            "priority": 71, "title": rendered["title"], "message": rendered["message"],
            "rationale": (
                "An open question the farmer was already asked about is now settled by the "
                "board's own evidence; closing it is part of the answer."
            ),
            "evidence": evidence,
            "confidence": float(record.get("confidence") or 0.5),
            "requires_confirmation": False, "cooldown_days": 60,
            "investigation_id": record["id"],
            "closes_proposal_id": previous["id"],
        })
    return candidates


RESEARCH_KIND_PREFIX = "research:"

# Analyses this adapter already renders itself, in the farmer's language and
# with its own agronomic phrasing. Delivering the engine's generic version too
# would ask the same question twice in one thread.
#
# Everything else the engine finds about a field — a cross-series hypothesis, a
# season unlike its predecessors, a forecast drifting from the station — has no
# adapter topic and must be delivered, or the research never reaches anyone.
ADAPTER_COVERED_ANALYSES = frozenset({
    "threshold_materiality",   # leaf_wetness_proxy
    "ceiling_saturation",      # leaf_wetness_proxy, systematic-station clause
    "neighbour_reports",       # peer_signal_divergence
    "outcome_calibration",     # alert_calibration
})


def deliverable_finding(finding):
    subject = str(finding.get("subject") or "")
    if not subject.startswith("vineyard:"):
        return True
    return str(finding.get("analysis") or "") not in ADAPTER_COVERED_ANALYSES


def research_findings(params, limit=5):
    """Open findings the general engine wants a person to see.

    Subjects the vineyard adapter already covers are left out: the pack asks
    those questions through this skill's own topics, and nobody needs the same
    question twice in one message thread.
    """
    state_dir = (
        params.get("research_state_dir")
        or os.environ.get("NORA_STATE_DIR")
        or "/root/.picoclaw/workspace/research"
    )
    if not Path(state_dir, "research.db").exists():
        return []
    try:
        import engine as research_engine
    except ImportError:
        return []
    try:
        connection = research_engine.connect(state_dir)
        try:
            findings = [
                item for item in research_engine.list_findings(
                    connection, verdict=research_engine.VERDICT_MATERIAL, limit=limit * 4,
                )
                if item.get("status") == "open" and deliverable_finding(item)
            ]
        finally:
            connection.close()
    except Exception:
        return []
    return findings[:limit]


def research_candidates(connection, profile, params, include_board_wide=False):
    """Turn engine findings into one confirmable message each."""
    language = profile["language"]
    name = profile["name"]
    field_subject = research_subject(profile["field_id"])
    candidates = []
    for finding in research_findings(params):
        subject = str(finding.get("subject") or "")
        if subject.startswith("vineyard:"):
            if subject != field_subject:
                continue
        elif not include_board_wide:
            continue
        rendered = investigations.render_anomaly(language, name, finding)
        if not rendered:
            continue
        options = finding.get("options") or []
        candidates.append({
            "field_id": profile["field_id"],
            "kind": f"{RESEARCH_KIND_PREFIX}{finding.get('analysis')}",
            "target": "farmer",
            "priority": RESEARCH_NOTIFICATION_PRIORITY,
            "title": rendered["title"],
            "message": rendered["message"],
            "rationale": (
                "The research engine found a pattern in the board's own record that it "
                "could not settle from local evidence."
            ),
            "evidence": [{
                "research_finding_id": finding.get("id"),
                "subject": finding.get("subject"),
                "analysis": finding.get("analysis"),
                "verdict": finding.get("verdict"),
                "method": finding.get("method"),
                "sample_size": finding.get("sample_size"),
                "options": [option.get("id") for option in options],
                "option_costs": sorted({
                    option.get("cost") for option in options if option.get("cost")
                }),
                "limitations": finding.get("limitations") or [],
            }],
            "confidence": float(finding.get("confidence") or 0.5),
            "requires_confirmation": True,
            "cooldown_days": 14,
            "research_finding_id": finding.get("id"),
        })
    return candidates


def apply_investigation_actions(connection, field_id, records):
    """Queue the source question a local investigation could not answer."""
    queued = []
    for record in records:
        if record.get("verdict") != investigations.VERDICT_MATERIAL:
            continue
        for action in record.get("internal_actions") or []:
            if action.get("action") != "queue_research" or not action.get("query"):
                continue
            queue_research(
                connection, field_id, str(action["query"]), str(action.get("reason") or ""),
                [{"investigation_id": record.get("id"), "topic": record.get("topic")}],
            )
            queued.append(action["query"])
    return queued


def generate_proposals(connection, profiles, investigation_records=None, params=None):
    created = []
    investigation_records = investigation_records or {}
    params = params or {}
    for profile in profiles:
        field_id = profile["field_id"]
        name = profile["name"]
        language = profile["language"]
        observations = latest_observations(connection, field_id)
        disease_observations = [item for item in observations if item["kind"].startswith("disease_state:")]
        nano_assessment = nano_experiment_assessment(observations)
        current = [item for item in disease_observations if item["freshness"] == "current"]
        current_diseases = {item["payload"].get("disease") for item in current}
        expected_diseases = {"downy_mildew", "powdery_mildew", "black_rot"}
        incomplete_diseases = sorted(expected_diseases - current_diseases)
        candidates = []
        if incomplete_diseases:
            candidates.append({
                "field_id": field_id, "kind": "refresh_required", "target": "system",
                "priority": 100, "title": f"Refresh required for {name}",
                "message": f"Current dashboard evidence is incomplete for {name}: {', '.join(incomplete_diseases)}.",
                "rationale": "Farmer advice is blocked until all three independent disease caches are current.",
                "evidence": [{"source_ref": item["source_ref"], "freshness": item["freshness"], "kind": item["kind"]} for item in disease_observations],
                "confidence": 1.0, "requires_confirmation": False, "cooldown_days": 1,
            })
        if not incomplete_diseases:
            summary = signal_summary(current, language)
            treatment = latest_operation(connection, field_id, {"treatment", "treated", "application", "spray"})
            if summary["alert"]:
                signal = ", ".join(summary["signals"])
                question = phrase(language, "question")
                candidates.append({
                    "field_id": field_id, "kind": "field_check", "target": "farmer",
                    "priority": 90, "title": phrase(language, "attention_title", name=name),
                    "message": phrase(language, "attention", name=name, signal=signal, question=question),
                    "rationale": "A current disease-specific model signal crossed the watch policy; treatment remains conditional on inspection and protection history.",
                    "evidence": (
                        summary["evidence"]
                        + [{"alert_diseases": summary["alert_diseases"]}]
                        + ([{"operation": treatment["event_id"], "occurred_at": treatment["occurred_at"]}] if treatment else [])
                    ),
                    "confidence": 0.9, "requires_confirmation": True, "cooldown_days": 2,
                })
            if summary["untrained"]:
                candidates.append({
                    "field_id": field_id, "kind": "scouting_evidence", "target": "farmer",
                    "priority": 45, "title": phrase(language, "model_title", name=name),
                    "message": phrase(language, "model", name=name),
                    "rationale": "The field-specific learned layer is untrained and needs confirmed local outcomes.",
                    "evidence": summary["evidence"], "confidence": 1.0,
                    "requires_confirmation": True, "cooldown_days": 14,
                })
        if nano_assessment["issues"]:
            issue = nano_assessment["issues"][0]
            query = nano_research_query(issue)
            queue_research(
                connection,
                field_id,
                query,
                "A field-related nano-os-agent experiment did not pass its evaluation gate. Its result is quarantined while a bounded remedy search is reviewed.",
                [issue],
            )
            candidates.append({
                "field_id": field_id,
                "kind": "experiment_investigation",
                "target": "system",
                "priority": 80,
                "title": f"Experiment investigation required for {name}",
                "message": (
                    f"The field experiment {issue.get('task_name') or issue.get('task_id') or 'unknown'} "
                    "did not pass its declared checks. Its measurements are excluded from farmer advice pending review."
                ),
                "rationale": (
                    "A failed or partial experiment is evidence of an unresolved method or hardware problem, "
                    "not evidence about the field."
                ),
                "evidence": [issue, {"research_query": query}],
                "confidence": 1.0,
                "requires_confirmation": False,
                "cooldown_days": 7,
            })
        follow_up = pending_operation_follow_up(connection, field_id)
        if follow_up:
            operation_text = localized_operation_description(follow_up, language)
            candidates.append({
                "field_id": field_id, "kind": "operation_follow_up", "target": "farmer",
                "priority": 75,
                "title": phrase(language, "operation_title", name=name),
                "message": phrase(
                    language,
                    "operation_follow_up",
                    name=name,
                    operation=operation_text,
                    day=str(follow_up.get("occurred_at") or "")[:10],
                ),
                "rationale": (
                    "A confirmed operation has no later confirmed outcome. The follow-up "
                    "closes the learning loop while explicitly avoiding a causal inference."
                ),
                "evidence": [{
                    "source_operation": {
                        "event_id": follow_up["event_id"],
                        "operation_type": follow_up["operation_type"],
                        "occurred_at": follow_up["occurred_at"],
                        "disease": follow_up.get("disease_id") or "",
                    }
                }],
                "confidence": 1.0,
                "requires_confirmation": True,
                "cooldown_days": 14,
            })
        missing = missing_profile_items(profile)
        if missing:
            missing_text = ", ".join(localized_missing_items(missing, language))
            candidates.append({
                "field_id": field_id, "kind": "profile_clarification", "target": "farmer",
                "priority": 55, "title": phrase(language, "profile_title", name=name),
                "message": phrase(language, "profile", name=name, missing=missing_text),
                "rationale": "Variety, vine age/planting year and rootstock are stable covariates required for cross-board model comparison.",
                "evidence": [{"source_ref": "agent_config.yaml", "profile_fingerprint": digest(profile["profile"])}],
                "confidence": 1.0, "requires_confirmation": True, "cooldown_days": 30,
            })
        records = investigation_records.get(field_id) or []
        apply_investigation_actions(connection, field_id, records)
        candidates.extend(investigation_candidates(connection, profile, records))
        # Field findings stay with their field. Domain-neutral board findings
        # have no field route, so attach those once to the first profile.
        candidates.extend(research_candidates(
            connection,
            profile,
            params,
            include_board_wide=profile is profiles[0],
        ))
        candidates.sort(key=lambda item: item["priority"], reverse=True)
        for candidate in candidates:
            proposal = create_proposal(connection, candidate)
            if proposal:
                if candidate.get("investigation_id"):
                    investigations.mark_investigation(
                        connection, candidate["investigation_id"], "reported",
                    )
                if candidate.get("closes_proposal_id"):
                    connection.execute(
                        "UPDATE proposals SET status='completed', updated_at=? WHERE id=?",
                        (iso_now(), candidate["closes_proposal_id"]),
                    )
                    connection.commit()
                created.append(proposal)
                break
    return created


def next_proposal(connection, field_id=None, include_system=False, only_unnotified=False):
    clauses = ["status IN ('pending','notified')"]
    values = []
    if field_id:
        clauses.append("field_id=?")
        values.append(field_id)
    if not include_system:
        clauses.append("target='farmer'")
    if only_unnotified:
        clauses.append("notified_at IS NULL")
    row = connection.execute(
        "SELECT * FROM proposals WHERE " + " AND ".join(clauses) +
        " ORDER BY priority DESC, created_at ASC LIMIT 1",
        values,
    ).fetchone()
    return proposal_dict(row) if row else None


def pending_research(connection, field_id=None):
    query = "SELECT * FROM research_requests WHERE status='queued'"
    values = []
    if field_id:
        query += " AND field_id=?"
        values.append(field_id)
    query += " ORDER BY created_at ASC LIMIT 1"
    row = connection.execute(query, values).fetchone()
    if not row:
        return None
    item = dict(row)
    item["evidence"] = json.loads(item.pop("evidence_json"))
    return item


def public_url(value):
    try:
        parsed = urllib.parse.urlparse(str(value))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            return None
    except ValueError:
        pass
    return parsed.geturl()


def read_whitelisted_env(path, allowed=SEARCH_CREDENTIAL_KEYS):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    allowed = set(allowed)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            values[key] = value
    return values


def load_search_credentials(repo_path=None, explicit_path=None):
    credentials = {
        key: os.environ[key].strip()
        for key in SEARCH_CREDENTIAL_KEYS
        if os.environ.get(key, "").strip()
    }
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates.append(Path.home() / ".picoclaw" / "search.env")
    if repo_path:
        candidates.append(Path(repo_path) / ".env")
    for path in candidates:
        for key, value in read_whitelisted_env(path).items():
            credentials.setdefault(key, value)
    return credentials


def strip_tags(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def search_tavily(query, limit, key=None):
    key = key or os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "api_key": key, "query": query, "max_results": limit,
        "search_depth": "basic", "include_answer": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "PicoClaw-ProactiveField/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read(512 * 1024).decode("utf-8", "replace"))
    return [{
        "title": str(item.get("title") or item.get("url") or "Source")[:300],
        "url": item.get("url"),
        "snippet": str(item.get("content") or "")[:1200],
        "provider": "tavily",
    } for item in data.get("results") or []]


def search_brave(query, limit, key=None):
    key = key or os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return None
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({
        "q": query,
        "count": max(1, min(int(limit), 10)),
        "safesearch": "moderate",
    })
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
            "User-Agent": "PicoClaw-ProactiveField/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read(512 * 1024).decode("utf-8", "replace"))
    return [{
        "title": str(item.get("title") or item.get("url") or "Source")[:300],
        "url": item.get("url"),
        "snippet": str(item.get("description") or "")[:1200],
        "provider": "brave",
    } for item in ((data.get("web") or {}).get("results") or [])]


def parse_duckduckgo_results(body, limit, provider):
    links = []
    for attributes, title in re.findall(r"<a\b([^>]*)>(.*?)</a>", body, flags=re.I | re.S):
        class_match = re.search(r"\bclass\s*=\s*['\"]([^'\"]*)['\"]", attributes, flags=re.I)
        href_match = re.search(r"\bhref\s*=\s*['\"]([^'\"]+)['\"]", attributes, flags=re.I)
        classes = set((class_match.group(1) if class_match else "").split())
        if not href_match or not classes.intersection({"result__a", "result-link"}):
            continue
        links.append((href_match.group(1), title))
        if len(links) >= limit:
            break
    snippets = re.findall(
        r"<(?:a|div|td)\b[^>]*class\s*=\s*['\"][^'\"]*(?:result__snippet|result-snippet)[^'\"]*['\"][^>]*>(.*?)</(?:a|div|td)>",
        body, flags=re.I | re.S,
    )
    results = []
    for index, (href, title) in enumerate(links[:limit]):
        parsed = urllib.parse.urlparse(html.unescape(href))
        redirect = urllib.parse.parse_qs(parsed.query).get("uddg")
        target = redirect[0] if redirect else html.unescape(href)
        results.append({
            "title": strip_tags(title)[:300], "url": target,
            "snippet": strip_tags(snippets[index] if index < len(snippets) else "")[:1200],
            "provider": provider,
        })
    return results


def search_duckduckgo(query, limit):
    encoded = urllib.parse.urlencode({"q": query})
    endpoints = (
        ("https://html.duckduckgo.com/html/?" + encoded, "duckduckgo_html"),
        ("https://lite.duckduckgo.com/lite/?" + encoded, "duckduckgo_lite"),
    )
    for url, provider in endpoints:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 PicoClaw-ProactiveField/1.0"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read(512 * 1024).decode("utf-8", "replace")
        results = parse_duckduckgo_results(body, limit, provider)
        if results:
            return results
    return []


def normalize_sources(raw_sources, provider=None, limit=5):
    sources = []
    for item in raw_sources or []:
        if not isinstance(item, dict):
            continue
        url = public_url(item.get("url"))
        title = strip_tags(str(item.get("title") or ""))[:300]
        if not url or not title:
            continue
        sources.append({
            "title": title,
            "url": url,
            "snippet": strip_tags(str(item.get("snippet") or item.get("content") or ""))[:1200],
            "provider": str(item.get("provider") or provider or "external")[:80],
        })
        if len(sources) >= limit:
            break
    return sources


def perform_search(query, limit=5, credentials=None):
    credentials = credentials or {}
    errors = []
    try:
        results = search_tavily(query, limit, credentials.get("TAVILY_API_KEY"))
        if results:
            return normalize_sources(results, "tavily", limit), errors
    except Exception as exc:
        errors.append(f"tavily: {exc}")
    try:
        results = search_brave(query, limit, credentials.get("BRAVE_SEARCH_API_KEY"))
        if results:
            return normalize_sources(results, "brave", limit), errors
    except Exception as exc:
        errors.append(f"brave: {exc}")
    try:
        results = search_duckduckgo(query, limit)
        return normalize_sources(results, "duckduckgo_html", limit), errors
    except Exception as exc:
        errors.append(f"duckduckgo_html: {exc}")
    return [], errors


def store_research(connection, request_row, sources):
    now = iso_now()
    inserted = 0
    for source in sources:
        fingerprint = digest({"url": source["url"], "snippet": source.get("snippet") or ""})
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO research_sources(
                request_id, title, url, snippet, provider, retrieved_at, fingerprint
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                request_row["id"], source["title"], source["url"], source.get("snippet") or "",
                source.get("provider") or "external", now, fingerprint,
            ),
        )
        inserted += int(cursor.rowcount > 0)
    next_attempt = int(request_row.get("attempts") or 0) + 1
    status = "complete" if sources else ("queued" if next_attempt < 3 else "failed")
    connection.execute(
        "UPDATE research_requests SET status=?, attempts=attempts+1, updated_at=? WHERE id=?",
        (status, now, request_row["id"]),
    )
    connection.commit()
    return inserted


def store_research_synthesis(connection, request_row, sources):
    """Keep public sources as internal evidence and compare them locally.

    A bibliography is not a farmer task. Candidate sources can support a board
    method review, but they never become an unsolicited request to read papers,
    buy hardware, or authorize analysis the board can perform itself.
    """
    profile = connection.execute(
        "SELECT * FROM field_profiles WHERE field_id=?", (request_row.get("field_id"),)
    ).fetchone()
    if not profile or not sources:
        return None
    profile = dict(profile)
    wetness_facts = connection.execute(
        """
        SELECT value_json, source_ref, updated_at FROM facts
        WHERE field_id=? AND predicate='leaf_wetness_observation'
          AND source_type='farmer_confirmed' AND status='confirmed'
        ORDER BY updated_at DESC
        """,
        (profile["field_id"],),
    ).fetchall()
    direct_observations = []
    for row in wetness_facts:
        try:
            value = json.loads(row["value_json"])
        except (TypeError, ValueError):
            continue
        direct_observations.append({
            "wet": bool(value.get("wet")),
            "observed_at": value.get("observed_at"),
            "source_ref": row["source_ref"],
        })
    is_wetness = (
        "leaf wetness" in str(request_row.get("query") or "").lower()
        or "wetness" in str(request_row.get("reason") or "").lower()
    )
    synthesis = {
        "request_id": request_row["id"],
        "field_id": profile["field_id"],
        "query": request_row.get("query"),
        "source_count": len(sources),
        "sources": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "provider": item.get("provider"),
            }
            for item in sources
        ],
        "direct_field_observations": direct_observations if is_wetness else [],
        "conclusion": (
            "Direct farmer-confirmed canopy wetness is available and takes precedence over "
            "candidate sensor literature for this event. The board will compare the observation "
            "with its weather and disease series; no farmer literature review is required."
            if is_wetness and direct_observations else
            "Candidate sources were retained for internal method comparison. They do not by "
            "themselves validate a field claim or change an operational threshold."
        ),
        "operational_change": False,
        "farmer_action_required": False,
        "causal_claim": False,
    }
    upsert_fact(
        connection, profile["field_id"], "research", "external_source_synthesis",
        synthesis, "public_sources", f"research_request:{request_row['id']}",
        confidence=0.5, status="candidate_evidence",
    )
    if str(request_row.get("reason") or "").startswith(
        "A field-related nano-os-agent experiment"
    ):
        now = iso_now()
        connection.execute(
            """
            UPDATE proposals SET status='completed', updated_at=?
            WHERE field_id=? AND kind='experiment_investigation'
              AND status IN ('pending','notified','deferred')
            """,
            (now, profile["field_id"]),
        )
        connection.commit()
    return synthesis


def retire_legacy_research_review_proposals(connection):
    """Close source-dump prompts created by older autonomous cycles."""
    now = iso_now()
    cursor = connection.execute(
        """
        UPDATE proposals SET status='completed', updated_at=?
        WHERE kind='research_review' AND status IN ('pending','notified','deferred')
        """,
        (now,),
    )
    connection.commit()
    return int(cursor.rowcount or 0)


def proposal_alert_diseases(proposal):
    diseases = set()
    for item in proposal.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        values = item.get("alert_diseases")
        if isinstance(values, list):
            diseases.update(str(value) for value in values if value)
    if not diseases:
        message = str(proposal.get("message") or "").lower()
        if any(token in message for token in ("black rot", "guignardia", "bidwellii")):
            diseases.add("black_rot")
        if any(token in message for token in ("powdery", "oïdi", "oidi", "oidio", "pmi")):
            diseases.add("powdery_mildew")
        if any(token in message for token in ("downy", "míldiu", "mildiu", "goidanich", "rossi")):
            diseases.add("downy_mildew")
    return sorted(diseases)


def proposal_source_operation(proposal):
    for item in proposal.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source_operation")
        if isinstance(source, dict) and source.get("event_id"):
            return source
    return None


def reconcile_proposals_from_operations(connection, profiles):
    """Close proposals only when a later confirmed event supplies the answer."""
    completed = []
    for profile in profiles:
        operations = field_operations(connection, profile["field_id"])
        rows = connection.execute(
            """
            SELECT * FROM proposals
            WHERE field_id=? AND kind IN ('field_check','operation_follow_up')
              AND status IN ('pending','notified','deferred')
            ORDER BY created_at
            """,
            (profile["field_id"],),
        ).fetchall()
        for row in rows:
            proposal = proposal_dict(row)
            created = parse_datetime(proposal.get("created_at"))
            diseases = set(proposal_alert_diseases(proposal))
            source_operation = proposal_source_operation(proposal)
            source_time = parse_datetime(
                source_operation.get("occurred_at") if source_operation else None
            )
            match = None
            for operation in operations:
                occurred = operation.get("occurred_datetime")
                if not occurred or (created and occurred <= created):
                    continue
                operation_type = operation.get("operation_type")
                if proposal["kind"] == "field_check":
                    if operation_type not in OUTCOME_OPERATION_TYPES | TREATMENT_OPERATION_TYPES:
                        continue
                    disease = str(operation.get("disease_id") or "")
                    if diseases and disease and disease not in diseases:
                        continue
                else:
                    if operation_type not in OUTCOME_OPERATION_TYPES:
                        continue
                    if source_time and occurred <= source_time:
                        continue
                match = operation
                break
            if not match:
                continue
            now = iso_now()
            connection.execute(
                "UPDATE proposals SET status='completed', updated_at=? WHERE id=?",
                (now, proposal["id"]),
            )
            upsert_fact(
                connection,
                profile["field_id"],
                "proposal_resolution",
                proposal["kind"],
                {
                    "proposal_id": proposal["id"],
                    "evidence_event_id": match["event_id"],
                    "evidence_type": match["operation_type"],
                    "evidence_at": match["occurred_at"],
                },
                "confirmed_operation",
                f"proposal-resolution:{proposal['id']}:{match['event_id']}",
                confidence=1.0,
                status="confirmed",
            )
            completed.append(proposal["id"])
    connection.commit()
    return completed


def proposal_media(proposal):
    alert_diseases = set(proposal_alert_diseases(proposal))
    media = []
    seen = set()
    if not alert_diseases:
        return media
    for item in proposal.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        disease = item.get("disease")
        if not disease and str(item.get("kind") or "").startswith("disease_state:"):
            disease = str(item["kind"]).split(":", 1)[1]
        if disease not in alert_diseases:
            continue
        path = str(item.get("plot_path") or "").strip()
        if not path:
            state_path = Path(str(item.get("source_ref") or ""))
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                path = str(state.get("plot_path") or state.get("plot") or "").strip()
            except (OSError, ValueError):
                path = ""
        if not path or path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        media.append({
            "type": "photo",
            "path": path,
            "source_path": path,
            "caption": proposal.get("title") or "",
            "mime_type": "image/png",
            "exists": True,
            "disease": disease,
        })
    return media[:3]


def notification_meta(payload, key, default=None):
    if key in payload:
        return payload.get(key)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return meta.get(key, default)


def recent_daily_notification_cover(proposal, outbox_dir):
    if proposal.get("kind") != "field_check":
        return None
    diseases = set(proposal_alert_diseases(proposal))
    if not diseases:
        return None
    outbox = Path(outbox_dir)
    if not outbox.is_dir():
        return None
    cutoff = utcnow() - dt.timedelta(hours=30)
    roles = {
        "three_disease_daily_overview",
        "black_rot_alert",
        "downy_mildew_alert",
        "powdery_mildew_alert",
    }
    try:
        candidates = sorted(outbox.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:100]
    except OSError:
        return None
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if payload.get("status") not in {"pending", "sent"}:
            continue
        if notification_meta(payload, "dispatch_role") not in roles:
            continue
        created = parse_datetime(payload.get("created_at"))
        if created and created < cutoff:
            continue
        covered_diseases = set(notification_meta(payload, "alert_diseases", []) or [])
        if not diseases.intersection(covered_diseases):
            continue
        covered_fields = set(notification_meta(payload, "alert_fields", []) or [])
        if covered_fields and proposal.get("field_id") not in covered_fields:
            continue
        return str(path)
    return None


def mark_proposal_notified(connection, proposal_id):
    now = iso_now()
    connection.execute(
        "UPDATE proposals SET status='notified', notified_at=?, updated_at=? WHERE id=?",
        (now, now, proposal_id),
    )
    connection.commit()


def notify_proposal(
    connection, proposal, state_dir,
    threshold=DEFAULT_NOTIFICATION_THRESHOLD,
):
    if not proposal:
        return {"status": "skipped", "reason": "no pending proposal"}
    if proposal["target"] != "farmer":
        return {"status": "skipped", "reason": "proposal is internal"}
    if proposal["priority"] < threshold:
        return {"status": "skipped", "reason": f"priority below notification threshold {threshold}"}
    if proposal.get("notified_at"):
        return {"status": "skipped", "reason": "proposal already notified"}
    outbox_dir = os.environ.get("PICOCLAW_OUTBOX", "/tmp/picoclaw_outbox")
    covered_by = recent_daily_notification_cover(proposal, outbox_dir)
    if covered_by:
        mark_proposal_notified(connection, proposal["id"])
        return {
            "status": "skipped_covered",
            "reason": "today's disease briefing already covers this field and signal",
            "proposal_id": proposal["id"],
            "covered_by": covered_by,
        }
    notify_script = Path(__file__).resolve().parents[1] / "farmer_notify" / "run.py"
    if not notify_script.exists():
        return {"status": "error", "reason": f"farmer-notify missing: {notify_script}"}
    message = proposal["message"] + f"\n\nRef: PF-{proposal['id']}"
    media = proposal_media(proposal)
    alert_diseases = proposal_alert_diseases(proposal)
    payload = {
        "title": proposal["title"], "message": message,
        "caption": proposal["title"], "channel": "picoclaw_telegram",
        "text_after_photo": message if media else "",
        "attachments": media,
        "media": media,
        "dispatch_role": "proactive_field_proposal", "field": proposal.get("field_id"),
        "alert_diseases": alert_diseases,
        "outbox_dir": outbox_dir,
        "dedupe_minutes": 1440,
        "meta": {
            "proposal_id": proposal["id"], "proposal_kind": proposal["kind"],
            "requires_confirmation": proposal["requires_confirmation"],
            "alert_diseases": alert_diseases,
        },
    }
    proc = subprocess.run(
        [sys.executable, str(notify_script)], input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )
    try:
        result = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        result = {"raw_stdout": proc.stdout.decode("utf-8", "replace")}
    if proc.returncode == 0 and result.get("status") in {"success", "skipped_duplicate"}:
        mark_proposal_notified(connection, proposal["id"])
        return {"status": result.get("status"), "proposal_id": proposal["id"], "outbox": result}
    trace(state_dir, "notification_error", {"proposal_id": proposal["id"], "stderr": proc.stderr.decode("utf-8", "replace")})
    return {"status": "error", "proposal_id": proposal["id"], "stderr": proc.stderr.decode("utf-8", "replace"), "result": result}


def compact_status(connection, field_id=None):
    profiles_query = "SELECT * FROM field_profiles"
    values = []
    if field_id:
        profiles_query += " WHERE field_id=?"
        values.append(field_id)
    profiles_query += " ORDER BY name"
    profiles = []
    for row in connection.execute(profiles_query, values):
        item = dict(row)
        item["profile"] = json.loads(item.pop("profile_json"))
        profiles.append(item)
    proposal_query = "SELECT * FROM proposals WHERE status IN ('pending','notified','deferred')"
    proposal_values = []
    if field_id:
        proposal_query += " AND field_id=?"
        proposal_values.append(field_id)
    proposal_query += " ORDER BY priority DESC, created_at LIMIT 20"
    proposals = [proposal_dict(row) for row in connection.execute(proposal_query, proposal_values)]
    observations = {}
    operations = {}
    facts = {}
    derived_insights = {}
    for profile in profiles:
        current_field = profile["field_id"]
        observations[current_field] = [
            {
                "kind": item["kind"], "effective_day": item.get("effective_day"),
                "freshness": item["freshness"], "source_ref": item["source_ref"],
                "payload": item["payload"],
            }
            for item in latest_observations(connection, current_field)
        ]
        operation_rows = connection.execute(
            "SELECT * FROM operations WHERE field_id=? ORDER BY occurred_at DESC LIMIT 20",
            (current_field,),
        ).fetchall()
        operations[current_field] = []
        for row in operation_rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            operations[current_field].append(item)
        fact_rows = connection.execute(
            "SELECT * FROM facts WHERE field_id=? ORDER BY updated_at DESC LIMIT 50",
            (current_field,),
        ).fetchall()
        facts[current_field] = []
        for row in fact_rows:
            item = dict(row)
            item["value"] = json.loads(item.pop("value_json"))
            facts[current_field].append(item)
        derived_insights[current_field] = [
            item for item in facts[current_field]
            if item.get("source_type") == "derived_confirmed_sequence"
        ]
    decision_query = (
        "SELECT d.*, p.field_id, p.kind AS proposal_kind "
        "FROM decisions d JOIN proposals p ON p.id=d.proposal_id"
    )
    decision_values = []
    if field_id:
        decision_query += " WHERE p.field_id=?"
        decision_values.append(field_id)
    decision_query += " ORDER BY d.created_at DESC LIMIT 20"
    decisions = [dict(row) for row in connection.execute(decision_query, decision_values)]
    request = pending_research(connection, field_id)
    return {
        "profiles": profiles,
        "observations": observations,
        "operations": operations,
        "facts": facts,
        "derived_insights": derived_insights,
        "proposals": proposals,
        "decisions": decisions,
        "investigations": investigations.list_investigations(connection, field_id),
        "next_research": request,
    }


def mode_observe(connection, params, create=False):
    repo_path = params.get("repo_path") or DEFAULT_REPO
    selected_field = params.get("field") or None
    profiles = field_profiles(repo_path)
    if selected_field:
        profiles = [profile for profile in profiles if profile["field_id"] == selected_field]
    if not profiles:
        return {"status": "error", "error": "no configured fields found", "repo_path": repo_path}
    retired_source_reviews = retire_legacy_research_review_proposals(connection)
    changed_profiles = save_profiles(connection, profiles)
    profile_facts(connection, profiles)
    recovered_farmer_evidence = backfill_leaf_wetness_decisions(connection, repo_path)
    observations = discover_states(repo_path, profiles, selected_field)
    nano_observations = discover_nano_experiments(
        params.get("nano_root") or "/root/nano-os-agent", profiles, selected_field,
    )
    observations.extend(nano_observations)
    inserted_observations = store_observations(connection, observations)
    nano_insights = derive_nano_insights(connection, profiles)
    operations = ingest_operations(connection, repo_path, selected_field)
    derived_insights = derive_operation_insights(connection, profiles)
    reconciled_proposals = reconcile_proposals_from_operations(connection, profiles)
    investigation_records = {
        profile["field_id"]: run_field_investigations(connection, profile, repo_path)
        for profile in profiles
    }
    proposals = (
        generate_proposals(connection, profiles, investigation_records, params)
        if create else []
    )
    return {
        "status": "success", "mode": "tick" if create else "observe",
        "repo_path": repo_path, "fields": [profile["field_id"] for profile in profiles],
        "profiles_changed": changed_profiles,
        "retired_source_review_proposals": retired_source_reviews,
        "recovered_farmer_evidence": recovered_farmer_evidence,
        "observations": {
            "seen": len(observations), "inserted": inserted_observations,
            "disease_states": len(observations) - len(nano_observations),
            "nano_experiments": len(nano_observations),
            "nano_insights": nano_insights,
        },
        "operations": {
            **operations,
            "derived_insights": derived_insights,
            "reconciled_proposals": reconciled_proposals,
        },
        "investigations": compact_investigations(investigation_records),
        "proposals": proposals,
        "pending_proposal": next_proposal(connection, selected_field),
        "research_request": pending_research(connection, selected_field),
    }


def compact_investigations(investigation_records):
    """Report what was investigated without repeating every stored metric."""
    summary = []
    for field_id, records in sorted(investigation_records.items()):
        for record in records:
            summary.append({
                "field_id": field_id,
                "investigation_id": record.get("id"),
                "topic": record.get("topic"),
                "verdict": record.get("verdict"),
                "sample_size": record.get("sample_size"),
                "confidence": record.get("confidence"),
                "open_question": record.get("open_question"),
                "created": record.get("created"),
            })
    return summary


def mode_investigate(connection, params):
    repo_path = params.get("repo_path") or DEFAULT_REPO
    selected_field = params.get("field") or None
    profiles = field_profiles(repo_path)
    if selected_field:
        profiles = [profile for profile in profiles if profile["field_id"] == selected_field]
    if not profiles:
        return {"status": "error", "error": "no configured fields found", "repo_path": repo_path}
    save_profiles(connection, profiles)
    records = {
        profile["field_id"]: run_field_investigations(connection, profile, repo_path)
        for profile in profiles
    }
    return {
        "status": "success",
        "mode": "investigate",
        "repo_path": repo_path,
        "fields": [profile["field_id"] for profile in profiles],
        "investigations": [
            item for field_records in records.values() for item in field_records
        ],
        "summary": compact_investigations(records),
        "safety": (
            "Findings are model-derived evidence. No treatment, purchase, or hardware "
            "action was created."
        ),
    }


def mode_research(connection, params):
    field_id = params.get("field") or None
    request = pending_research(connection, field_id)
    query = str(params.get("query") or "").strip()
    if query:
        queue_research(
            connection, field_id, query,
            str(params.get("reason") or "Operator-requested bounded research"),
            params.get("evidence") if isinstance(params.get("evidence"), list) else [],
        )
        request = pending_research(connection, field_id)
    if not request:
        return {"status": "skipped", "reason": "no queued research request"}
    credentials = load_search_credentials(
        params.get("repo_path") or DEFAULT_REPO,
        params.get("search_env"),
    )
    sources, errors = perform_search(
        request["query"], int(params.get("limit") or 5), credentials,
    )
    inserted = store_research(connection, request, sources)
    synthesis = store_research_synthesis(connection, request, sources)
    return {
        "status": "success" if sources else "error", "mode": "research",
        "request": request, "sources": sources, "inserted": inserted,
        "proposal": None, "synthesis": synthesis, "errors": errors,
        "safety": (
            "Candidate sources were stored for autonomous method comparison. No farmer "
            "review request, treatment action, threshold change, or hardware action was created."
        ),
    }


def mode_ingest_research(connection, params):
    request_id = params.get("request_id")
    if request_id:
        row = connection.execute("SELECT * FROM research_requests WHERE id=?", (int(request_id),)).fetchone()
        request = dict(row) if row else None
        if request:
            request["evidence"] = json.loads(request.pop("evidence_json"))
    else:
        request = pending_research(connection, params.get("field"))
    if not request:
        return {"status": "error", "error": "research request not found"}
    sources = normalize_sources(params.get("sources") or [], "external", int(params.get("limit") or 10))
    if not sources:
        return {"status": "error", "error": "no valid public source URLs supplied"}
    inserted = store_research(connection, request, sources)
    synthesis = store_research_synthesis(connection, request, sources)
    return {
        "status": "success", "request_id": request["id"], "inserted": inserted,
        "sources": sources, "proposal": None, "synthesis": synthesis,
    }


def mode_decision(connection, params):
    decision = str(params.get("decision") or "").strip().lower()
    if decision not in ALLOWED_DECISIONS:
        return {"status": "error", "error": f"decision must be one of {sorted(ALLOWED_DECISIONS)}"}
    proposal_id = params.get("proposal_id")
    proposal = proposal_by_id(connection, int(proposal_id)) if proposal_id else next_proposal(connection, params.get("field"), only_unnotified=False)
    if not proposal:
        return {"status": "error", "error": "no matching pending proposal"}
    note = str(params.get("note") or "").strip()
    option_id = str(params.get("option_id") or "").strip()
    wetness_reply = None
    wetness_observation_route = (
        decision == "accepted"
        and proposal_analysis(proposal) == investigations.TOPIC_WETNESS
        and option_id == "same_day_canopy_check"
    )
    if wetness_observation_route:
        explicit_wetness = params.get("leaf_wet")
        wetness_reply = (
            bool(explicit_wetness)
            if isinstance(explicit_wetness, bool)
            else leaf_wetness_reply(note)
        )
        if wetness_reply is None:
            return {
                "status": "confirmation_required",
                "mode": "record_decision",
                "proposal_id": proposal["id"],
                "written": False,
                "missing": ["leaf_wetness_observation"],
                "confirmation_question": (
                    "Confirmeu si les fulles eren mullades o seques."
                    if str(params.get("language") or "").lower().startswith("ca") else
                    "Confirme si las hojas estaban mojadas o secas."
                    if str(params.get("language") or "").lower().startswith("es") else
                    "Confirm whether the leaves were wet or dry."
                ),
            }
    now = iso_now()
    connection.execute(
        "INSERT INTO decisions(proposal_id, decision, note, source, created_at) VALUES(?,?,?,?,?)",
        (proposal["id"], decision, note, str(params.get("source") or "farmer"), now),
    )
    new_status = decision
    cooldown = proposal.get("cooldown_until")
    if decision == "deferred":
        cooldown = (utcnow() + dt.timedelta(days=int(params.get("defer_days") or 3))).isoformat()
    if decision == "rejected":
        # "No" is an answer, not a delay. The subject stays closed for the season
        # unless new evidence changes the underlying finding.
        cooldown = (utcnow() + dt.timedelta(days=REJECTED_COOLDOWN_DAYS)).isoformat()
    connection.execute(
        "UPDATE proposals SET status=?, cooldown_until=?, updated_at=? WHERE id=?",
        (new_status, cooldown, now, proposal["id"]),
    )
    investigation_id = proposal_investigation_id(proposal)
    if investigation_id and decision in {"accepted", "rejected"}:
        investigations.mark_investigation(
            connection, investigation_id,
            "answered" if decision == "accepted" else "closed_by_farmer",
        )
    if note and decision == "corrected":
        upsert_fact(
            connection, proposal.get("field_id") or "board", "farmer_correction",
            proposal["kind"], note, "farmer_confirmed", f"proposal:{proposal['id']}",
            confidence=1.0, status="confirmed",
        )
    field_evidence = None
    retired_research_requests = []
    model_refresh = None
    autonomous_follow_up = None
    send_text = None
    if wetness_observation_route:
        field_evidence = record_leaf_wetness_observation(
            connection, proposal, wetness_reply, note, params,
        )
        retired_research_requests = close_wetness_research(
            connection, proposal.get("field_id"),
        )
        repo_path = str(params.get("repo_path") or DEFAULT_REPO)
        model_refresh = refresh_black_rot_from_observation(
            repo_path, proposal.get("field_id"), field_evidence["observed_at"],
        )
        profiles = [
            profile for profile in field_profiles(repo_path)
            if profile["field_id"] == proposal.get("field_id")
        ]
        if profiles:
            records = run_field_investigations(connection, profiles[0], repo_path)
            follow_up_record = next(
                (
                    record
                    for record in records
                    if record.get("topic") == investigations.TOPIC_WETNESS
                ),
                None,
            )
            if follow_up_record:
                autonomous_follow_up = {
                    "topic": follow_up_record.get("topic"),
                    "verdict": follow_up_record.get("verdict"),
                    "method": follow_up_record.get("method"),
                    "sample_size": follow_up_record.get("sample_size"),
                    "findings": follow_up_record.get("findings"),
                    "limitations": follow_up_record.get("limitations"),
                }
                rendered = investigations.render_report(
                    profiles[0].get("language"), profiles[0].get("name"),
                    follow_up_record,
                )
                if rendered:
                    send_text = f"{rendered['title']}\n{rendered['message']}"
        # The field answer and its analysis complete this question now. Keeping
        # the proposal as merely accepted would create a redundant closure
        # notification during tomorrow's proactive cycle.
        connection.execute(
            "UPDATE proposals SET status='completed', updated_at=? WHERE id=?",
            (iso_now(), proposal["id"]),
        )
    connection.commit()
    return {
        "status": "success", "proposal_id": proposal["id"], "decision": decision,
        "option_id": option_id or None,
        "note": note, "executed_action": False,
        "reopens_after": cooldown if decision == "rejected" else None,
        "research_feedback": mirror_decision_to_research(proposal, decision, note, params),
        "field_evidence": field_evidence,
        "retired_research_requests": retired_research_requests,
        "model_refresh": model_refresh,
        "autonomous_follow_up": autonomous_follow_up,
        "send_text": send_text,
        "must_send_exactly": bool(send_text),
        "message": (
            "Farmer-confirmed leaf wetness was stored and the local black-rot investigation was rerun. "
            "The answered question is closed; no treatment or hardware action was executed."
            if wetness_observation_route else
            "Decision recorded. No treatment or hardware action was executed automatically."
        ),
    }


def research_subject(field_id):
    return f"vineyard:{field_id or 'board'}"


def proposal_analysis(proposal):
    """The research subject this proposal's answer is evidence about."""
    kind = str(proposal.get("kind") or "")
    if kind.startswith(INVESTIGATION_KIND_PREFIX):
        return kind[len(INVESTIGATION_KIND_PREFIX):].split(":", 1)[0]
    return kind or "proposal"


def proposal_research_finding_id(proposal):
    for item in proposal.get("evidence") or []:
        if isinstance(item, dict) and item.get("research_finding_id"):
            return int(item["research_finding_id"])
    return None


def mirror_decision_to_research(proposal, decision, note, params):
    """Echo a farmer decision into the research engine.

    The farmer answers over Telegram, so the engine that raised the underlying
    question never sees the reply unless it is echoed. Two refusals on one
    subject are what make the board ask whether it should be sending fewer
    messages at all, so this is the loop that lets it stop.

    Best effort by design: a board without the research skill installed keeps
    working exactly as before.
    """
    state_dir = (
        params.get("research_state_dir")
        or os.environ.get("NORA_STATE_DIR")
        or "/root/.picoclaw/workspace/research"
    )
    try:
        import engine as research_engine
    except ImportError as exc:
        return {"mirrored": False, "reason": f"research engine unavailable: {exc}"}
    finding_id = proposal_research_finding_id(proposal)
    try:
        connection = research_engine.connect(state_dir)
        try:
            if finding_id:
                # This message carried one of the engine's own findings, so the
                # answer goes back to it directly: accepting the offer to look
                # further is what opens the wider question.
                stored = research_engine.record_decision(
                    connection, finding_id, decision,
                    option_id=params.get("option_id"), note=note or None,
                    source="proactive-field-agent",
                    drafts_dir=params.get("task_drafts_dir"),
                )
                record = {
                    "finding_id": finding_id,
                    "subject": (stored or {}).get("subject"),
                    "analysis": (stored or {}).get("analysis"),
                    "decision": decision,
                    "option_id": params.get("option_id"),
                    "follow_up_question": (stored or {}).get("follow_up_question"),
                    "drafted_task": (stored or {}).get("drafted_task"),
                }
            else:
                record = research_engine.record_external_decision(
                    connection,
                    research_subject(proposal.get("field_id")),
                    proposal_analysis(proposal),
                    decision,
                    option_id=params.get("option_id"),
                    note=note or None,
                    source="proactive-field-agent",
                )
        finally:
            connection.close()
    except Exception as exc:  # storage on another skill's state directory
        return {"mirrored": False, "reason": str(exc)}
    return {"mirrored": True, "state_dir": state_dir, **record}


def proposal_investigation_id(proposal):
    for item in proposal.get("evidence") or []:
        if isinstance(item, dict) and item.get("investigation_id"):
            return int(item["investigation_id"])
    return None


def proposal_investigation(connection, proposal):
    investigation_id = proposal_investigation_id(proposal)
    return investigations.investigation_by_id(connection, investigation_id) if investigation_id else None


def proposal_sent_options(proposal, record):
    """The options the farmer actually received, not the current finding's list.

    A later tick may drop an option, for example once a hardware suggestion has
    been used up. The reply must still resolve against the message that was sent.
    """
    stored = {
        option.get("id"): option
        for option in ((record or {}).get("options") or [])
        if option.get("id")
    }
    sent = []
    for item in proposal.get("evidence") or []:
        if isinstance(item, dict) and item.get("options"):
            sent = [str(value) for value in item["options"]]
            break
    if not sent:
        return list(stored.values())
    return [stored.get(option_id) or {"id": option_id, "params": {}} for option_id in sent]


def extract_proposal_id(value):
    match = re.search(r"\bPF[-_ ]?(\d+)\b", str(value or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def normalized_lookup(value):
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", raw.lower()).split())


def explicit_feedback_disease(value):
    text = normalized_lookup(value)
    if any(token in text for token in (
        "black rot", "blackrot", "guignardia", "bidwellii", "phyllosticta ampelicida",
    )):
        return "black_rot"
    if any(token in text for token in ("powdery", "oidium", "oidi", "oidio")):
        return "powdery_mildew"
    if any(token in text for token in ("downy", "mildiu", "mildio", "goidanich", "rossi")):
        return "downy_mildew"
    return ""


def resolve_context_field(connection, requested, raw_text):
    rows = connection.execute(
        "SELECT field_id, name FROM field_profiles ORDER BY length(name) DESC, name"
    ).fetchall()
    if requested:
        wanted = normalized_lookup(requested)
        for row in rows:
            if wanted in {normalized_lookup(row["field_id"]), normalized_lookup(row["name"])}:
                return row["field_id"]
        return str(requested)
    text = normalized_lookup(raw_text)
    matches = []
    for row in rows:
        aliases = {normalized_lookup(row["field_id"]), normalized_lookup(row["name"])}
        aliases.discard("")
        if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases):
            matches.append(row["field_id"])
    return matches[0] if len(set(matches)) == 1 else None


def proposal_context_question(language, field_name, diseases, missing):
    lang = str(language or "en").lower()[:2]
    disease_labels = {
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
    labels = disease_labels.get(lang, disease_labels["en"])
    disease_text = ", ".join(labels.get(item, item) for item in diseases)
    if "proposal" in missing:
        return {
            "ca": "No puc relacionar aquesta resposta amb una única proposta pendent. Indiqueu la referència PF, el camp i la malaltia.",
            "es": "No puedo relacionar esta respuesta con una única propuesta pendiente. Indique la referencia PF, el campo y la enfermedad.",
            "en": "I cannot link this reply to one pending proposal. Provide the PF reference, field, and disease.",
        }.get(lang, "I cannot link this reply to one pending proposal. Provide the PF reference, field, and disease.")
    if "disease" in missing:
        return {
            "ca": f"La resposta correspon a {field_name}. Confirmeu a quina malaltia es refereix: {disease_text}.",
            "es": f"La respuesta corresponde a {field_name}. Confirme a qué enfermedad se refiere: {disease_text}.",
            "en": f"The reply concerns {field_name}. Confirm which disease it concerns: {disease_text}.",
        }.get(lang, f"The reply concerns {field_name}. Confirm which disease it concerns: {disease_text}.")
    return {
        "ca": f"He relacionat la resposta amb {field_name} i {disease_text}. Encara no s'ha desat res; confirmeu l'esborrany estructurat.",
        "es": f"He relacionado la respuesta con {field_name} y {disease_text}. Aún no se ha guardado nada; confirme el borrador estructurado.",
        "en": f"I linked the reply to {field_name} and {disease_text}. Nothing has been stored yet; confirm the structured draft.",
    }.get(lang, f"I linked the reply to {field_name} and {disease_text}. Nothing has been stored yet; confirm the structured draft.")


def operation_context_question(language, field_name, source_operation, route):
    lang = str(language or "en").lower()[:2]
    operation = localized_operation_description(
        {
            "operation_type": source_operation.get("operation_type"),
            "payload": {},
        },
        language,
    )
    day = str(source_operation.get("occurred_at") or "")[:10]
    if route == "farmer-feedback-capture":
        texts = {
            "ca": "He relacionat la resposta amb {field} i {operation} del {day}. Encara no s'ha desat res; confirmeu el resultat de la inspecció i la malaltia objectiu en l'esborrany estructurat.",
            "es": "He relacionado la respuesta con {field} y {operation} del {day}. Aún no se ha guardado nada; confirme el resultado de la inspección y la enfermedad objetivo en el borrador estructurado.",
            "en": "I linked the reply to {field} and {operation} on {day}. Nothing has been stored; confirm the scouting outcome and target disease in the structured draft.",
        }
    else:
        texts = {
            "ca": "He relacionat la resposta amb {field} i {operation} del {day}. Encara no s'ha desat res; confirmeu què vau observar i la data de l'observació.",
            "es": "He relacionado la respuesta con {field} y {operation} del {day}. Aún no se ha guardado nada; confirme qué observó y la fecha de la observación.",
            "en": "I linked the reply to {field} and {operation} on {day}. Nothing has been stored; confirm what you observed and the observation date.",
        }
    return texts.get(lang, texts["en"]).format(
        field=field_name,
        operation=operation,
        day=day,
    )


def investigation_context_question(language, field_name, options):
    lang = str(language or "en").lower()[:2]
    option_text = investigations.render_options(language, options)
    if option_text:
        texts = {
            "ca": "La resposta és sobre la comprovació que vaig fer a {field}. Encara no s'ha desat res: confirmeu quina opció trieu ({options}), o digueu que ho deixem estar.",
            "es": "La respuesta es sobre la comprobación que hice en {field}. Aún no se ha guardado nada: confirme qué opción elige ({options}), o dígame que lo dejemos.",
            "en": "The reply concerns the check I ran at {field}. Nothing has been stored: confirm which option you choose ({options}), or tell me to drop it.",
        }
    else:
        texts = {
            "ca": "La resposta és sobre la comprovació que vaig fer a {field}. Encara no s'ha desat res: confirmeu si voleu que hi continuï o que ho tanqui.",
            "es": "La respuesta es sobre la comprobación que hice en {field}. Aún no se ha guardado nada: confirme si quiere que siga o que lo cierre.",
            "en": "The reply concerns the check I ran at {field}. Nothing has been stored: confirm whether I should carry on or close it.",
        }
    return texts.get(lang, texts["en"]).format(field=field_name, options=option_text)


def mode_proposal_context(connection, params):
    raw_text = params.get("raw_text") or ""
    proposal_id = params.get("proposal_id") or extract_proposal_id(raw_text)
    proposal = proposal_by_id(connection, int(proposal_id)) if proposal_id else None
    candidates = []
    if not proposal and not proposal_id:
        clauses = [
            "kind IN ('field_check','operation_follow_up')",
            "status IN ('pending','notified','deferred')",
        ]
        values = []
        selected_field = resolve_context_field(connection, params.get("field"), raw_text)
        if selected_field:
            clauses.append("field_id=?")
            values.append(selected_field)
        rows = connection.execute(
            "SELECT * FROM proposals WHERE " + " AND ".join(clauses) +
            " ORDER BY priority DESC, created_at DESC LIMIT 3",
            values,
        ).fetchall()
        candidates = [proposal_dict(row) for row in rows]
        explicit_disease = explicit_feedback_disease(raw_text)
        if explicit_disease:
            candidates = [
                item for item in candidates
                if explicit_disease in (
                    proposal_alert_diseases(item)
                    + ([str((proposal_source_operation(item) or {}).get("disease"))]
                       if (proposal_source_operation(item) or {}).get("disease") else [])
                )
            ]
        if len(candidates) == 1:
            proposal = candidates[0]
    if not proposal:
        return {
            "status": "confirmation_required",
            "mode": "proposal_context",
            "written": False,
            "missing": ["proposal", "field", "disease"],
            "candidates": [
                {
                    "proposal_id": item["id"],
                    "field": item.get("field_id"),
                    "alert_diseases": proposal_alert_diseases(item),
                }
                for item in candidates
            ],
            "confirmation_question": proposal_context_question(
                params.get("language") or "en", "", [], ["proposal"],
            ),
        }
    profile = connection.execute(
        "SELECT name, language FROM field_profiles WHERE field_id=?",
        (proposal.get("field_id"),),
    ).fetchone()
    field_name = profile["name"] if profile else proposal.get("field_id") or ""
    language = (profile["language"] if profile else None) or params.get("language") or "en"
    if str(proposal.get("kind") or "").startswith(RESEARCH_KIND_PREFIX):
        evidence = next(
            (item for item in proposal.get("evidence") or []
             if isinstance(item, dict) and item.get("research_finding_id")),
            {},
        )
        options = [
            {"id": option, "cost": "none", "params": {}}
            for option in evidence.get("options") or []
        ]
        return {
            "status": "success",
            "mode": "proposal_context",
            "proposal_id": proposal["id"],
            "proposal_kind": proposal["kind"],
            "field": proposal.get("field_id"),
            "field_name": field_name,
            "alert_diseases": [],
            "disease": None,
            "research_finding": {
                "id": evidence.get("research_finding_id"),
                "subject": evidence.get("subject"),
                "analysis": evidence.get("analysis"),
                "method": evidence.get("method"),
                "options": evidence.get("options") or [],
                "limitations": evidence.get("limitations") or [],
            },
            "missing": [],
            "written": False,
            "next_route": "proactive-field-agent",
            "next_mode": "record_decision",
            "confirmation_question": investigation_context_question(
                language, field_name, options,
            ),
        }
    if str(proposal.get("kind") or "").startswith(INVESTIGATION_KIND_PREFIX):
        record = proposal_investigation(connection, proposal)
        options = proposal_sent_options(proposal, record)
        return {
            "status": "success",
            "mode": "proposal_context",
            "proposal_id": proposal["id"],
            "proposal_kind": proposal["kind"],
            "field": proposal.get("field_id"),
            "field_name": field_name,
            "alert_diseases": [],
            "disease": None,
            "investigation": {
                "id": (record or {}).get("id"),
                "topic": (record or {}).get("topic"),
                "question": (record or {}).get("question"),
                "verdict": (record or {}).get("verdict"),
                "findings": (record or {}).get("findings"),
                "limitations": (record or {}).get("limitations"),
                "options": [option.get("id") for option in options],
                "option_texts": investigations.render_options(language, options),
            },
            "missing": [],
            "written": False,
            "next_route": "proactive-field-agent",
            "next_mode": "record_decision",
            "confirmation_question": investigation_context_question(
                language, field_name, options,
            ),
        }
    if proposal.get("kind") == "operation_follow_up":
        source_operation = proposal_source_operation(proposal) or {}
        disease = str(source_operation.get("disease") or "")
        treatment_route = (
            source_operation.get("operation_type") in TREATMENT_OPERATION_TYPES
            or bool(disease)
        )
        next_route = "farmer-feedback-capture" if treatment_route else "proactive-field-agent"
        return {
            "status": "success",
            "mode": "proposal_context",
            "proposal_id": proposal["id"],
            "proposal_kind": proposal["kind"],
            "field": proposal.get("field_id"),
            "field_name": field_name,
            "alert_diseases": [disease] if disease else [],
            "disease": disease or None,
            "source_operation": source_operation,
            "operation_type": "follow_up_observation",
            "missing": [],
            "written": False,
            "next_route": next_route,
            "next_mode": "draft_operation" if not treatment_route else None,
            "confirmation_question": operation_context_question(
                language, field_name, source_operation, next_route,
            ),
        }
    diseases = proposal_alert_diseases(proposal)
    explicit_disease = explicit_feedback_disease(raw_text)
    if explicit_disease in diseases:
        diseases = [explicit_disease]
    missing = [] if len(diseases) == 1 else ["disease"]
    return {
        "status": "success" if not missing else "confirmation_required",
        "mode": "proposal_context",
        "proposal_id": proposal["id"],
        "field": proposal.get("field_id"),
        "field_name": field_name,
        "alert_diseases": diseases,
        "disease": diseases[0] if len(diseases) == 1 else None,
        "missing": missing,
        "written": False,
        "next_route": "farmer-feedback-capture" if not missing else None,
        "confirmation_question": proposal_context_question(
            language, field_name, diseases, missing,
        ),
    }


def mode_remember(connection, params):
    required = [key for key in ("field", "predicate", "value") if params.get(key) in (None, "")]
    if required:
        return {"status": "error", "error": "missing: " + ", ".join(required)}
    confirmed = as_bool(params.get("confirmed"), False)
    source_type = "farmer_confirmed" if confirmed else "operator_provisional"
    source_ref = str(params.get("source_ref") or f"manual:{digest(params)[:16]}")
    upsert_fact(
        connection, str(params["field"]), str(params.get("subject") or "field"),
        str(params["predicate"]), params["value"], source_type, source_ref,
        confidence=1.0 if confirmed else 0.5,
        status="confirmed" if confirmed else "provisional",
    )
    return {"status": "success", "confirmed": confirmed, "source_ref": source_ref}


def infer_operation_type(raw_text):
    text = str(raw_text or "").lower()
    patterns = (
        ("treatment", ("spray", "tractament", "tratamiento", "aplicat", "aplicado", "fungic", "copper", "sofre", "azufre")),
        ("inspection", ("inspect", "scout", "revisat", "revisado", "dosser net", "canopy clean")),
        ("pruning", ("prun", "poda", "esporga")),
        ("mowing", ("mow", "sega", "desbross", "desbro")),
        ("soil_work", ("till", "cultivat", "llaur", "laboreo", "subsol")),
        ("irrigation", ("irrig", "regat", "riego")),
        ("fertilization", ("fertil", "abon", "compost", "esmena")),
        ("cover_crop", ("cover crop", "coberta vegetal", "cubierta vegetal", "sown", "sembr")),
        ("harvest", ("harvest", "verema", "vendimia", "collita")),
        ("planting", ("planting", "plantat", "plantado", "replant")),
        ("sensor_installation", ("sensor", "sonda", "datalogger")),
    )
    for operation, tokens in patterns:
        if any(token in text for token in tokens):
            return operation
    return ""


def normalize_operation_type(value):
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized[:80]


def operation_language(connection, field_id, fallback="en"):
    if field_id:
        row = connection.execute(
            "SELECT language FROM field_profiles WHERE field_id=?", (field_id,)
        ).fetchone()
        if row and row["language"]:
            return row["language"]
    return fallback


def resolve_operation_field(connection, requested):
    if requested:
        row = connection.execute(
            "SELECT field_id, name FROM field_profiles WHERE field_id=? OR lower(name)=lower(?)",
            (str(requested), str(requested)),
        ).fetchone()
        return dict(row) if row else None
    rows = connection.execute("SELECT field_id, name FROM field_profiles ORDER BY name").fetchall()
    return dict(rows[0]) if len(rows) == 1 else None


def operation_confirmation(language, draft, missing):
    lang = str(language or "en").lower()[:2]
    if missing:
        labels = {
            "ca": "Abans de desar l'operació, indiqueu: ",
            "es": "Antes de guardar la operación, indique: ",
            "en": "Before saving the operation, provide: ",
        }
        return labels.get(lang, labels["en"]) + ", ".join(missing) + "."
    detail = json.dumps(draft.get("details") or {}, ensure_ascii=False, sort_keys=True)
    texts = {
        "ca": "Confirmeu que és correcte abans de desar-ho",
        "es": "Confirme que es correcto antes de guardarlo",
        "en": "Confirm this is correct before it is stored",
    }
    return (
        f"{texts.get(lang, texts['en'])}: {draft['field_name']} — "
        f"{draft['operation_type']} — {draft['occurred_at']} — {detail}."
    )


def mode_operation(connection, params, force_draft=False):
    raw_text = str(params.get("raw_text") or "").strip()
    field = resolve_operation_field(connection, params.get("field"))
    operation_type = normalize_operation_type(
        params.get("operation_type") or infer_operation_type(raw_text)
    )
    occurred_at = str(params.get("occurred_at") or params.get("date") or "").strip()
    details = params.get("details") if isinstance(params.get("details"), dict) else {}
    missing = []
    if not field:
        missing.append("field")
    if not operation_type:
        missing.append("operation type")
    if not occurred_at:
        missing.append("date/time")
    draft = {
        "field_id": field.get("field_id") if field else None,
        "field_name": field.get("name") if field else str(params.get("field") or ""),
        "operation_type": operation_type,
        "occurred_at": occurred_at,
        "details": details,
        "raw_text": raw_text,
    }
    language = operation_language(
        connection, draft.get("field_id"), str(params.get("language") or "en")
    )
    if operation_type in DISEASE_OPERATION_TYPES:
        return {
            "status": "redirect",
            "route": "farmer-feedback-capture",
            "reason": "Treatments and disease inspections require product/catalog and disease-state validation.",
            "draft": draft,
            "missing": missing,
        }
    confirmed = as_bool(params.get("confirmed"), False) and not force_draft
    if missing or not confirmed:
        return {
            "status": "confirmation_required",
            "draft": draft,
            "missing": missing,
            "confirmation_question": operation_confirmation(language, draft, missing),
            "written": False,
        }
    try:
        parsed_date = parse_datetime(occurred_at)
        if not parsed_date and len(occurred_at) == 10:
            parsed_date = dt.datetime.fromisoformat(occurred_at).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        parsed_date = None
    if not parsed_date:
        return {
            "status": "confirmation_required", "draft": draft,
            "missing": ["valid ISO date/time"],
            "confirmation_question": operation_confirmation(language, draft, ["valid ISO date/time"]),
            "written": False,
        }
    draft["occurred_at"] = parsed_date.isoformat()
    event_id = digest({"field": draft["field_id"], "operation": draft, "confirmed": True})
    connection.execute(
        """
        INSERT OR IGNORE INTO operations(
            event_id, field_id, disease_id, operation_type, occurred_at,
            payload_json, source_ref, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            event_id, draft["field_id"], str(params.get("disease") or ""),
            operation_type, draft["occurred_at"],
            json_text({**draft, "confirmed": True}),
            str(params.get("source_ref") or "farmer_confirmed_general_operation"),
            iso_now(),
        ),
    )
    connection.commit()
    upsert_fact(
        connection, draft["field_id"], "field_operation", f"last_{operation_type}",
        {"occurred_at": draft["occurred_at"], "details": details},
        "farmer_confirmed", f"operation:{event_id}", confidence=1.0, status="confirmed",
    )
    return {
        "status": "success", "written": True, "event_id": event_id,
        "operation": draft,
        "supabase": "local proactive memory only; treatment/inspection events use farmer-feedback-capture for Supabase sync",
    }


def mode_self_test(connection, params):
    repo_path = params.get("repo_path") or DEFAULT_REPO
    nano_root = params.get("nano_root") or "/root/nano-os-agent"
    profiles = field_profiles(repo_path)
    states = discover_states(repo_path, profiles)
    coverage = {profile["field_id"]: {} for profile in profiles}
    for item in states:
        coverage[item["field_id"]][item["payload"].get("disease")] = item["freshness"]
    expected = {"downy_mildew", "powdery_mildew", "black_rot"}
    missing = {
        field_id: sorted(expected - set(diseases))
        for field_id, diseases in coverage.items()
        if expected - set(diseases)
    }
    stale = {
        field_id: sorted(disease for disease, freshness in diseases.items() if freshness != "current")
        for field_id, diseases in coverage.items()
        if any(freshness != "current" for freshness in diseases.values())
    }
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    notify_script = Path(__file__).resolve().parents[1] / "farmer_notify" / "run.py"
    journals = [
        str(path) for path in (Path(nano_root) / "experiments.jsonl", Path("/tmp/experiments.jsonl"))
        if path.exists()
    ]
    search_credentials = load_search_credentials(repo_path, params.get("search_env"))
    search_providers = []
    if search_credentials.get("TAVILY_API_KEY"):
        search_providers.append("tavily")
    if search_credentials.get("BRAVE_SEARCH_API_KEY"):
        search_providers.append("brave")
    search_providers.append("duckduckgo_html_or_lite_fallback")
    field_db = investigations.open_field_db(repo_path)
    investigation_sources = {}
    try:
        investigation_sources = {
            "black_rot_daily_predictions": bool(
                investigations.table_columns(field_db, "black_rot_daily_predictions")
            ),
            "upper_bound_index": "potential_infection_index" in investigations.table_columns(
                field_db, "black_rot_daily_predictions"
            ),
            "peer_signals": bool(investigations.table_columns(field_db, "peer_signals")),
        }
    finally:
        if field_db is not None:
            try:
                field_db.close()
            except sqlite3.Error:
                pass
    checks = {
        "sqlite_integrity": integrity,
        "configured_fields": len(profiles),
        "farmer_notify_available": notify_script.exists(),
        "nano_experiment_journals": journals,
        "search_providers": search_providers,
        "disease_state_coverage": coverage,
        "missing_disease_states": missing,
        "stale_disease_states": stale,
        "investigation_topics": [
            investigations.TOPIC_WETNESS,
            investigations.TOPIC_PEER,
            investigations.TOPIC_CALIBRATION,
        ],
        "investigation_sources": investigation_sources,
    }
    installed = integrity == "ok" and bool(profiles) and notify_script.exists()
    operational_ready = installed and not missing and not stale
    return {
        "status": "success" if installed else "error",
        "mode": "self_test",
        "installed": installed,
        "operational_ready": operational_ready,
        "checks": checks,
        "next_action": (
            "none" if operational_ready else
            "run the deterministic three-disease cache refresh before farmer advice"
            if installed else "repair the failed installation checks"
        ),
    }


def main():
    try:
        params = read_params()
        mode = str(params.get("mode") or "tick").strip().lower().replace("-", "_")
        state_dir = params.get("state_dir") or DEFAULT_STATE_DIR
        connection = connect_db(state_dir)
        trace(state_dir, "mode_start", {"mode": mode, "field": params.get("field")})
        if mode == "init":
            result = {"status": "success", "mode": mode, "schema_version": SCHEMA_VERSION, "state_dir": state_dir}
        elif mode == "observe":
            result = mode_observe(connection, params, create=False)
        elif mode == "tick":
            result = mode_observe(connection, params, create=True)
            if as_bool(params.get("research"), False) and result.get("research_request"):
                result["research"] = mode_research(connection, params)
            if as_bool(params.get("notify"), False):
                proposal = next_proposal(connection, params.get("field"), only_unnotified=True)
                result["notification"] = notify_proposal(
                    connection, proposal, state_dir,
                    threshold=int(
                        params.get("notify_threshold")
                        or DEFAULT_NOTIFICATION_THRESHOLD
                    ),
                )
        elif mode == "investigate":
            result = mode_investigate(connection, params)
        elif mode == "investigations":
            result = {
                "status": "success", "mode": mode,
                "investigations": investigations.list_investigations(
                    connection, params.get("field"), params.get("topic"),
                    int(params.get("limit") or 20),
                ),
            }
        elif mode == "status":
            result = {"status": "success", "mode": mode, **compact_status(connection, params.get("field"))}
        elif mode == "next_proposal":
            result = {"status": "success", "mode": mode, "proposal": next_proposal(connection, params.get("field"), as_bool(params.get("include_system"), False))}
        elif mode == "next_research":
            result = {"status": "success", "mode": mode, "research_request": pending_research(connection, params.get("field"))}
        elif mode == "research":
            result = mode_research(connection, params)
        elif mode == "ingest_research":
            result = mode_ingest_research(connection, params)
        elif mode == "record_decision":
            result = mode_decision(connection, params)
        elif mode == "proposal_context":
            result = mode_proposal_context(connection, params)
        elif mode == "remember":
            result = mode_remember(connection, params)
        elif mode == "draft_operation":
            configured = field_profiles(params.get("repo_path") or DEFAULT_REPO)
            save_profiles(connection, configured)
            profile_facts(connection, configured)
            result = mode_operation(connection, params, force_draft=True)
        elif mode == "record_operation":
            configured = field_profiles(params.get("repo_path") or DEFAULT_REPO)
            save_profiles(connection, configured)
            profile_facts(connection, configured)
            result = mode_operation(connection, params, force_draft=False)
        elif mode == "self_test":
            result = mode_self_test(connection, params)
        elif mode == "notify":
            proposal = proposal_by_id(connection, int(params["proposal_id"])) if params.get("proposal_id") else next_proposal(connection, params.get("field"), only_unnotified=True)
            result = notify_proposal(
                connection,
                proposal,
                state_dir,
                int(
                    params.get("notify_threshold")
                    or DEFAULT_NOTIFICATION_THRESHOLD
                ),
            )
        else:
            result = {"status": "error", "error": f"unsupported mode: {mode}"}
        trace(state_dir, "mode_complete", {"mode": mode, "status": result.get("status")})
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") in {
            "success", "skipped", "confirmation_required", "redirect",
        } else 1
    except Exception as exc:
        try:
            trace(locals().get("state_dir", DEFAULT_STATE_DIR), "mode_error", {"error": str(exc)})
        except Exception:
            pass
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
