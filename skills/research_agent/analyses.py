#!/usr/bin/env python3
"""Domain-neutral analyses and signal scanning for the nora research engine.

Every experiment nora runs leaves the same kind of trace: a JSONL journal of
timestamped records, or a table in a local database. These analyses work on
that trace and nothing else, so they apply equally to a canopy humidity series,
a microphone event count, an NPU latency benchmark, or a soil probe.

Each analysis answers one question and returns a finding with its method,
sample, verdict, limitations and options. None of them decide anything; they
report what the data can and cannot support.
"""

import datetime as dt
import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
from pathlib import Path

import engine

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MIN_SAMPLES = 12
NEAR_CRITERION_FRACTION = 0.95
LEVEL_SHIFT_MAD_MULTIPLE = 3.0
GAP_INTERVAL_MULTIPLE = 3.0


# ---------------------------------------------------------------------------
# Reading evidence
# ---------------------------------------------------------------------------

def read_journal(path, max_lines=400, max_bytes=256 * 1024):
    """Read the tail of a JSONL journal without loading the whole file."""
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
    records = []
    for line in data.decode("utf-8", "replace").splitlines()[-int(max_lines):]:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def pluck(record, key):
    """Read a dotted key path out of a nested record."""
    current = record
    for part in str(key).split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


DEFAULT_TIME_KEYS = (
    "timestamp", "time", "observed_at", "occurred_at", "notified_at", "day", "date",
)


def record_moment(record, time_key=None):
    for key in ([time_key] if time_key else []) + list(DEFAULT_TIME_KEYS):
        if not key:
            continue
        value = pluck(record, key)
        moment = engine.parse_moment(value) if value is not None else None
        if moment:
            return moment
        if value is not None:
            day = str(value)[:10]
            try:
                return dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
    return None


def read_sqlite(path, table, columns, time_column=None, limit=2000, where=None,
                where_values=()):
    """Read selected columns from a local table, with identifier validation."""
    names = [name for name in ([time_column] if time_column else []) + list(columns) if name]
    for name in [table] + names:
        if not IDENTIFIER.match(str(name)):
            raise ValueError(f"unsafe identifier: {name}")
    if not Path(path).exists():
        return []
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        available = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not available:
            return []
        selected = [name for name in names if name in available]
        if not selected:
            return []
        query = f"SELECT {', '.join(selected)} FROM {table}"
        if where:
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*\?$", where.strip()):
                raise ValueError(f"unsafe filter: {where}")
            query += f" WHERE {where}"
        if time_column and time_column in available:
            query += f" ORDER BY {time_column}"
        query += " LIMIT ?"
        rows = connection.execute(query, list(where_values) + [int(limit)]).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


SKILL_ROOTS = (
    Path(__file__).resolve().parent.parent,
    Path("/root/.picoclaw/workspace/skills"),
    Path("/root/nano-os-agent/skills"),
)


def resolve_skill(name):
    """Find an installed skill by name. Names only: never a caller-supplied path."""
    if not IDENTIFIER.match(str(name or "").replace("-", "_")):
        raise ValueError(f"unsafe skill name: {name}")
    for root in SKILL_ROOTS:
        for candidate in (str(name), str(name).replace("-", "_")):
            runner = root / candidate / "run.sh"
            if runner.is_file():
                return runner
    return None


def run_skill(name, params=None, timeout=60):
    """Run an installed skill and return its JSON output.

    This is how research reaches work the board already knows how to do. A
    domain that has a skill for seasonal averages should not have that
    arithmetic reimplemented inside an analysis.
    """
    runner = resolve_skill(name)
    if runner is None:
        raise ValueError(f"skill not installed: {name}")
    proc = subprocess.run(
        [str(runner)],
        input=json.dumps(params or {}).encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=float(timeout), check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            f"skill {name} failed: {proc.stderr.decode('utf-8', 'replace')[:200]}"
        )
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except ValueError as exc:
        raise ValueError(f"skill {name} returned no JSON: {exc}")


def read_json_files(pattern, limit=40):
    """Every JSON document matching a glob, as one record each.

    Artifacts a skill wrote over several seasons are a baseline nobody has to
    recompute.
    """
    records = []
    for path in sorted(Path().glob(pattern) if not os.path.isabs(pattern)
                       else Path(os.sep).glob(pattern.lstrip(os.sep)))[:int(limit)]:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict):
            loaded.setdefault("artifact_path", str(path))
            records.append(loaded)
        elif isinstance(loaded, list):
            records.extend(item for item in loaded if isinstance(item, dict))
    return records


def load_records(source, limits=None):
    """Load records from a declared source.

    A source may name a JSONL journal, a local table, a glob of JSON
    artifacts, or an installed skill. It may also carry a `refresh` source that
    is run first, which is how a question keeps a skill's artifacts current
    before reading them.
    """
    limits = limits or {}
    source = source or {}
    refresh = source.get("refresh")
    if isinstance(refresh, dict):
        try:
            load_records(refresh, limits)
        except Exception:
            # A stale baseline is still a baseline; a failed refresh must not
            # take the analysis down with it.
            pass
    kind = str(source.get("kind") or "journal")
    if kind == "skill":
        payload = run_skill(
            source.get("name"), source.get("params") or {},
            timeout=source.get("timeout") or 60,
        )
        records = pluck(payload, source["records_path"]) if source.get("records_path") else payload
        if isinstance(records, dict):
            return [records]
        return [item for item in (records or []) if isinstance(item, dict)]
    if kind == "glob":
        return read_json_files(source.get("pattern") or "", int(source.get("limit") or 40))
    if kind == "journal":
        return read_journal(
            source.get("path"),
            max_lines=int(source.get("max_lines") or limits.get("max_lines") or 400),
        )
    if kind == "sqlite":
        return read_sqlite(
            source.get("path"), source.get("table"), source.get("columns") or [],
            time_column=source.get("time_column"), limit=int(source.get("limit") or 2000),
            where=source.get("where"), where_values=source.get("where_values") or (),
        )
    if kind == "inline":
        return list(source.get("records") or [])
    raise ValueError(f"unsupported source kind: {kind}")


def numeric_series(records, key, time_key=None):
    """Return [(moment_or_None, value)] for one numeric key, in record order."""
    series = []
    for record in records:
        value = engine.as_float(pluck(record, key))
        if value is None:
            continue
        series.append((record_moment(record, time_key), value))
    return series


def source_label(source):
    return str((source or {}).get("label") or (source or {}).get("path") or "source")


def window_bounds(series):
    moments = [moment for moment, _ in series if moment]
    if not moments:
        return None, None
    return min(moments).isoformat(), max(moments).isoformat()


