#!/usr/bin/env python3
"""nora research agent: bounded autonomous research over local evidence.

Domain-neutral by construction. The board raises its own questions from the
journals it writes and from the answers it gets back, tests them with bounded
analyses, and returns findings. Delivering a message to a human is a separate
concern handled by whatever adapter the deployment configures.
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

_SKILL_DIR = str(Path(__file__).resolve().parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

import analyses  # noqa: E402
import engine  # noqa: E402

DEFAULT_STATE_DIR = "/root/.picoclaw/workspace/research"
DEFAULT_JOURNAL_DIRS = ("/tmp/monitors",)
DEFAULT_EVIDENCE_JOURNAL = "/root/nano-os-agent/experiments.jsonl"

# Host defaults for a deployment that is not the board. An explicit parameter
# always wins; these only replace the board paths above when nothing was given.
# See deploy/cloud.env.example.
ENVIRONMENT_DEFAULTS = {
    "NORA_STATE_DIR": "state_dir",
    "NORA_JOURNAL_DIRS": "journal_dirs",
    "NORA_EVIDENCE_JOURNAL": "evidence_journal",
    "GOIDANICH_REPO": "repo_path",
}


def read_params():
    raw = ""
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
        except (OSError, ValueError):
            raw = ""
    params = {}
    if raw.strip():
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                params = loaded
        except ValueError:
            params = {}
    for key, value in os.environ.items():
        if key.startswith("SKILL_"):
            params.setdefault(key[6:].lower(), value)
    for argument in sys.argv[1:]:
        if argument.startswith("--") and "=" in argument:
            key, value = argument[2:].split("=", 1)
            params[key.replace("-", "_")] = value
    for variable, key in ENVIRONMENT_DEFAULTS.items():
        value = os.environ.get(variable, "").strip()
        if value:
            params.setdefault(key, value)
    return params


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_list(value, fallback):
    if value is None:
        return list(fallback)
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def pack_directories(params):
    """Where to look for domain packs.

    Defaults to the sibling skill directories, so installing a domain skill is
    all it takes to register its analyses.
    """
    explicit = params.get("pack_dirs")
    if explicit:
        return as_list(explicit, ())
    skills_root = Path(_SKILL_DIR).parent
    candidates = [str(skills_root)]
    workspace = Path("/root/.picoclaw/workspace/skills")
    if workspace.is_dir() and str(workspace) != str(skills_root):
        candidates.append(str(workspace))
    return candidates


def build_context(params, packs):
    journal_dirs = as_list(params.get("journal_dirs"), DEFAULT_JOURNAL_DIRS)
    for pack in packs:
        for directory in pack.get("journal_dirs") or []:
            if directory not in journal_dirs:
                journal_dirs.append(directory)
    context = {
        "journal_dirs": journal_dirs,
        "calibration_sources": {},
        # Series a domain considers meaningful as drivers or responses. The
        # engine pairs them to form cross-series hypotheses nobody declared.
        "series": [],
        # Schema-discovered evidence sources. A domain supplies a database or
        # journal root, while the engine infers tables, temporal axes, numeric
        # channels and repeated entity partitions from the data itself.
        "catalog_sources": [],
        "max_new_pairs": int(params.get("max_new_pairs") or 2),
        "now": engine.utcnow(),
        "limits": {"max_lines": int(params.get("max_lines") or 400)},
        "params_in": {
            key: value for key, value in params.items()
            if key in {"repo_path", "state_dir", "subject"}
        },
    }
    for pack in packs:
        declared = pack.get("series")
        if callable(declared):
            try:
                declared = declared(context)
            except Exception:
                declared = []
        context["series"].extend(declared or [])
        catalogues = pack.get("catalog_sources")
        if callable(catalogues):
            try:
                catalogues = catalogues(context)
            except Exception:
                catalogues = []
        context["catalog_sources"].extend(catalogues or [])
    # A pack may declare its calibration sources as a callable so it can resolve
    # deployment paths at run time rather than at import time.
    for pack in packs:
        declared = pack.get("calibration_sources")
        if callable(declared):
            try:
                declared = declared(context)
            except Exception:
                declared = {}
        context["calibration_sources"].update(declared or {})
    return context


def collect_scanners(packs):
    scanners = list(analyses.BUILTIN_SCANNERS)
    for pack in packs:
        scanners.extend(pack.get("scanners") or [])
    return scanners


def budget_from(params):
    budget = dict(engine.DEFAULT_BUDGET)
    for key, caster in (
        ("max_questions", int), ("max_seconds", float),
        ("max_files", int), ("max_lines", int),
        ("min_interval_seconds", float),
    ):
        if params.get(key) is not None:
            try:
                budget[key] = caster(params[key])
            except (TypeError, ValueError):
                pass
    return budget


def load_environment(params, errors):
    packs = engine.load_packs(pack_directories(params), errors)
    registry = engine.build_registry(packs, analyses.BUILTIN_ANALYSES)
    context = build_context(params, packs)
    return packs, registry, context


def builtin_questions(connection, context):
    """Questions the engine always asks about itself.

    The coverage register is the board attending to its own blind spots: which
    questions it has framed and cannot measure, and which single addition would
    unlock the most of them. Weekly, because a gap does not change hourly.
    """
    return [engine.open_question(
        connection,
        str(context.get("subject") or "board"),
        "the board has framed questions it cannot measure",
        "coverage_gaps",
        {"min_interval_seconds": 7 * 24 * 3600},
        source=engine.SOURCE_PACK,
        origin="builtin",
        priority=35,
    )]


def pack_questions(connection, packs, context):
    """Let each pack declare the questions its domain always cares about."""
    raised = []
    for pack in packs:
        declare = pack.get("questions")
        if not callable(declare):
            continue
        try:
            current_ids = set()
            for item in declare(engine.pack_context(pack, context)) or []:
                question = engine.open_question(
                    connection,
                    item["subject"], item["claim"], item["analysis"],
                    item.get("params"), source=item.get("source", engine.SOURCE_PACK),
                    origin=pack["name"], priority=int(item.get("priority", 50)),
                )
                raised.append(question)
                current_ids.add(int(question["id"]))
            # Packs describe standing model checks. When a pack stops declaring
            # one, close its open row so removed application logic cannot keep
            # asking through persisted state. Findings and decisions remain.
            stale = connection.execute(
                "SELECT id FROM questions WHERE source=? AND origin=? AND status=?",
                (engine.SOURCE_PACK, pack["name"], engine.QUESTION_OPEN),
            ).fetchall()
            for row in stale:
                if int(row["id"]) not in current_ids:
                    engine.mark_question(
                        connection, row["id"], status=engine.QUESTION_CLOSED,
                    )
        except Exception as exc:  # pack code
            raised.append({"pack": pack["name"], "error": str(exc)})
    return raised


def evidence_paths(packs, context, limits):
    """Every file a cycle would read, for the change check."""
    paths = [
        str(path) for path in
        analyses.journal_paths(context.get("journal_dirs"), int(limits.get("max_files") or 12))
    ]
    for pack in packs:
        declared = pack.get("evidence_paths")
        if callable(declared):
            try:
                declared = declared(engine.pack_context(pack, context))
            except Exception:
                declared = []
        paths.extend(str(item) for item in (declared or []))
    return paths


def mode_cycle(connection, params):
    errors = []
    packs, registry, context = load_environment(params, errors)
    limits = budget_from(params)
    # Decide whether there is anything to do before touching the database. A
    # quiet board should cost no writes at all.
    signature = engine.evidence_signature(
        evidence_paths(packs, context, limits),
        extra={
            "feedback": connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
            "packs": sorted(pack["name"] for pack in packs),
        },
    )
    # Zero is a meaningful value here ("recheck every cycle"), so it must not
    # be treated as "unset".
    raw_recheck = params.get("idle_recheck_seconds")
    try:
        idle_recheck = (
            float(raw_recheck) if raw_recheck not in (None, "")
            else float(engine.IDLE_RECHECK_SECONDS)
        )
    except (TypeError, ValueError):
        idle_recheck = float(engine.IDLE_RECHECK_SECONDS)
    needed, reason = engine.cycle_needed(connection, signature, idle_recheck, context["now"])
    if not needed:
        return {
            "status": "skipped",
            "mode": "cycle",
            "reason": reason,
            "wrote": False,
            "packs": [pack["name"] for pack in packs],
        }
    declared = builtin_questions(connection, context) + pack_questions(connection, packs, context)
    result = engine.cycle(
        connection, registry, context,
        budget=limits,
        scanners=collect_scanners(packs),
        journal_path=params.get("evidence_journal", DEFAULT_EVIDENCE_JOURNAL),
        signature=signature,
        idle_recheck_seconds=idle_recheck,
    )
    return {
        "status": "success",
        "mode": "cycle",
        "packs": [pack["name"] for pack in packs],
        "pack_errors": errors,
        "declared_questions": len(declared),
        "raised": [
            item.get("claim") or item.get("error") for item in result["raised"]
        ],
        "investigated": [
            engine.compact_finding(item) if item.get("id") else item
            for item in result["investigated"]
        ],
        "reportable": [engine.compact_finding(item) for item in result["reportable"]],
        "autonomous_follow_ups": result.get("autonomous_follow_ups") or [],
        "elapsed_seconds": result["elapsed_seconds"],
        "safety": (
            "Findings are evidence about stored data. No action was taken and no "
            "message was sent."
        ),
    }


def mode_scan(connection, params):
    errors = []
    packs, _, context = load_environment(params, errors)
    declared = builtin_questions(connection, context) + pack_questions(connection, packs, context)
    raised = []
    for scanner in collect_scanners(packs):
        try:
            raised.extend(scanner(connection, context, budget_from(params)) or [])
        except Exception as exc:
            errors.append({"scanner": getattr(scanner, "__name__", "scanner"), "error": str(exc)})
    return {
        "status": "success",
        "mode": "scan",
        "packs": [pack["name"] for pack in packs],
        "pack_errors": errors,
        "questions": [
            {
                "id": item.get("id"), "subject": item.get("subject"),
                "claim": item.get("claim"), "analysis": item.get("analysis"),
                "source": item.get("source"),
            }
            for item in raised + declared if isinstance(item, dict) and item.get("id")
        ],
    }


def mode_catalog(params):
    """Describe inferred channels without returning their measurements."""
    errors = []
    packs, _, context = load_environment(params, errors)
    limits = budget_from(params)
    catalogue = list(context.get("series") or [])
    catalogue.extend(analyses.catalog_series(context, limits))
    catalogue.extend(analyses.journal_series(context, limits))
    compact = []
    seen = set()
    for item in catalogue:
        name = str(item.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        source = item.get("source") or {}
        compact.append({
            "name": name,
            "subject": item.get("subject"),
            "label": item.get("label"),
            "source_kind": source.get("kind"),
            "table": source.get("table"),
            "key": item.get("key"),
            "time_key": item.get("time_key"),
            "entity_values": source.get("where_values") or [],
            "adaptive_clock_windows": bool(item.get("discover_time_windows")),
        })
    result_limit = max(1, min(int(params.get("limit") or 300), 1000))
    return {
        "status": "success", "mode": "catalog",
        "count": len(compact), "series": compact[:result_limit],
        "truncated": len(compact) > result_limit,
        "packs": [pack["name"] for pack in packs], "pack_errors": errors,
    }


def mode_investigate(connection, params):
    errors = []
    packs, registry, context = load_environment(params, errors)
    question_id = params.get("question_id")
    if question_id:
        row = connection.execute(
            "SELECT * FROM questions WHERE id=?", (int(question_id),)
        ).fetchone()
        questions = [engine.question_dict(row)] if row else []
    elif params.get("analysis"):
        questions = [engine.open_question(
            connection, str(params.get("subject") or "board"),
            str(params.get("claim") or params["analysis"]),
            str(params["analysis"]),
            params.get("params") if isinstance(params.get("params"), dict) else {},
            source=engine.SOURCE_OPERATOR, priority=int(params.get("priority") or 60),
        )]
    else:
        questions = engine.due_questions(
            connection, limit=int(params.get("max_questions") or 3),
        )
    if not questions:
        return {"status": "skipped", "reason": "no open question matched"}
    findings = []
    for question in questions:
        record = engine.run_question(connection, question, registry, context)
        if record.get("id"):
            engine.journal_finding(
                params.get("evidence_journal", DEFAULT_EVIDENCE_JOURNAL), record,
            )
        findings.append(record)
    return {
        "status": "success",
        "mode": "investigate",
        "pack_errors": errors,
        "findings": findings,
        "summary": [
            engine.compact_finding(item) if item.get("id") else item for item in findings
        ],
    }


def mode_decision(connection, params):
    finding_id = params.get("finding_id")
    decision = str(params.get("decision") or "").strip().lower()
    if not finding_id or decision not in {"accepted", "rejected", "deferred", "corrected"}:
        return {
            "status": "error",
            "error": "finding_id and decision (accepted|rejected|deferred|corrected) are required",
        }
    record = engine.record_decision(
        connection, int(finding_id), decision,
        option_id=params.get("option_id"), note=params.get("note"),
        source=str(params.get("source") or "human"),
        drafts_dir=params.get("task_drafts_dir"),
    )
    if not record:
        return {"status": "error", "error": "finding not found"}
    watch = None
    if decision == "accepted" and as_bool(params.get("watch"), False):
        watch = engine.arm_watch(
            connection, record["subject"], record["analysis"],
            question_id=record.get("question_id"),
            note=params.get("note"), armed_by=str(params.get("source") or "human"),
            expires_days=int(params.get("watch_days") or 180),
        )
    return {
        "status": "success",
        "mode": "record_decision",
        "finding": engine.compact_finding(record),
        "option_id": params.get("option_id"),
        "watch": watch,
        "follow_up_question": record.get("follow_up_question"),
        "drafted_task": record.get("drafted_task"),
        "executed_action": False,
        "message": (
            "Decision recorded. Nothing was executed automatically; a drafted study "
            "is written as status: template and runs only after a person promotes it."
        ),
    }


def mode_self_test(connection, params):
    errors = []
    packs, registry, context = load_environment(params, errors)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    journals = [str(path) for path in analyses.journal_paths(context["journal_dirs"], 12)]
    checks = {
        "sqlite_integrity": integrity,
        "analyses": sorted(registry),
        "packs": [{"name": pack["name"], "path": pack["path"]} for pack in packs],
        "pack_errors": errors,
        "journal_dirs": context["journal_dirs"],
        "journals_found": journals,
        "open_questions": len(engine.list_questions(connection, status=engine.QUESTION_OPEN)),
        "armed_watches": len(engine.armed_watches(connection)),
        "analysis_policy": engine.analysis_policy(connection),
    }
    installed = integrity == "ok" and bool(registry)
    return {
        "status": "success" if installed else "error",
        "mode": "self_test",
        "installed": installed,
        "operational_ready": installed and bool(journals or packs),
        "checks": checks,
        "next_action": (
            "none" if journals or packs else
            "point journal_dirs at a monitor journal or install a domain pack"
        ),
    }


def main():
    try:
        params = read_params()
        mode = str(params.get("mode") or "cycle").strip().lower().replace("-", "_")
        state_dir = params.get("state_dir") or DEFAULT_STATE_DIR
        connection = engine.connect(state_dir)
        if mode == "cycle":
            result = mode_cycle(connection, params)
        elif mode == "scan":
            result = mode_scan(connection, params)
        elif mode == "catalog":
            result = mode_catalog(params)
        elif mode == "investigate":
            result = mode_investigate(connection, params)
        elif mode == "questions":
            result = {
                "status": "success", "mode": mode,
                "questions": engine.list_questions(
                    connection, params.get("status"), params.get("subject"),
                    int(params.get("limit") or 50),
                ),
            }
        elif mode == "findings":
            result = {
                "status": "success", "mode": mode,
                "findings": engine.list_findings(
                    connection, params.get("subject"), params.get("verdict"),
                    int(params.get("limit") or 20),
                ),
            }
        elif mode == "reportable":
            result = {
                "status": "success", "mode": mode,
                "findings": [
                    engine.compact_finding(item) for item in engine.list_findings(
                        connection, params.get("subject"),
                        engine.VERDICT_MATERIAL, int(params.get("limit") or 20),
                    )
                    if (
                        item.get("status") == "open"
                        and not engine.autonomous_only_finding(item)
                    )
                ],
            }
        elif mode == "record_decision":
            result = mode_decision(connection, params)
        elif mode == "arm_watch":
            result = {
                "status": "success", "mode": mode,
                "watch": engine.arm_watch(
                    connection, str(params.get("subject") or "board"),
                    str(params.get("analysis") or ""),
                    question_id=params.get("question_id"),
                    note=params.get("note"),
                    expires_days=int(params.get("watch_days") or 180),
                ),
            }
        elif mode == "policy":
            result = {
                "status": "success", "mode": mode,
                "policy": engine.refresh_policy(connection),
                "note": (
                    "Priority adjustment per analysis, from this board's own record. "
                    "An analysis is demoted, never silenced: one that stops running "
                    "can never earn its place back."
                ),
            }
        elif mode == "watches":
            result = {
                "status": "success", "mode": mode,
                "watches": engine.armed_watches(connection, params.get("subject")),
            }
        elif mode == "self_test":
            result = mode_self_test(connection, params)
        else:
            result = {"status": "error", "error": f"unsupported mode: {mode}"}
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0 if result.get("status") in {"success", "skipped"} else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
