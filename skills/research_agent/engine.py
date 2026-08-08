#!/usr/bin/env python3
"""Autonomous research engine for nora.

A board that samples the world spends almost all of its time idle. This module
turns that idle time into research: it reads the evidence the board already
produced, raises questions from what it sees, tests them with bounded
deterministic analyses, and keeps the conclusion. A human is interrupted only
when a question stayed open *and* would change a decision, and the interruption
carries the finding, the options, and the cost of each option.

The engine is domain-neutral. It knows about questions, analyses, findings,
verdicts and watches. It knows nothing about vineyards, cameras or microphones:
those arrive as packs that register datasets and analyses.

Vocabulary is deliberately aligned with the existing nora research agenda in
`program.yaml` (claim, experiment, metric, status) so a finding can be written
into the same `experiments.jsonl` evidence journal the executor already
publishes over MCP.
"""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 1

# Verdict vocabulary. These strings are part of the contract with packs and
# with any adapter that decides whether to contact a human.
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_NOT_MATERIAL = "not_material"
VERDICT_RESOLVED = "resolved_local"
VERDICT_MATERIAL = "material_unresolved"
VERDICTS = (
    VERDICT_INSUFFICIENT, VERDICT_NOT_MATERIAL, VERDICT_RESOLVED, VERDICT_MATERIAL,
)
# Only this verdict may become a human interruption.
REPORTABLE_VERDICTS = (VERDICT_MATERIAL,)

QUESTION_OPEN = "open"
QUESTION_ANSWERED = "answered"
QUESTION_CLOSED = "closed"

SOURCE_SIGNAL = "signal"
SOURCE_FEEDBACK = "feedback"
SOURCE_PACK = "pack"
SOURCE_OPERATOR = "operator"

# One idle cycle must stay small enough that a 1 W board can run it between
# scheduled duties without ever competing with sampling.
DEFAULT_BUDGET = {
    "max_questions": 3,
    "max_seconds": 20.0,
    "max_files": 12,
    "max_lines": 400,
    # An open question is one the board could not close. Re-deriving the same
    # finding every cycle burns the idle time that made the research possible,
    # so an unresolved question is re-checked on this interval instead.
    "min_interval_seconds": 6 * 3600,
}

# When nothing has changed, a cycle still runs occasionally, because some
# conclusions depend on the clock rather than on new data: a source that
# stopped reporting looks healthier the less often you check.
IDLE_RECHECK_SECONDS = 6 * 3600

# Metrics that move with the clock alone. A finding whose only difference is one
# of these has not changed its mind, and rewriting the row would be wear
# without information.
VOLATILE_METRIC_KEYS = frozenset({"seconds_since_last_record"})


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso_now():
    return utcnow().isoformat()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_moment(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def connect(state_dir):
    path = Path(state_dir)
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path / "research.db"))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            claim TEXT NOT NULL,
            analysis TEXT NOT NULL,
            params_json TEXT NOT NULL,
            source TEXT NOT NULL,
            origin TEXT,
            priority INTEGER NOT NULL DEFAULT 50,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            last_run_at TEXT,
            runs INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_questions_status
            ON questions(status, priority DESC, last_run_at);
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            subject TEXT NOT NULL,
            analysis TEXT NOT NULL,
            claim TEXT NOT NULL,
            method TEXT NOT NULL,
            window_start TEXT,
            window_end TEXT,
            sample_size INTEGER NOT NULL DEFAULT 0,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            metrics_json TEXT NOT NULL,
            limitations_json TEXT NOT NULL,
            options_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            open_question TEXT,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_findings_subject
            ON findings(subject, analysis, updated_at DESC);
        CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            analysis TEXT NOT NULL,
            question_id INTEGER,
            trigger_verdicts TEXT NOT NULL,
            note TEXT,
            armed_by TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL,
            triggered_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id INTEGER,
            decision TEXT NOT NULL,
            option_id TEXT,
            note TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    # An adapter that delivered a finding to a person records the answer here
    # too, so feedback given over Telegram reaches the engine that raised the
    # question. Such a row has no finding of its own and carries its subject.
    existing = {row[1] for row in connection.execute("PRAGMA table_info(decisions)")}
    for column in ("subject", "analysis"):
        if column not in existing:
            connection.execute(f"ALTER TABLE decisions ADD COLUMN {column} TEXT")
    connection.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