def median(values):
    return statistics.median(values) if values else 0.0


def mad(values):
    if not values:
        return 0.0
    centre = median(values)
    return median([abs(value - centre) for value in values])


def shift_test(values):
    """Compare the two halves of a series against their own internal spread.

    The spread has to be measured *within* each half. Taking it across the whole
    series lets a real shift inflate the very threshold meant to detect it, and
    the change disappears into its own evidence.
    """
    half = len(values) // 2
    first, second = values[:half], values[half:]
    if not first or not second:
        return None
    shift = median(second) - median(first)
    spread = max(mad(first), mad(second))
    if spread > 0:
        threshold = LEVEL_SHIFT_MAD_MULTIPLE * spread
        stable = False
    else:
        # Both halves are internally constant: any real step is a shift, but
        # keep a relative floor so float noise does not become a discovery.
        scale = max(abs(median(first)), abs(median(second)), 1e-9)
        threshold = 0.05 * scale
        stable = True
    return {
        "median_before": median(first),
        "median_after": median(second),
        "shift": shift,
        "within_half_spread": spread,
        "threshold": threshold,
        "stable_halves": stable,
        "significant": abs(shift) > threshold,
    }


def wall_test(values):
    """Is the top of this series a wall, or just the top of its range?

    A clipped channel piles up at its maximum: the top bucket holds far more
    samples than the one below it. A counter that happens to reach its highest
    value now and then has no such pile, and is not a finding.
    """
    if not values:
        return None
    top, bottom = max(values), min(values)
    if top <= bottom:
        return {"varies": False, "share": 1.0, "ratio": 0.0, "is_wall": False, "top": top}
    epsilon = (top - bottom) * 1e-3
    at_top = [value for value in values if value >= top - epsilon]
    below = [value for value in values if value < top - epsilon]
    second = max(below) if below else None
    at_second = [value for value in below if value >= second - epsilon] if below else []
    share = len(at_top) / len(values)
    ratio = len(at_top) / max(1, len(at_second))
    return {
        "varies": True,
        "top": top,
        "share": share,
        "ratio": ratio,
        "samples_at_top": len(at_top),
        "samples_at_next_level": len(at_second),
        # The pile-up ratio is what separates clipping from an ordinary maximum;
        # the share and count only keep a single stray sample from qualifying.
        "is_wall": ratio >= 3.0 and share >= 0.05 and len(at_top) >= 3,
    }


def base_finding(ctx, analysis, claim, method, series_length, source, limitations,
                 window=(None, None)):
    return {
        "subject": ctx.get("subject") or (ctx.get("question") or {}).get("subject") or "board",
        "analysis": analysis,
        "claim": claim,
        "method": method,
        "sample_size": series_length,
        "window_start": window[0],
        "window_end": window[1],
        "limitations": limitations,
        "evidence": [{"source": source_label(source)}],
        "options": [],
        "metrics": {},
    }


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def threshold_materiality(ctx):
    """Does the uncertainty between a conservative and an upper-bound estimate
    ever cross a decision threshold, and was it resolved anyway?

    Many edge models carry two versions of the same quantity: what the evidence
    confirms, and what it could be if an unmeasured input were at its worst.
    The interesting question is never "are they different" but "did the
    difference ever change what someone would do".
    """
    params = ctx.get("params") or {}
    source = params.get("source") or {}
    records = load_records(source, ctx.get("limits"))
    lower_key = params.get("lower_key")
    upper_key = params.get("upper_key")
    threshold = engine.as_float(params.get("threshold"))
    if threshold is None or not lower_key or not upper_key:
        raise ValueError("threshold_materiality needs lower_key, upper_key and threshold")
    time_key = params.get("time_key")
    tolerance = int(params.get("coverage_tolerance") or 2)
    resolved_key = params.get("resolved_key")

    rows = []
    for record in records:
        lower = engine.as_float(pluck(record, lower_key))
        upper = engine.as_float(pluck(record, upper_key))
        if lower is None or upper is None:
            continue
        rows.append({
            "moment": record_moment(record, time_key),
            "lower": lower,
            "upper": upper,
            "resolved": bool(pluck(record, resolved_key)) if resolved_key else False,
        })
    series = [(row["moment"], row["lower"]) for row in rows]
    limitations = [
        "The upper bound is a worst-case construction, not a measurement.",
        "This bounds the effect of the missing input; it does not supply it.",
    ]
    finding = base_finding(
        ctx, "threshold_materiality",
        ctx.get("claim") or "the unmeasured input changes a decision",
        f"Compared {lower_key} against {upper_key} around threshold {threshold:g} "
        f"over {len(rows)} records, then checked whether each ambiguous point was "
        f"already covered by a confirmed crossing within {tolerance} steps.",
        len(rows), source, limitations, window_bounds(series),
    )
    if len(rows) < MIN_SAMPLES:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"records": len(rows), "minimum": MIN_SAMPLES},
            "headline": {"records": len(rows)},
        })
        return finding

    crossing_indexes = [
        index for index, row in enumerate(rows) if row["lower"] >= threshold
    ]
    ambiguous = [
        index for index, row in enumerate(rows)
        if row["lower"] < threshold <= row["upper"]
    ]
    covered = [
        index for index in ambiguous
        if any(abs(index - other) <= tolerance for other in crossing_indexes)
    ]
    unresolved = [index for index in ambiguous if index not in covered]
    if any(row["resolved"] for row in rows):
        unresolved = [index for index in unresolved if not rows[index]["resolved"]]
    max_upper = max((rows[index]["upper"] for index in unresolved), default=0.0)
    max_lower = max((rows[index]["lower"] for index in unresolved), default=0.0)
    finding["metrics"] = {
        "records": len(rows),
        "threshold": threshold,
        "confirmed_crossings": len(crossing_indexes),
        "ambiguous_points": len(ambiguous),
        "ambiguous_covered_by_confirmed_crossing": len(covered),
        "unresolved_points": len(unresolved),
        "unresolved_at": [
            rows[index]["moment"].date().isoformat() if rows[index]["moment"] else index
            for index in unresolved[:10]
        ],
        "max_upper_bound": round(max_upper, 2),
        "max_confirmed_on_unresolved": round(max_lower, 2),
    }
    if not ambiguous:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.8,
            "headline": {"ambiguous": 0},
        })
        return finding
    if not unresolved:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.8,
            "headline": {"ambiguous": len(ambiguous), "unresolved": 0},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL,
        "confidence": min(0.9, 0.4 + 0.1 * len(unresolved)),
        "headline": {"unresolved": len(unresolved)},
        "open_question": params.get("open_question")
        or f"whether {upper_key} reflects reality on the {len(unresolved)} unresolved points",
        "options": params.get("options") or [
            {"id": "observe_at_next_event", "cost": "none", "params": {}},
            {"id": "deeper_analysis", "cost": "none", "params": {}},
        ],
    })
    return finding


def ceiling_saturation(ctx):
    """Is a channel pinned at a bound, or never reaching a criterion it approaches?

    A sensor clipped at its range and a criterion that a site can never satisfy
    look identical in a report and mean opposite things. Both are worth knowing
    before anyone trusts a threshold built on that channel.
    """
    params = ctx.get("params") or {}
    source = params.get("source") or {}
    key = params.get("key")
    if not key:
        raise ValueError("ceiling_saturation needs a key")
    records = load_records(source, ctx.get("limits"))
    series = numeric_series(records, key, params.get("time_key"))
    values = [value for _, value in series]
    criterion = engine.as_float(params.get("criterion"))
    limitations = [
        "A channel that never reaches a criterion may reflect the site, the sensor, or the criterion.",
        "This analysis cannot distinguish a calibration fault from a real absence.",
    ]
    finding = base_finding(
        ctx, "ceiling_saturation",
        ctx.get("claim") or f"{key} never reaches its criterion",
        f"Reviewed {len(values)} values of {key}"
        + (f" against criterion {criterion:g}." if criterion is not None else " for a pinned upper bound."),
        len(values), source, limitations, window_bounds(series),
    )
    if len(values) < MIN_SAMPLES:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"samples": len(values), "minimum": MIN_SAMPLES},
            "headline": {"samples": len(values)},
        })
        return finding
    observed_max = max(values)
    if criterion is None:
        wall = wall_test(values) or {}
        finding["metrics"] = {
            "samples": len(values), "observed_max": round(observed_max, 4),
            "samples_at_top": wall.get("samples_at_top", 0),
            "samples_at_next_level": wall.get("samples_at_next_level", 0),
            "top_share": round(wall.get("share", 0.0), 3),
            "top_to_next_ratio": round(wall.get("ratio", 0.0), 2),
        }
        material = bool(wall.get("is_wall"))
        if not wall.get("varies"):
            finding["metrics"]["reason"] = (
                "the channel does not vary; this is a constant, not a range limit"
            )
        elif not material:
            finding["metrics"]["reason"] = (
                "the top value is the top of a range, not a pile-up against a limit"
            )
        finding.update({
            "verdict": engine.VERDICT_MATERIAL if material else engine.VERDICT_NOT_MATERIAL,
            "confidence": 0.6,
            "headline": {"wall": material},
            "open_question": "whether the channel is clipping at its range" if material else None,
            "options": (params.get("options") or [
                {"id": "check_source", "cost": "none", "params": {}},
                {"id": "deeper_analysis", "cost": "none", "params": {}},
            ]) if material else [],
        })
        return finding
    reached = [value for value in values if value >= criterion]
    approached = [
        value for value in values
        if criterion * NEAR_CRITERION_FRACTION <= value < criterion
    ]
    finding["metrics"] = {
        "samples": len(values),
        "criterion": criterion,
        "samples_at_or_above_criterion": len(reached),
        "samples_approaching_criterion": len(approached),
        "observed_max": round(observed_max, 4),
    }
    if reached:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.8,
            "headline": {"reached": len(reached)},
        })
        return finding
    if not approached:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
            "headline": {"reached": 0, "approached": 0},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.7,
        "headline": {"reached": 0, "approached": len(approached)},
        "open_question": params.get("open_question")
        or f"whether the {criterion:g} criterion is reachable at this site at all",
        "options": params.get("options") or [
            {"id": "compare_second_source", "cost": "none", "params": {}},
            {"id": "deeper_analysis", "cost": "none", "params": {}},
        ],
    })
    return finding


def source_disagreement(ctx):
    """Do two sources that should agree actually agree?

    Used for a second station, a neighbouring board, a redundant sensor, or a
    model against a reference. Disagreement is reported as a rate and a
    magnitude, never as a claim about which source is right.
    """
    params = ctx.get("params") or {}
    primary = params.get("primary") or {}
    reference = params.get("reference") or {}
    key = params.get("key")
    reference_key = params.get("reference_key") or key
    tolerance = engine.as_float(params.get("tolerance"), 0.0)
    primary_records = load_records(primary, ctx.get("limits"))
    reference_records = load_records(reference, ctx.get("limits"))
    time_key = params.get("time_key")

    def by_day(records, value_key):
        buckets = {}
        for record in records:
            value = engine.as_float(pluck(record, value_key))
            moment = record_moment(record, time_key)
            if value is None or not moment:
                continue
            buckets.setdefault(moment.date().isoformat(), []).append(value)
        return {day: median(values) for day, values in buckets.items()}

    left = by_day(primary_records, key)
    right = by_day(reference_records, reference_key)
    shared = sorted(set(left) & set(right))
    limitations = [
        "Agreement between two sources does not make either one correct.",
        "Only overlapping periods are compared.",
    ]
    finding = base_finding(
        ctx, "source_disagreement",
        ctx.get("claim") or "two sources disagree beyond tolerance",
        f"Compared {source_label(primary)} against {source_label(reference)} on "
        f"{len(shared)} shared periods with tolerance {tolerance:g}.",
        len(shared), primary, limitations,
        (shared[0], shared[-1]) if shared else (None, None),
    )
    if len(shared) < max(3, MIN_SAMPLES // 3):
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"shared_periods": len(shared)},
            "headline": {"shared": len(shared)},
        })
        return finding
    differences = [left[day] - right[day] for day in shared]
    exceeding = [day for day, delta in zip(shared, differences) if abs(delta) > tolerance]
    finding["metrics"] = {
        "shared_periods": len(shared),
        "tolerance": tolerance,
        "periods_beyond_tolerance": len(exceeding),
        "median_difference": round(median(differences), 4),
        "max_difference": round(max(differences, key=abs), 4),
        "first_beyond": exceeding[0] if exceeding else None,
    }
    share = len(exceeding) / len(shared)
    if share < float(params.get("disagreement_share_limit") or 0.2):
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.7,
            "headline": {"share": round(share, 2)},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.7,
        "headline": {"share": round(share, 2)},
        "open_question": params.get("open_question")
        or "which of the two sources reflects this site",
        "options": params.get("options") or [
            {"id": "observe_at_next_event", "cost": "none", "params": {}},
            {"id": "deeper_analysis", "cost": "none", "params": {}},
        ],
    })
    return finding