# How far the board may reweight its own research on its own record. An
# analysis that has never paid off here loses priority; one that keeps producing
# real findings gains a little. The floor matters more than the ceiling: an
# analysis that is never run again can never redeem itself, so it is demoted,
# never silenced.
POLICY_MIN_ATTEMPTS = 6
POLICY_MAX_PENALTY = -20
POLICY_MAX_BONUS = 10


def refresh_policy(connection):
    """Reweight analyses by what they have actually produced on this board.

    Two boards do not have the same questions worth asking. A humidity ceiling
    check earns its place on a station that sits near saturation and wastes
    cycles on one that never does, and only the board's own record can tell
    which it is.
    """
    rows = connection.execute(
        """
        SELECT f.analysis AS analysis,
               COUNT(*) AS findings,
               SUM(CASE WHEN f.verdict=? THEN 1 ELSE 0 END) AS material,
               SUM(CASE WHEN d.decision IN ('rejected','corrected') THEN 1 ELSE 0 END) AS declined
        FROM findings f
        LEFT JOIN decisions d ON d.finding_id = f.id
        GROUP BY f.analysis
        """,
        (VERDICT_MATERIAL,),
    ).fetchall()
    policy = {}
    for row in rows:
        findings = int(row["findings"] or 0)
        if findings < POLICY_MIN_ATTEMPTS:
            continue
        material = int(row["material"] or 0)
        declined = int(row["declined"] or 0)
        if material == 0:
            delta = POLICY_MAX_PENALTY
        elif declined >= material:
            # It finds things, and the human keeps saying they were not worth
            # raising. That is evidence about the question, not about the human.
            delta = POLICY_MAX_PENALTY // 2
        else:
            share = material / findings
            delta = int(round(POLICY_MAX_BONUS * min(1.0, share * 2)))
        policy[row["analysis"]] = {
            "delta": max(POLICY_MAX_PENALTY, min(POLICY_MAX_BONUS, delta)),
            "findings": findings, "material": material, "declined": declined,
        }
    meta_set(connection, "analysis_policy", json_text(policy))
    return policy


def analysis_policy(connection):
    try:
        return json.loads(meta_get(connection, "analysis_policy") or "{}")
    except ValueError:
        return {}


def policy_delta(connection, analysis):
    entry = analysis_policy(connection).get(str(analysis))
    return int((entry or {}).get("delta") or 0)


def meta_get(connection, key, default=None):
    row = connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(connection, key, value):
    connection.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    connection.commit()


def evidence_signature(paths, extra=None):
    """A cheap fingerprint of everything a cycle would read.

    Stat calls only: the point is to decide whether to open the files at all.
    """
    parts = []
    for path in sorted(str(item) for item in paths or []):
        try:
            info = os.stat(path)
        except OSError:
            parts.append([path, None])
            continue
        parts.append([path, int(info.st_mtime_ns), int(info.st_size)])
    return digest({"paths": parts, "extra": extra or {}})


def cycle_needed(connection, signature, idle_recheck_seconds=IDLE_RECHECK_SECONDS,
                 now=None):
    """Decide whether this cycle has anything to do, without writing anything.

    A board with nothing new to read should cost nothing to run. Flash memory
    is the scarcest thing on it, and a conclusion restated hourly is not a
    second discovery.
    """
    moment = now or utcnow()
    stored = meta_get(connection, "evidence_signature")
    if stored != signature:
        return True, "evidence changed since the last cycle"
    last = parse_moment(meta_get(connection, "last_cycle_at"))
    if last is None:
        return True, "no previous cycle"
    if (moment - last).total_seconds() >= float(idle_recheck_seconds):
        return True, "idle recheck: some conclusions depend on elapsed time"
    return False, "no new evidence since the last cycle"


def row_dict(row, json_columns=()):
    item = dict(row)
    for column, key in json_columns:
        try:
            item[key] = json.loads(item.pop(column))
        except (KeyError, ValueError, TypeError):
            item[key] = {}
    return item


QUESTION_JSON = (("params_json", "params"),)
FINDING_JSON = (
    ("metrics_json", "metrics"),
    ("limitations_json", "limitations"),
    ("options_json", "options"),
    ("evidence_json", "evidence"),
)


def question_dict(row):
    return row_dict(row, QUESTION_JSON)