def outcome_calibration(ctx):
    """Do the board's own alerts match the outcomes that came back?

    This is how the agent audits itself. A run of negative outcomes is a result
    about the alerting threshold, and the correction it justifies is fewer
    interruptions, not a louder alarm.
    """
    params = ctx.get("params") or {}
    alerts = load_records(params.get("alerts") or {}, ctx.get("limits"))
    outcomes = load_records(params.get("outcomes") or {}, ctx.get("limits"))
    time_key = params.get("time_key")
    # Alerts and outcomes usually come from different tables, and therefore from
    # different timestamp columns.
    outcome_time_key = params.get("outcome_time_key") or time_key
    outcome_key = params.get("outcome_key") or "outcome"
    positive = {str(value).lower() for value in (params.get("positive_labels") or [])}
    negative = {str(value).lower() for value in (params.get("negative_labels") or [])}
    response_days = float(params.get("response_days") or 7)

    alert_moments = sorted(
        moment for moment in (record_moment(record, time_key) for record in alerts) if moment
    )
    labelled = []
    for record in outcomes:
        moment = record_moment(record, outcome_time_key)
        label = str(pluck(record, outcome_key) or "").lower()
        if not moment or not label:
            continue
        if label in positive:
            labelled.append((moment, "positive"))
        elif label in negative:
            labelled.append((moment, "negative"))
    labelled.sort()

    used = set()
    matched = {"positive": 0, "negative": 0}
    for sent in alert_moments:
        for index, (moment, label) in enumerate(labelled):
            if index in used or moment < sent:
                continue
            if (moment - sent).days > response_days:
                continue
            used.add(index)
            matched[label] += 1
            break
    answered = matched["positive"] + matched["negative"]
    limitations = [
        "An unanswered alert counts as neither a hit nor a miss.",
        "A negative outcome calibrates this subject on that date only.",
    ]
    finding = base_finding(
        ctx, "outcome_calibration",
        ctx.get("claim") or "the alerting threshold is not earning its interruptions",
        f"Matched {len(alert_moments)} alerts against confirmed outcomes recorded "
        f"within {response_days:g} days.",
        answered, params.get("alerts") or {}, limitations,
        (
            alert_moments[0].isoformat() if alert_moments else None,
            alert_moments[-1].isoformat() if alert_moments else None,
        ),
    )
    finding["metrics"] = {
        "alerts_sent": len(alert_moments),
        "alerts_answered": answered,
        "confirmed": matched["positive"],
        "negative": matched["negative"],
        "response_days": response_days,
    }
    minimum = int(params.get("min_labels") or 4)
    if answered < minimum:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "headline": {"answered": answered},
        })
        return finding
    if matched["positive"] == 0:
        finding.update({
            "verdict": engine.VERDICT_MATERIAL,
            "confidence": min(0.9, 0.5 + 0.05 * matched["negative"]),
            "headline": {"answered": answered, "confirmed": 0},
            "open_question": params.get("open_question")
            or "how many alerts this subject should produce",
            "options": params.get("options") or [
                {"id": "raise_alert_threshold", "cost": "none", "params": {}},
                {"id": "keep_alert_threshold", "cost": "none", "params": {}},
            ],
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
        "headline": {"answered": answered, "confirmed": matched["positive"]},
    })
    return finding


def data_gap(ctx):
    """Did a source stop reporting, or thin out?

    Silence is the failure mode an unattended board is least likely to notice
    and most likely to misread as a quiet field.
    """
    params = ctx.get("params") or {}
    source = params.get("source") or {}
    records = load_records(source, ctx.get("limits"))
    moments = sorted(
        moment for moment in
        (record_moment(record, params.get("time_key")) for record in records)
        if moment
    )
    limitations = [
        "A gap in the journal may be a stopped sensor, a stopped task, or a cleared file.",
    ]
    finding = base_finding(
        ctx, "data_gap", ctx.get("claim") or "a source stopped reporting",
        f"Checked {len(moments)} timestamps for interval growth and a stale tail.",
        len(moments), source, limitations,
        (moments[0].isoformat(), moments[-1].isoformat()) if moments else (None, None),
    )
    if len(moments) < 3:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"records": len(moments)},
            "headline": {"records": len(moments)},
        })
        return finding
    intervals = [
        (later - earlier).total_seconds()
        for earlier, later in zip(moments, moments[1:])
        if (later - earlier).total_seconds() > 0
    ]
    typical = median(intervals) if intervals else 0.0
    now = ctx.get("now") or engine.utcnow()
    silence = (now - moments[-1]).total_seconds()
    expected = engine.as_float(params.get("expected_interval_seconds"), typical) or typical
    finding["metrics"] = {
        "records": len(moments),
        "typical_interval_seconds": round(typical, 1),
        "expected_interval_seconds": round(expected, 1),
        "seconds_since_last_record": round(silence, 1),
        "last_record_at": moments[-1].isoformat(),
    }
    if expected <= 0 or silence <= expected * GAP_INTERVAL_MULTIPLE:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.7,
            "headline": {"stale": False},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.8,
        "headline": {"stale": True},
        "open_question": params.get("open_question")
        or "whether the source stopped, or the experiment ended",
        "options": params.get("options") or [
            {"id": "check_source", "cost": "none", "params": {}},
        ],
    })
    return finding


def level_shift(ctx):
    """Did the level of a series change, beyond its own noise?

    Robust to outliers by construction: medians and median absolute deviation,
    so one bad frame or one dropped packet does not become a discovery.
    """
    params = ctx.get("params") or {}
    source = params.get("source") or {}
    key = params.get("key")
    if not key:
        raise ValueError("level_shift needs a key")
    records = load_records(source, ctx.get("limits"))
    series = numeric_series(records, key, params.get("time_key"))
    values = [value for _, value in series]
    limitations = [
        "A level shift is a change in the record, not an explanation for it.",
        "Concurrent changes in setup, weather or firmware are not controlled here.",
    ]
    finding = base_finding(
        ctx, "level_shift", ctx.get("claim") or f"the level of {key} changed",
        f"Compared the median of the first and second half of {len(values)} values of {key} "
        f"against {LEVEL_SHIFT_MAD_MULTIPLE:g} times the within-half median absolute deviation.",
        len(values), source, limitations, window_bounds(series),
    )
    if len(values) < MIN_SAMPLES:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"samples": len(values), "minimum": MIN_SAMPLES},
            "headline": {"samples": len(values)},
        })
        return finding
    test = shift_test(values)
    finding["metrics"] = {
        "samples": len(values),
        "median_before": round(test["median_before"], 4),
        "median_after": round(test["median_after"], 4),
        "shift": round(test["shift"], 4),
        "within_half_deviation": round(test["within_half_spread"], 6),
        "shift_threshold": round(test["threshold"], 6),
        "stable_halves": test["stable_halves"],
    }
    if not test["significant"]:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
            "headline": {"shifted": False},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.7,
        "headline": {
            "shifted": True, "direction": "up" if test["shift"] > 0 else "down",
        },
        "open_question": params.get("open_question")
        or f"what changed around the middle of the {key} record",
        "options": params.get("options") or [
            {"id": "confirm_context_change", "cost": "none", "params": {}},
            {"id": "deeper_analysis", "cost": "none", "params": {}},
        ],
    })
    return finding


def haversine_km(first, second):
    try:
        lat1, lon1 = float(first[0]), float(first[1])
        lat2, lon2 = float(second[0]), float(second[1])
    except (TypeError, ValueError, IndexError):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    inner = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return round(2 * 6371.0 * math.asin(min(1.0, math.sqrt(inner))), 3)


def neighbour_reports(ctx):
    """Do nearby reporters see something this board's own indicator does not?

    Generic over networks: peer boards on a farm, stations in an air-quality
    network, machines in a fleet. A neighbour's report is evidence about the
    neighbour. It raises the prior here; it confirms nothing here. The analysis
    says so in its limitations and asks for the one cheap local check.
    """
    params = ctx.get("params") or {}
    source = params.get("events") or {}
    origin = params.get("origin")
    records = load_records(source, ctx.get("limits"))
    window_days = float(params.get("window_days") or 14)
    local_radius = float(params.get("local_radius_km") or 5.0)
    regional_radius = float(params.get("regional_radius_km") or 15.0)
    accepted = {
        str(value).lower() for value in (params.get("accepted_labels") or [])
    }
    label_key = params.get("label_key")
    metadata_key = params.get("metadata_key")
    now = ctx.get("now") or engine.utcnow()
    since = now - dt.timedelta(days=window_days)

    events = []
    for record in records:
        moment = record_moment(record, params.get("time_key"))
        if not moment or moment < since:
            continue
        if accepted and label_key:
            if str(pluck(record, label_key) or "").lower() not in accepted:
                continue
        metadata = {}
        if metadata_key:
            raw = pluck(record, metadata_key)
            if isinstance(raw, str):
                try:
                    metadata = json.loads(raw)
                except ValueError:
                    metadata = {}
            elif isinstance(raw, dict):
                metadata = raw
        latitude = pluck(record, "latitude")
        longitude = pluck(record, "longitude")
        if latitude is None and isinstance(metadata, dict):
            latitude = metadata.get("latitude")
            longitude = metadata.get("longitude")
        distance = haversine_km(origin, (latitude, longitude)) if origin else None
        if distance is None:
            distance = engine.as_float(pluck(record, "distance_km"), None)
        events.append({
            "day": moment.date().isoformat(),
            "reporter": str(
                pluck(record, params.get("reporter_key") or "peer_id")
                or (metadata.get("board_id") if isinstance(metadata, dict) else "")
                or "unknown"
            ),
            "distance_km": distance,
        })

    limitations = [
        "A neighbour's report is evidence about the neighbour, not about here; it raises the prior only.",
        "Distances come from reported coordinates and can be approximate.",
    ]
    finding = base_finding(
        ctx, "neighbour_reports",
        ctx.get("claim") or "nearby reporters see something this board does not",
        f"Compared {len(events)} located reports from the last {window_days:g} days "
        f"against the local indicator, using a {local_radius:g} km local radius.",
        len(events), source, limitations,
        (
            (min(item["day"] for item in events), max(item["day"] for item in events))
            if events else (None, None)
        ),
    )
    if not events:
        return None
    located = [item for item in events if item["distance_km"] is not None]
    if not located:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {"reports": len(events), "reason": "no report carried a location"},
            "headline": {"reason": "unlocated"},
        })
        return finding
    nearest = min(item["distance_km"] for item in located)
    near = [item for item in located if item["distance_km"] <= local_radius]
    regional = [item for item in located if item["distance_km"] <= regional_radius]
    local_value = engine.as_float(params.get("local_value"))
    if local_value is None and params.get("local_source"):
        series = numeric_series(
            load_records(params["local_source"], ctx.get("limits")),
            params.get("local_key"), params.get("time_key"),
        )
        local_value = series[-1][1] if series else None
    threshold = engine.as_float(params.get("alert_threshold"))
    in_alert = (
        local_value is not None and threshold is not None and local_value >= threshold
    )
    finding["metrics"] = {
        "reports_in_window": len(events),
        "reports_located": len(located),
        "reports_within_local_radius": len(near),
        "reports_within_regional_radius": len(regional),
        "nearest_km": round(nearest, 1),
        "reporters": sorted({item["reporter"] for item in near}) or
                     sorted({item["reporter"] for item in located}),
        "first_day": min(item["day"] for item in located),
        "last_day": max(item["day"] for item in located),
        "local_value": local_value,
        "alert_threshold": threshold,
        "local_in_alert": in_alert,
        "local_radius_km": local_radius,
    }
    if not regional:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
            "headline": {"reason": "outside_regional_radius"},
        })
        return finding
    if not near or in_alert:
        # Either nothing is close, or the local indicator already agrees. Both
        # are answers, and neither is worth an interruption.
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
            "headline": {"near": len(near), "agrees": in_alert},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.6,
        "headline": {"near": len(near), "nearest": round(nearest, 1)},
        "open_question": params.get("open_question")
        or "whether what the neighbours confirmed is already present here",
        "options": params.get("options") or [
            {"id": "targeted_inspection", "cost": "none", "params": {}},
            {"id": "share_peer_context", "cost": "none", "params": {}},
        ],
    })
    return finding


# ---------------------------------------------------------------------------
# Cross-series association
#
# The step from "run the registered analyses" to "form a hypothesis" is where
# an autonomous researcher starts inventing relationships nobody declared. That
# is exactly where one starts finding patterns in noise, so every guard here
# exists to make a negative result the easy outcome: detrending, a persistence
# requirement across halves, correction for the number of lags tried, a floor
# on sample size, and a memory of pairs already refuted.
# ---------------------------------------------------------------------------

MIN_ASSOCIATION_PAIRS = 30
DEFAULT_LAGS = (0, 1, 2, 3, 5, 7)
ASSOCIATION_ALPHA = 0.01
MIN_ABS_RHO = 0.35