def finding_dict(row):
    return row_dict(row, FINDING_JSON)


DISPLAY_ONLY_KEYS = {"label", "description", "title"}


def normalize_params(value):
    """Strip display-only keys so cosmetic differences do not fork a question.

    The scan and an operator can describe the same source with different
    labels. If the label reached the fingerprint they would become two
    questions, and the board would answer one thing twice.
    """
    if isinstance(value, dict):
        return {
            key: normalize_params(inner)
            for key, inner in sorted(value.items())
            if key not in DISPLAY_ONLY_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_params(item) for item in value]
    return value


def open_question(connection, subject, claim, analysis, params=None, source=SOURCE_PACK,
                  origin=None, priority=50):
    """Record one question. Re-raising the same question does not duplicate it."""
    now = iso_now()
    params = params or {}
    fingerprint = digest({
        "subject": subject, "analysis": analysis,
        "params": normalize_params(params),
    })
    # What this analysis has been worth on this board, so far.
    priority = max(1, min(100, int(priority) + policy_delta(connection, analysis)))
    known = connection.execute(
        "SELECT * FROM questions WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    if known is not None and (
        known["claim"] == claim
        and known["priority"] >= int(priority)
        and known["status"] != QUESTION_CLOSED
    ):
        # Raising a question the board already holds is not news, and rewriting
        # the row to say so is pure wear.
        item = question_dict(known)
        item["created"] = False
        return item
    connection.execute(
        """
        INSERT INTO questions(
            subject, claim, analysis, params_json, source, origin, priority,
            status, fingerprint, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            claim=excluded.claim,
            priority=MAX(questions.priority, excluded.priority),
            status=CASE WHEN questions.status=? THEN ? ELSE questions.status END,
            updated_at=excluded.updated_at
        """,
        (
            subject, claim, analysis, json_text(params), source, origin,
            int(priority), QUESTION_OPEN, fingerprint, now, now,
            QUESTION_CLOSED, QUESTION_CLOSED,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM questions WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    item = question_dict(row)
    item["created"] = known is None
    return item


def list_questions(connection, status=None, subject=None, limit=50):
    clauses = []
    values = []
    if status:
        clauses.append("status=?")
        values.append(status)
    if subject:
        clauses.append("subject=?")
        values.append(subject)
    query = "SELECT * FROM questions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY priority DESC, COALESCE(last_run_at,'') ASC, id ASC LIMIT ?"
    values.append(int(limit))
    return [question_dict(row) for row in connection.execute(query, values)]


def due_questions(connection, limit=3, min_interval_seconds=0):
    """Open questions, least recently investigated first.

    A question may set its own `min_interval_seconds` when it is expensive to
    answer — one backed by a skill that reads a season of weather has no
    business running every hour.
    """
    rows = list_questions(connection, status=QUESTION_OPEN, limit=limit * 4)
    now = utcnow()
    ready = []
    for row in rows:
        interval = as_float(
            (row.get("params") or {}).get("min_interval_seconds"),
            float(min_interval_seconds or 0),
        )
        last = parse_moment(row.get("last_run_at"))
        if interval <= 0 or last is None or (now - last).total_seconds() >= interval:
            ready.append(row)
        if len(ready) >= limit:
            break
    return ready


def mark_question(connection, question_id, status=None, ran=False):
    now = iso_now()
    if ran:
        connection.execute(
            "UPDATE questions SET runs=runs+1, last_run_at=?, updated_at=? WHERE id=?",
            (now, now, int(question_id)),
        )
    if status:
        connection.execute(
            "UPDATE questions SET status=?, updated_at=? WHERE id=?",
            (status, now, int(question_id)),
        )
    connection.commit()


def stable_metrics(metrics):
    """Metrics with the clock-driven ones removed, for change detection."""
    if not isinstance(metrics, dict):
        return {}
    return {
        key: value for key, value in metrics.items()
        if key not in VOLATILE_METRIC_KEYS
    }


def finding_changed(existing, finding):
    """Has anything worth a write actually changed?"""
    try:
        stored_metrics = json.loads(existing["metrics_json"])
    except (TypeError, ValueError):
        stored_metrics = {}
    if stable_metrics(stored_metrics) != stable_metrics(finding.get("metrics") or {}):
        return True
    if (existing["window_start"], existing["window_end"]) != (
        finding.get("window_start"), finding.get("window_end")
    ):
        return True
    if int(existing["sample_size"] or 0) != int(finding.get("sample_size") or 0):
        return True
    if (existing["open_question"] or None) != (finding.get("open_question") or None):
        return True
    for column, key in (("options_json", "options"), ("limitations_json", "limitations")):
        try:
            stored = json.loads(existing[column])
        except (TypeError, ValueError):
            stored = []
        if stored != (finding.get(key) or []):
            return True
    return False


def store_finding(connection, finding):
    """Store a finding, and leave the row untouched when nothing changed."""
    now = iso_now()
    fingerprint = digest({
        "subject": finding.get("subject"),
        "analysis": finding.get("analysis"),
        # Two questions may share a subject and an analysis while asking about
        # different channels. Without the scope they would overwrite each other.
        "scope": finding.get("scope") or "",
        "verdict": finding.get("verdict"),
        "headline": finding.get("headline") or {},
    })
    payload = (
        finding.get("question_id"), finding.get("subject") or "",
        finding.get("analysis") or "", finding.get("claim") or "",
        finding.get("method") or "", finding.get("window_start"),
        finding.get("window_end"), int(finding.get("sample_size") or 0),
        finding.get("verdict"), float(finding.get("confidence") or 0.0),
        json_text(finding.get("metrics") or {}),
        json_text(finding.get("limitations") or []),
        json_text(finding.get("options") or []),
        json_text(finding.get("evidence") or []),
        finding.get("open_question"),
    )
    existing = connection.execute(
        "SELECT * FROM findings WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    if existing and not finding_changed(existing, finding):
        # Same conclusion, same evidence window, same numbers that mean
        # anything. Leave the row alone.
        record = finding_dict(existing)
        record["created"] = False
        record["changed"] = False
        return record
    if existing:
        connection.execute(
            """
            UPDATE findings SET question_id=?, subject=?, analysis=?, claim=?,
                method=?, window_start=?, window_end=?, sample_size=?, verdict=?,
                confidence=?, metrics_json=?, limitations_json=?, options_json=?,
                evidence_json=?, open_question=?, updated_at=?
            WHERE fingerprint=?
            """,
            payload + (now, fingerprint),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM findings WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        record = finding_dict(row)
        record["created"] = False
        record["changed"] = True
        return record
    connection.execute(
        """
        INSERT INTO findings(
            question_id, subject, analysis, claim, method, window_start,
            window_end, sample_size, verdict, confidence, metrics_json,
            limitations_json, options_json, evidence_json, open_question,
            status, fingerprint, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        payload + ("open", fingerprint, now, now),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM findings WHERE fingerprint=?", (fingerprint,)
    ).fetchone()
    record = finding_dict(row)
    record["created"] = True
    record["changed"] = True
    return record


def list_findings(connection, subject=None, verdict=None, limit=20):
    clauses = []
    values = []
    if subject:
        clauses.append("subject=?")
        values.append(subject)
    if verdict:
        clauses.append("verdict=?")
        values.append(verdict)
    query = "SELECT * FROM findings"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT ?"
    values.append(int(limit))
    return [finding_dict(row) for row in connection.execute(query, values)]


def finding_by_id(connection, finding_id):
    row = connection.execute(
        "SELECT * FROM findings WHERE id=?", (int(finding_id),)
    ).fetchone()
    return finding_dict(row) if row else None


def mark_finding(connection, finding_id, status):
    connection.execute(
        "UPDATE findings SET status=?, updated_at=? WHERE id=?",
        (status, iso_now(), int(finding_id)),
    )
    connection.commit()


DEEPER_ANALYSIS_OPTION = "deeper_analysis"
DEEPER_ANALYSIS_FACTOR = 4

MEASUREMENT_TASK_OPTION = "run_measurement_task"
DEFAULT_DRAFTS_DIR = "/root/.picoclaw/workspace/research/task_drafts"
MAX_TASK_ITERATIONS = 52
MIN_TASK_INTERVAL_SECONDS = 300


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(character in text for character in ":#{}[],&*?|-<>=!%@`\"'\n"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return text


def measurement_task_yaml(finding, spec):
    """A bounded task a person can read, then enable — never enabled here.

    Written as `status: template`, which the executor does not run. Promotion is
    a human act, and that is the whole point of drafting rather than starting.
    """
    identifier = re.sub(r"[^a-z0-9_]+", "_", f"study_{finding.get('analysis')}_{finding.get('id')}".lower())
    skill = str(spec.get("skill") or "research_agent")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", skill):
        raise ValueError(f"unsafe skill name: {skill}")
    interval = max(MIN_TASK_INTERVAL_SECONDS, int(spec.get("interval_sec") or 604800))
    iterations = max(1, min(MAX_TASK_ITERATIONS, int(spec.get("max_iterations") or 8)))
    journal = str(spec.get("journal_path") or f"/tmp/monitors/{identifier}.jsonl")
    parameters = dict(spec.get("params") or {})
    parameters.setdefault("skill_name", skill)
    lines = [
        f"- id: {identifier}",
        f"  name: {yaml_scalar(spec.get('name') or finding.get('claim') or identifier)}",
        "  priority: 3",
        # A draft is never runnable. A person promotes it to `pending`.
        "  status: template",
        f"  # Drafted by research-agent from finding {finding.get('id')}"
        f" ({finding.get('analysis')}), after a human agreed it was worth measuring.",
        f"  # Question: {str(finding.get('claim') or '')[:160]}",
        "  steps:",
        "    - id: measure",
        "      action: call_skill",
        "      parameters:",
    ]
    for key, value in sorted(parameters.items()):
        lines.append(f"        {key}: {yaml_scalar(value)}")
    lines.extend([
        "      expect:",
        "        status: success",
        f"      timeout: {int(spec.get('timeout') or 120)}",
        "      on_fail: continue",
        "      repeat:",
        f"        interval_sec: {interval}",
        f"        max_iterations: {iterations}",
        f"        journal_path: {journal}",
        "        continue_on_fail: true",
        "  success_criteria:",
        f"    - test -f {journal}",
        "",
    ])
    return "\n".join(lines)


def default_measurement_spec(finding, question):
    """Re-test the same question on data collected after it was asked.

    A relationship found in the record it was discovered in has not been
    confirmed; it has been described. Re-running it prospectively, weekly, is
    the cheapest honest next experiment and needs no new hardware.
    """
    if not question:
        return None
    return {
        "name": f"Prospective check: {finding.get('claim') or question.get('claim')}",
        "skill": "research_agent",
        "params": {
            "mode": "investigate",
            "question_id": int(question["id"]),
        },
        "interval_sec": 7 * 24 * 3600,
        "max_iterations": 8,
        "timeout": 120,
    }


def draft_measurement_task(connection, finding, drafts_dir=None, spec=None):
    """Write the drafted study to disk and return where it went."""
    question = None
    if finding.get("question_id"):
        row = connection.execute(
            "SELECT * FROM questions WHERE id=?", (finding["question_id"],)
        ).fetchone()
        question = question_dict(row) if row else None
    spec = spec or (question or {}).get("params", {}).get("measurement_task") \
        or default_measurement_spec(finding, question)
    if not spec:
        return {"drafted": False, "reason": "no measurement is defined for this finding"}
    directory = Path(drafts_dir or DEFAULT_DRAFTS_DIR)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        content = measurement_task_yaml(finding, spec)
        name = re.sub(r"[^a-z0-9_]+", "_", f"study_{finding.get('analysis')}_{finding.get('id')}".lower())
        path = directory / f"{name}.yaml"
        path.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as exc:
        return {"drafted": False, "reason": str(exc)}
    return {
        "drafted": True,
        "path": str(path),
        "status": "template",
        "note": "Drafted only. Promote it to status: pending to let the executor run it.",
    }


def widen_question(connection, question, factor=DEEPER_ANALYSIS_FACTOR):
    """Open the same question again over a wider window.

    This is what the board does when a person accepts its offer to look
    further: same analysis, more evidence, its own time. It is a new question
    rather than a mutation of the old one, so the narrow conclusion and the
    wide one stay separately auditable.
    """
    params = json.loads(json.dumps(question.get("params") or {}))
    source = params.get("source")
    widened = False
    for holder in [source] + [
        params.get(key) for key in ("primary", "reference", "alerts", "outcomes")
    ]:
        if not isinstance(holder, dict):
            continue
        if holder.get("kind") == "sqlite":
            holder["limit"] = int(holder.get("limit") or 2000) * factor
            widened = True
        else:
            holder["max_lines"] = int(holder.get("max_lines") or 400) * factor
            widened = True
    if not widened:
        return None
    params["depth"] = "extended"
    return open_question(
        connection,
        question["subject"],
        f"{question['claim']} (over a wider window)",
        question["analysis"],
        params,
        source=SOURCE_OPERATOR,
        origin=f"deeper_analysis:{question['id']}",
        priority=min(100, int(question.get("priority") or 50) + 10),
    )


def record_external_decision(connection, subject, analysis, decision, option_id=None,
                             note=None, source="adapter"):
    """Record an answer a person gave through an adapter, not through the engine.

    Vineyard Guard delivers findings over Telegram and stores the reply in its
    own memory. Without this echo the engine would never learn that its
    questions are being declined, and the one loop that makes it stop asking
    would be blind.
    """
    now = iso_now()
    connection.execute(
        "INSERT INTO decisions(finding_id, subject, analysis, decision, option_id,"
        " note, source, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (None, subject, analysis, decision, option_id, note, source, now),
    )
    connection.commit()
    return {
        "subject": subject, "analysis": analysis, "decision": decision,
        "option_id": option_id, "recorded_at": now,
    }


def record_decision(connection, finding_id, decision, option_id=None, note=None,
                    source="human", drafts_dir=None):
    """Store what the human decided, and honour a refusal as an answer."""
    finding = finding_by_id(connection, finding_id)
    if not finding:
        return None
    now = iso_now()
    connection.execute(
        "INSERT INTO decisions(finding_id, subject, analysis, decision, option_id,"
        " note, source, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            finding["id"], finding.get("subject"), finding.get("analysis"),
            decision, option_id, note, source, now,
        ),
    )
    status = {
        "accepted": "accepted", "rejected": "declined",
        "deferred": "deferred", "corrected": "corrected",
    }.get(decision, "answered")
    connection.execute(
        "UPDATE findings SET status=?, updated_at=? WHERE id=?",
        (status, now, finding["id"]),
    )
    follow_up = None
    drafted = None
    if decision == "accepted" and option_id == MEASUREMENT_TASK_OPTION:
        # The human agreed the hypothesis is worth measuring. That authorizes a
        # draft study, not a running one.
        drafted = draft_measurement_task(connection, finding, drafts_dir)
    if finding.get("question_id") and decision in {"accepted", "rejected"}:
        connection.execute(
            "UPDATE questions SET status=?, updated_at=? WHERE id=?",
            (QUESTION_ANSWERED if decision == "accepted" else QUESTION_CLOSED,
             now, finding["question_id"]),
        )
        if decision == "accepted" and option_id == DEEPER_ANALYSIS_OPTION:
            row = connection.execute(
                "SELECT * FROM questions WHERE id=?", (finding["question_id"],)
            ).fetchone()
            if row:
                follow_up = widen_question(connection, question_dict(row))
    connection.commit()
    record = finding_by_id(connection, finding["id"])
    if record is not None and follow_up:
        record["follow_up_question"] = {
            "id": follow_up.get("id"),
            "claim": follow_up.get("claim"),
            "analysis": follow_up.get("analysis"),
        }
    if record is not None and drafted:
        record["drafted_task"] = drafted
    return record


# ---------------------------------------------------------------------------
# Watches: a future action the human confirmed once
# ---------------------------------------------------------------------------

def arm_watch(connection, subject, analysis, trigger_verdicts=(VERDICT_MATERIAL,),
              question_id=None, note=None, armed_by="human", expires_days=180):
    now = iso_now()
    expires = (utcnow() + dt.timedelta(days=int(expires_days))).isoformat()
    connection.execute(
        """
        INSERT INTO watches(
            subject, analysis, question_id, trigger_verdicts, note, armed_by,
            expires_at, status, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            subject, analysis, question_id, json_text(list(trigger_verdicts)),
            note, armed_by, expires, "armed", now, now,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM watches ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row)


def armed_watches(connection, subject=None, analysis=None):
    clauses = ["status='armed'"]
    values = []
    if subject:
        clauses.append("subject=?")
        values.append(subject)
    if analysis:
        clauses.append("analysis=?")
        values.append(analysis)
    rows = connection.execute(
        "SELECT * FROM watches WHERE " + " AND ".join(clauses) + " ORDER BY id",
        values,
    ).fetchall()
    now = utcnow()
    live = []
    for row in rows:
        expires = parse_moment(row["expires_at"])
        if expires and expires < now:
            connection.execute(
                "UPDATE watches SET status='expired', updated_at=? WHERE id=?",
                (iso_now(), row["id"]),
            )
            continue
        live.append(dict(row))
    connection.commit()
    return live


def trigger_watches(connection, finding):
    """Return the watches this finding satisfies, and disarm them."""
    triggered = []
    for watch in armed_watches(connection, finding.get("subject"), finding.get("analysis")):
        try:
            verdicts = json.loads(watch["trigger_verdicts"])
        except (TypeError, ValueError):
            verdicts = [VERDICT_MATERIAL]
        if finding.get("verdict") not in verdicts:
            continue
        now = iso_now()
        connection.execute(
            "UPDATE watches SET status='triggered', triggered_at=?, updated_at=? WHERE id=?",
            (now, now, watch["id"]),
        )
        watch["triggered_at"] = now
        triggered.append(watch)
    connection.commit()
    return triggered


# ---------------------------------------------------------------------------
# Packs
# ---------------------------------------------------------------------------

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def discover_pack_paths(pack_dirs):
    """Find `pack.py` files: one per domain, in any configured directory."""
    paths = []
    for directory in pack_dirs:
        base = Path(directory)
        if not base.is_dir():
            continue
        candidate = base / "pack.py"
        if candidate.is_file():
            paths.append(candidate)
            continue
        for child in sorted(base.iterdir()):
            nested = child / "pack.py"
            if child.is_dir() and nested.is_file():
                paths.append(nested)
    return paths


def load_packs(pack_dirs, errors=None):
    """Import every discovered pack and return its declaration.

    A pack is a module exposing `PACK = {"name", "subjects", "analyses", ...}`.
    A pack that fails to import is reported, never fatal: one broken domain must
    not stop the board from researching the others.
    """
    packs = []
    for index, path in enumerate(discover_pack_paths(pack_dirs)):
        try:
            module = load_module(path, f"nora_research_pack_{index}_{path.parent.name}")
            declaration = dict(getattr(module, "PACK", {}) or {})
        except Exception as exc:  # a pack is third-party code
            if errors is not None:
                errors.append({"pack": str(path), "error": str(exc)})
            continue
        if not declaration.get("name"):
            continue
        declaration["module"] = module
        declaration["path"] = str(path)
        packs.append(declaration)
    return packs


def build_registry(packs, builtin_analyses=None):
    """Map analysis name -> callable, builtins first, packs may add their own."""
    registry = dict(builtin_analyses or {})
    for pack in packs:
        for name, function in (pack.get("analyses") or {}).items():
            registry[f"{pack['name']}.{name}" if "." not in name else name] = function
    return registry


def pack_context(pack, base_context):
    context = dict(base_context)
    context["pack"] = pack.get("name")
    context.update(pack.get("context") or {})
    return context


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------

def journal_finding(journal_path, finding, only_when_changed=True):
    """Append a finding to the nora evidence journal in executor format.

    A conclusion restated every hour is not a second discovery, and the journal
    lives on the same flash card as everything else, so an unchanged finding is
    not written again.
    """
    if not journal_path:
        return False
    if only_when_changed and finding.get("changed") is False:
        return False
    entry = {
        "id": f"research-{finding.get('id')}",
        "timestamp": finding.get("updated_at") or iso_now(),
        "task_id": "autonomous_research",
        "task_name": finding.get("analysis"),
        "hypothesis_ref": finding.get("claim"),
        "verdict": {
            VERDICT_MATERIAL: "open",
            VERDICT_NOT_MATERIAL: "immaterial",
            VERDICT_RESOLVED: "resolved",
            VERDICT_INSUFFICIENT: "insufficient",
        }.get(finding.get("verdict"), "unknown"),
        "summary": finding.get("method"),
        "metrics_after": finding.get("metrics") or {},
        "steps_run": 1,
        "steps_passed": 1 if finding.get("verdict") != VERDICT_INSUFFICIENT else 0,
    }
    try:
        path = Path(journal_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return False
    return True


def run_question(connection, question, registry, context):
    """Run one question's analysis and store the finding."""
    analysis = registry.get(question["analysis"])
    if not analysis:
        return {
            "question_id": question["id"],
            "error": f"unknown analysis: {question['analysis']}",
            "verdict": VERDICT_INSUFFICIENT,
        }
    ctx = dict(context)
    ctx["question"] = question
    ctx["params"] = question.get("params") or {}
    # The question's own words, so a finding is reported as the thing that was
    # asked rather than as the shape of the analysis that answered it.
    ctx["claim"] = question.get("claim")
    ctx["subject"] = question.get("subject")
    try:
        finding = analysis(ctx)
    except Exception as exc:  # analyses are pack code
        mark_question(connection, question["id"], ran=True)
        return {
            "question_id": question["id"],
            "analysis": question["analysis"],
            "error": str(exc),
            "verdict": VERDICT_INSUFFICIENT,
        }
    mark_question(connection, question["id"], ran=True)
    if not finding:
        return {
            "question_id": question["id"],
            "analysis": question["analysis"],
            "verdict": VERDICT_INSUFFICIENT,
            "skipped": True,
        }
    finding.setdefault("subject", question["subject"])
    finding.setdefault("analysis", question["analysis"])
    finding.setdefault("claim", question["claim"])
    finding.setdefault(
        "scope", digest(normalize_params(question.get("params") or {}))[:16],
    )
    finding["question_id"] = question["id"]
    record = store_finding(connection, finding)
    if record["verdict"] in {VERDICT_NOT_MATERIAL, VERDICT_RESOLVED}:
        mark_question(connection, question["id"], status=QUESTION_ANSWERED)
    record["watches"] = trigger_watches(connection, record)
    return record


def cycle(connection, registry, context, budget=None, scanners=(), journal_path=None,
          signature=None, idle_recheck_seconds=IDLE_RECHECK_SECONDS):
    """One idle research cycle: look for questions, then answer a few.

    The cycle is budgeted in questions and wall-clock seconds so that it can be
    scheduled often on a board whose real job is sampling. When the evidence has
    not changed it returns immediately, having written nothing: an hourly
    schedule on a quiet board should cost no flash at all.
    """
    limits = dict(DEFAULT_BUDGET)
    limits.update(budget or {})
    if signature is not None:
        needed, reason = cycle_needed(
            connection, signature, idle_recheck_seconds, context.get("now"),
        )
        if not needed:
            return {
                "skipped": True, "reason": reason, "raised": [], "seen": 0,
                "investigated": [], "reportable": [], "elapsed_seconds": 0.0,
                "budget": limits, "wrote": False,
            }
    started = time.monotonic()
    # Reweight before raising anything, so this cycle's new questions already
    # reflect what has been worth asking here.
    refresh_policy(connection)
    raised = []
    for scanner in scanners:
        if time.monotonic() - started > limits["max_seconds"]:
            break
        try:
            raised.extend(scanner(connection, context, limits) or [])
        except Exception as exc:
            raised.append({"scanner": getattr(scanner, "__name__", "scanner"), "error": str(exc)})
    investigated = []
    reportable = []
    ready = due_questions(
        connection, limit=int(limits["max_questions"]),
        min_interval_seconds=float(limits.get("min_interval_seconds") or 0),
    )
    for question in ready:
        if time.monotonic() - started > limits["max_seconds"]:
            break
        record = run_question(connection, question, registry, context)
        investigated.append(record)
        if record.get("verdict") in REPORTABLE_VERDICTS and record.get("id"):
            reportable.append(record)
        if record.get("id"):
            journal_finding(journal_path, record)
    if signature is not None:
        meta_set(connection, "evidence_signature", signature)
        meta_set(connection, "last_cycle_at", iso_now())
    return {
        # Only genuinely new questions are news. A scan that recognises the same
        # shape again has raised nothing.
        "raised": [
            item for item in raised
            if item.get("created") is not False or item.get("error")
        ],
        "seen": len(raised),
        "investigated": investigated,
        "reportable": reportable,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "budget": limits,
        "skipped": False,
    }


def compact_finding(record):
    return {
        "finding_id": record.get("id"),
        "subject": record.get("subject"),
        "analysis": record.get("analysis"),
        "verdict": record.get("verdict"),
        "sample_size": record.get("sample_size"),
        "confidence": record.get("confidence"),
        "open_question": record.get("open_question"),
        "options": [option.get("id") for option in (record.get("options") or [])],
        "created": record.get("created"),
    }