def rank(values):
    """Fractional ranks, ties averaged."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        stop = position
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[position]]:
            stop += 1
        shared = (position + stop) / 2.0 + 1.0
        for index in range(position, stop + 1):
            ranks[order[index]] = shared
        position = stop + 1
    return ranks


def spearman(left, right):
    """Rank correlation: no distributional assumption, robust to outliers."""
    if len(left) != len(right) or len(left) < 3:
        return None
    left_ranks, right_ranks = rank(left), rank(right)
    mean_left = sum(left_ranks) / len(left_ranks)
    mean_right = sum(right_ranks) / len(right_ranks)
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left_ranks, right_ranks)
    )
    spread_left = math.sqrt(sum((a - mean_left) ** 2 for a in left_ranks))
    spread_right = math.sqrt(sum((b - mean_right) ** 2 for b in right_ranks))
    if spread_left <= 0 or spread_right <= 0:
        return None
    return covariance / (spread_left * spread_right)


def correlation_p_value(rho, count):
    """Two-sided p-value via Fisher's z. Adequate for the sample floor used here."""
    if rho is None or count < 6:
        return 1.0
    bounded = max(-0.999999, min(0.999999, rho))
    z = math.atanh(bounded) * math.sqrt(count - 3)
    return math.erfc(abs(z) / math.sqrt(2.0))


def difference(series):
    """First differences remove a shared trend or slow seasonal drift.

    Two series that both rise through a season correlate beautifully and mean
    nothing. Testing the day-to-day changes asks the sharper question: when the
    driver moves, does the response move afterwards?
    """
    return [later - earlier for earlier, later in zip(series, series[1:])]


def daily_window_series(records, key, time_key=None, hours=None, statistic="mean"):
    """Collapse an hourly series into one value per day for a window of hours.

    A window that wraps midnight belongs to the day it ends on, which is what
    "last night" means to the person reading the result.
    """
    buckets = {}
    start_hour, end_hour = (hours or (0, 23))
    wraps = start_hour > end_hour
    for record in records:
        moment = record_moment(record, time_key)
        value = engine.as_float(pluck(record, key))
        if moment is None or value is None:
            continue
        hour = moment.hour
        inside = (hour >= start_hour or hour <= end_hour) if wraps else (
            start_hour <= hour <= end_hour
        )
        if not inside:
            continue
        day = moment.date()
        if wraps and hour >= start_hour:
            day = day + dt.timedelta(days=1)
        buckets.setdefault(day.isoformat(), []).append(value)
    reducer = {
        "mean": lambda values: sum(values) / len(values),
        "max": max,
        "min": min,
        "sum": sum,
        "median": median,
    }.get(statistic, lambda values: sum(values) / len(values))
    return {day: reducer(values) for day, values in buckets.items() if values}


def daily_series(records, key, time_key=None, statistic="mean"):
    """One value per day from records that may be hourly or already daily."""
    return daily_window_series(records, key, time_key, (0, 23), statistic)


def load_daily(ctx, spec):
    """Build a day -> value map from a declared series specification."""
    records = load_records(spec.get("source") or {}, ctx.get("limits"))
    hours = spec.get("hours")
    statistic = spec.get("statistic") or "mean"
    if hours:
        return daily_window_series(
            records, spec.get("key"), spec.get("time_key"), tuple(hours), statistic,
        )
    return daily_series(records, spec.get("key"), spec.get("time_key"), statistic)


def series_label(spec):
    base = spec.get("label") or spec.get("key") or "series"
    window = spec.get("window_label")
    if window and window.lower() not in base.lower():
        return f"{window} {base}"
    return base


def lagged_association(ctx):
    """Does one series move before another, by a fixed number of days?

    This is the engine's hypothesis test rather than another fixed rule: any
    two daily series can be paired, and the honest answer is usually no.

    It reports precedence, never causation. A driver that leads a response by
    three days may share a cause with it, may be a proxy for it, or may be a
    coincidence that survived the guards.
    """
    params = ctx.get("params") or {}
    driver_spec = params.get("driver") or {}
    response_spec = params.get("response") or {}
    lags = [int(value) for value in (params.get("lags") or DEFAULT_LAGS)]
    minimum = int(params.get("min_pairs") or MIN_ASSOCIATION_PAIRS)
    alpha = float(params.get("alpha") or ASSOCIATION_ALPHA)
    min_rho = float(params.get("min_abs_rho") or MIN_ABS_RHO)

    limitations = [
        "Precedence is not causation: a leading series may share a cause with the response, or proxy for it.",
        "Only days present in both series are compared; gaps reduce the sample rather than the conclusion.",
        "Day-to-day changes are tested, so a shared seasonal trend cannot create the result.",
        f"{len(lags)} lags were tried and the significance level was corrected for that.",
    ]
    driver_daily = load_daily(ctx, driver_spec)
    response_daily = load_daily(ctx, response_spec)
    finding = base_finding(
        ctx, "lagged_association",
        ctx.get("claim") or "one series precedes another",
        f"Tested whether {series_label(driver_spec)} precedes {series_label(response_spec)} "
        f"at lags {lags} days, on first differences, requiring the same direction in both "
        f"halves of the record.",
        0, driver_spec.get("source") or {}, limitations,
    )

    missing = [
        series_label(spec) for spec, daily in
        ((driver_spec, driver_daily), (response_spec, response_daily))
        if len(daily) < minimum
    ]
    if missing:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT,
            "confidence": 0.2,
            "sample_size": min(len(driver_daily), len(response_daily)),
            "metrics": {
                "driver_days": len(driver_daily),
                "response_days": len(response_daily),
                "minimum_days": minimum,
                "missing_measurement": missing,
            },
            "headline": {"missing": missing},
            "options": params.get("missing_options") or [],
            "open_question": params.get("missing_question"),
        })
        return finding

    results = []
    for lag in lags:
        days = sorted(set(response_daily) & {
            (dt.date.fromisoformat(day) + dt.timedelta(days=lag)).isoformat()
            for day in driver_daily
        })
        pairs = []
        for day in days:
            driver_day = (dt.date.fromisoformat(day) - dt.timedelta(days=lag)).isoformat()
            if driver_day in driver_daily:
                pairs.append((driver_daily[driver_day], response_daily[day]))
        if len(pairs) < minimum:
            continue
        driver_values = difference([pair[0] for pair in pairs])
        response_values = difference([pair[1] for pair in pairs])
        rho = spearman(driver_values, response_values)
        if rho is None:
            continue
        half = len(driver_values) // 2
        first = spearman(driver_values[:half], response_values[:half])
        second = spearman(driver_values[half:], response_values[half:])
        persistent = (
            first is not None and second is not None
            and (first > 0) == (second > 0) == (rho > 0)
        )
        results.append({
            "lag_days": lag,
            "pairs": len(driver_values),
            "rho": round(rho, 3),
            "p_value": round(correlation_p_value(rho, len(driver_values)), 5),
            "first_half_rho": round(first, 3) if first is not None else None,
            "second_half_rho": round(second, 3) if second is not None else None,
            "persistent": persistent,
        })

    if not results:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "sample_size": 0,
            "metrics": {"reason": "no lag had enough overlapping days", "minimum_days": minimum},
            "headline": {"reason": "no_overlap"},
        })
        return finding

    corrected = alpha / max(1, len(results))
    surviving = [
        item for item in results
        if item["p_value"] <= corrected
        and abs(item["rho"]) >= min_rho
        and item["persistent"]
    ]
    best = max(results, key=lambda item: abs(item["rho"]))
    finding["sample_size"] = best["pairs"]
    finding["metrics"] = {
        "driver": series_label(driver_spec),
        "response": series_label(response_spec),
        "lags_tested": lags,
        "corrected_alpha": round(corrected, 5),
        "minimum_abs_rho": min_rho,
        "by_lag": results,
        "strongest_lag_days": best["lag_days"],
        "strongest_rho": best["rho"],
        "surviving_lags": [item["lag_days"] for item in surviving],
    }
    if not surviving:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.7,
            "headline": {"surviving": 0},
        })
        return finding
    leading = max(surviving, key=lambda item: abs(item["rho"]))
    finding.update({
        "verdict": engine.VERDICT_MATERIAL,
        "confidence": min(0.8, 0.4 + 0.1 * len(surviving)),
        "headline": {
            "lag": leading["lag_days"],
            "direction": "up" if leading["rho"] > 0 else "down",
        },
        "open_question": params.get("open_question") or (
            f"whether {series_label(driver_spec)} is acting on "
            f"{series_label(response_spec)} {leading['lag_days']} days later, or both "
            "follow something else"
        ),
        "options": params.get("options") or [
            {"id": "deeper_analysis", "cost": "none", "params": {}},
            {"id": "confirm_context_change", "cost": "none", "params": {}},
        ],
    })
    return finding


def baseline_deviation(ctx):
    """Is the current period unusual against the periods that came before it?

    The comparison a person actually makes about weather: not "is it warm" but
    "is this season unlike the last several". Robust by construction — median
    and median absolute deviation — because a handful of seasons is a small
    sample and one extreme year must not set the expectation for the rest.
    """
    params = ctx.get("params") or {}
    source = params.get("source") or {}
    key = params.get("key")
    period_key = params.get("period_key")
    if not key or not period_key:
        raise ValueError("baseline_deviation needs key and period_key")
    records = load_records(source, ctx.get("limits"))
    # A record often dates its period rather than naming it: period_slice takes
    # the leading characters, so an ISO end date becomes its year.
    period_slice = params.get("period_slice")
    observations = {}
    for record in records:
        period = pluck(record, period_key)
        value = engine.as_float(pluck(record, key))
        if period is None or value is None:
            continue
        label = str(period)[:int(period_slice)] if period_slice else str(period)
        observations[label] = value
    periods = sorted(observations)
    minimum = int(params.get("min_baseline") or 3)
    limitations = [
        "A period unlike its predecessors is a description, not a cause.",
        "Comparability depends on the periods covering the same part of the season.",
    ]
    finding = base_finding(
        ctx, "baseline_deviation",
        ctx.get("claim") or f"the current {period_key} is unlike the ones before it",
        f"Compared {key} for the most recent {period_key} against the median and "
        f"median absolute deviation of the {max(0, len(periods) - 1)} earlier ones.",
        len(periods), source, limitations,
        (periods[0], periods[-1]) if periods else (None, None),
    )
    current_period = str(params.get("current_period") or (periods[-1] if periods else ""))
    baseline = [observations[period] for period in periods if period != current_period]
    if current_period not in observations or len(baseline) < minimum:
        finding.update({
            "verdict": engine.VERDICT_INSUFFICIENT, "confidence": 0.2,
            "metrics": {
                "periods": len(periods), "baseline_periods": len(baseline),
                "minimum_baseline": minimum, "metric": key,
            },
            "headline": {"baseline": len(baseline)},
        })
        return finding
    current = observations[current_period]
    centre = median(baseline)
    spread = mad(baseline)
    if spread > 0:
        deviations = abs(current - centre) / spread
        threshold = float(params.get("deviation_threshold") or 3.0)
        unusual = deviations > threshold
    else:
        scale = max(abs(centre), 1e-9)
        deviations = abs(current - centre) / scale
        threshold = float(params.get("relative_threshold") or 0.25)
        unusual = deviations > threshold
    finding["metrics"] = {
        "metric": key,
        "current_period": current_period,
        "current_value": round(current, 4),
        "baseline_periods": len(baseline),
        "baseline_median": round(centre, 4),
        "baseline_deviation": round(spread, 4),
        "distance_from_baseline": round(deviations, 2),
        "threshold": threshold,
        "direction": "above" if current > centre else "below",
        "period_values": {period: round(observations[period], 4) for period in periods},
    }
    if not unusual:
        finding.update({
            "verdict": engine.VERDICT_NOT_MATERIAL, "confidence": 0.6,
            "headline": {"unusual": False},
        })
        return finding
    finding.update({
        "verdict": engine.VERDICT_MATERIAL, "confidence": 0.7,
        "headline": {"unusual": True, "direction": finding["metrics"]["direction"]},
        "open_question": params.get("open_question")
        or f"what an unusual {key} means for what you should do differently",
        "options": params.get("options") or [
            {"id": "confirm_context_change", "cost": "none", "params": {}},
            {"id": "deeper_analysis", "cost": "none", "params": {}},
        ],
    })
    return finding


BUILTIN_ANALYSES = {
    "threshold_materiality": threshold_materiality,
    "neighbour_reports": neighbour_reports,
    "baseline_deviation": baseline_deviation,
    "lagged_association": lagged_association,
    "ceiling_saturation": ceiling_saturation,
    "source_disagreement": source_disagreement,
    "outcome_calibration": outcome_calibration,
    "data_gap": data_gap,
    "level_shift": level_shift,
}


# ---------------------------------------------------------------------------
# Scanning: turning signals and feedback into questions
# ---------------------------------------------------------------------------

def numeric_keys(records, limit=8):
    """Numeric leaf keys that appear in most records, cheapest first."""
    counts = {}
    for record in records:
        for key, value in record.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            counts[key] = counts.get(key, 0) + 1
        for key, value in record.items():
            if not isinstance(value, dict):
                continue
            for nested, inner in value.items():
                if isinstance(inner, bool) or not isinstance(inner, (int, float)):
                    continue
                counts[f"{key}.{nested}"] = counts.get(f"{key}.{nested}", 0) + 1
    threshold = max(2, len(records) // 2)
    ranked = sorted(
        (key for key, count in counts.items() if count >= threshold),
        key=lambda key: (-counts[key], key),
    )
    return ranked[:limit]


def journal_paths(directories, limit=12):
    paths = []
    for directory in directories or []:
        base = Path(directory)
        if base.is_file():
            paths.append(base)
            continue
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.jsonl")):
            paths.append(path)
            if len(paths) >= limit:
                return paths
    return paths[:limit]


def scan_journals(connection, context, limits=None):
    """Raise questions from monitor journals the board already writes.

    The scan is deliberately shallow: it looks for the shapes worth a closer
    look and hands them to an analysis. It never concludes anything itself.
    """
    limits = dict(engine.DEFAULT_BUDGET, **(limits or {}))
    raised = []
    for path in journal_paths(context.get("journal_dirs"), int(limits["max_files"])):
        records = read_journal(path, max_lines=int(limits["max_lines"]))
        if len(records) < 3:
            continue
        subject = path.stem
        source = {"kind": "journal", "path": str(path), "label": path.name}
        moments = sorted(
            moment for moment in (record_moment(record) for record in records) if moment
        )
        if len(moments) >= 3:
            intervals = [
                (later - earlier).total_seconds()
                for earlier, later in zip(moments, moments[1:])
                if (later - earlier).total_seconds() > 0
            ]
            typical = median(intervals) if intervals else 0.0
            now = context.get("now") or engine.utcnow()
            if typical > 0 and (now - moments[-1]).total_seconds() > typical * GAP_INTERVAL_MULTIPLE:
                raised.append(engine.open_question(
                    connection, subject,
                    f"{path.name} stopped reporting at its usual interval",
                    "data_gap", {"source": source}, source=engine.SOURCE_SIGNAL,
                    origin=str(path), priority=70,
                ))
        for key in numeric_keys(records):
            values = [value for _, value in numeric_series(records, key)]
            if len(values) < MIN_SAMPLES or mad(values) <= 0:
                # A channel that never moves carries no question worth an analysis.
                continue
            test = shift_test(values)
            if test and test["significant"]:
                raised.append(engine.open_question(
                    connection, subject,
                    f"the level of {key} changed during the recorded window",
                    "level_shift", {"source": source, "key": key},
                    source=engine.SOURCE_SIGNAL, origin=str(path), priority=60,
                ))
                continue
            wall = wall_test(values)
            if wall and wall["is_wall"]:
                raised.append(engine.open_question(
                    connection, subject,
                    f"{key} piles up against {wall['top']:g} instead of passing it",
                    "ceiling_saturation", {"source": source, "key": key},
                    source=engine.SOURCE_SIGNAL, origin=str(path), priority=55,
                ))
    return raised


def scan_feedback(connection, context, limits=None):
    """Raise questions from what the human said about earlier findings.

    Two refusals on the same subject are not stubbornness; they are evidence
    that the board is asking the wrong question or asking it too often.
    """
    # Decisions come from two places: findings this engine delivered, and
    # answers an adapter collected elsewhere and echoed back with a subject.
    rows = connection.execute(
        """
        SELECT COALESCE(f.subject, d.subject) AS subject,
               COALESCE(f.analysis, d.analysis) AS analysis,
               COUNT(*) AS declines
        FROM decisions d LEFT JOIN findings f ON f.id = d.finding_id
        WHERE d.decision IN ('rejected','corrected')
          AND COALESCE(f.subject, d.subject) IS NOT NULL
        GROUP BY 1, 2
        HAVING COUNT(*) >= 2
        """
    ).fetchall()
    raised = []
    for row in rows:
        calibration = (context.get("calibration_sources") or {}).get(row["subject"])
        if not calibration:
            continue
        raised.append(engine.open_question(
            connection, row["subject"],
            f"my {row['analysis']} reports are being declined; the reporting threshold may be wrong",
            "outcome_calibration", calibration,
            source=engine.SOURCE_FEEDBACK,
            origin=f"declines:{row['declines']}", priority=65,
        ))
    return raised


def journal_series(context, limits):
    """Numeric channels in monitor journals, usable as drivers or responses."""
    series = []
    for path in journal_paths(context.get("journal_dirs"), int(limits.get("max_files") or 12)):
        records = read_journal(path, max_lines=int(limits.get("max_lines") or 400))
        if len(records) < MIN_ASSOCIATION_PAIRS:
            continue
        for key in numeric_keys(records, limit=4):
            values = [value for _, value in numeric_series(records, key)]
            if len(values) < MIN_ASSOCIATION_PAIRS or mad(values) <= 0:
                continue
            series.append({
                "name": f"{path.stem}.{key}",
                "role": "both",
                "subject": path.stem,
                "source": {"kind": "journal", "path": str(path), "label": path.name},
                "key": key,
                "label": f"{key} in {path.stem}",
            })
    return series


def scan_series_pairs(connection, context, limits=None):
    """Propose cross-series hypotheses nobody wrote down in advance.

    This is where the board starts inventing relationships, so it is bounded on
    purpose: only pairs of distinct series, only a couple of new questions per
    cycle, and never a pair that has already been asked and refuted — a
    question answered `not_material` stays answered, which is how a negative
    result is remembered.
    """
    limits = dict(engine.DEFAULT_BUDGET, **(limits or {}))
    catalogue = list(context.get("series") or [])
    catalogue.extend(journal_series(context, limits))
    drivers = [item for item in catalogue if item.get("role") in {"driver", "both"}]
    responses = [item for item in catalogue if item.get("role") in {"response", "both"}]
    budget = int(context.get("max_new_pairs") or 2)
    raised = []
    for response in responses:
        for driver in drivers:
            if len(raised) >= budget:
                return raised
            if driver["name"] == response["name"]:
                continue
            if driver.get("subject") and driver.get("subject") == response.get("subject") \
                    and driver.get("key") == response.get("key"):
                continue
            params = {
                "driver": {key: driver[key] for key in
                           ("source", "key", "time_key", "hours", "statistic", "label",
                            "window_label") if key in driver},
                "response": {key: response[key] for key in
                             ("source", "key", "time_key", "hours", "statistic", "label",
                              "window_label") if key in response},
                "lags": list(driver.get("lags") or response.get("lags") or DEFAULT_LAGS),
            }
            question = engine.open_question(
                connection,
                response.get("subject") or context.get("subject") or "board",
                f"{driver.get('label') or driver['name']} precedes "
                f"{response.get('label') or response['name']}",
                "lagged_association", params,
                source=engine.SOURCE_SIGNAL,
                origin=f"pair:{driver['name']}->{response['name']}",
                priority=40,
            )
            if question.get("created"):
                raised.append(question)
    return raised


BUILTIN_SCANNERS = (scan_journals, scan_feedback, scan_series_pairs)
