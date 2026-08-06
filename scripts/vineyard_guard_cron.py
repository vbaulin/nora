#!/usr/bin/env python3
"""Deterministic Vineyard Guard cron runner for PicoClaw command jobs."""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys


REPO = "/root/.picoclaw/workspace/goidanich"
SKILLS = "/root/.picoclaw/workspace/skills"


def run_json(command, payload=None, env=None, timeout=1200, cwd=None):
    proc = subprocess.run(
        command,
        input=json.dumps(payload or {}).encode("utf-8") if payload is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, **(env or {})},
        timeout=timeout,
        cwd=cwd,
    )
    text = proc.stdout.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text) if text else {}
    except Exception:
        data = {"raw_stdout": text}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": data,
        "stderr": proc.stderr.decode("utf-8", "replace").strip(),
    }


def call_daily(params):
    return run_json(
        [os.path.join(SKILLS, "daily_vineyard_briefing", "run.py")],
        payload=params,
        timeout=1200,
    )


def configured_fields():
    config_path = os.path.join(REPO, "agent_config.yaml")
    try:
        import yaml
        config = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
        return [field.get("id") for field in config.get("fields") or [] if field.get("id")]
    except Exception:
        pass
    try:
        text = open(config_path, encoding="utf-8").read()
    except Exception:
        return []
    fields = []
    in_fields = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped == "fields:":
            in_fields = True
            continue
        if in_fields:
            match = re.match(r"-\s+id:\s*['\"]?([^'\"]+)['\"]?", stripped)
            if match:
                fields.append(match.group(1).strip())
            elif stripped and not raw.startswith(" ") and not stripped.startswith("-"):
                break
    return fields


def call_vineyard_risk(env):
    return run_json(
        [os.path.join(SKILLS, "vineyard_disease_risk", "run.sh")],
        payload={},
        env=env,
        timeout=int(env.get("SKILL_TIMEOUT", "900")),
    )


def call_black_rot(params):
    return run_json(
        [os.path.join(SKILLS, "black_rot_risk", "run.py")],
        payload=params,
        timeout=1200,
    )


def call_farmer_notify(params):
    return run_json(
        [os.path.join(SKILLS, "farmer_notify", "run.py")],
        payload=params,
        timeout=120,
    )


def call_proactive(params):
    return run_json(
        [os.path.join(SKILLS, "proactive_field_agent", "run.py")],
        payload=params,
        timeout=180,
    )


def call_research(params):
    return run_json(
        [os.path.join(SKILLS, "research_agent", "run.py")],
        payload=params,
        timeout=120,
    )


def refresh_forecast_once():
    script = os.path.join(REPO, "forecast_projection.py")
    if not os.path.exists(script):
        return {"ok": False, "returncode": 1, "stdout": {}, "stderr": "forecast_projection.py missing"}
    return run_json(
        ["python3", script, "--db", os.path.join(REPO, "goidanich.db")],
        payload=None,
        env={},
        timeout=300,
        cwd=REPO,
    )


def text_from_result(result):
    payload = result.get("stdout") or {}
    text = payload.get("send_text") or (payload.get("telegram") or {}).get("text_after_photo") or ""
    if text:
        return text.strip()
    if payload.get("status") == "skipped":
        return ""
    if not result.get("ok"):
        return "Vineyard Guard scheduled job failed. Check /tmp/picoclaw_gateway.log and dashboard state files."
    return ""


def mode_refresh(args):
    observed_end = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    forecast = refresh_forecast_once()
    if not forecast["ok"]:
        print("Vineyard Guard forecast refresh failed.")
        print(forecast.get("stderr") or json.dumps(forecast.get("stdout"), ensure_ascii=False)[:800])
        return 1
    fields = configured_fields()
    if not fields:
        print("Vineyard Guard daily cache refresh failed: no fields configured.")
        return 1
    failures = []
    refreshed = []
    for field in fields:
        for disease in ("downy_mildew", "powdery_mildew"):
            result = call_daily({
                "mode": "standard_report",
                "field": field,
                "disease": disease,
                "days": args.days,
                "end": observed_end,
                "notify": False,
                "board_only": True,
                "force_refresh": True,
                "skip_forecast": True,
                "allow_fallback_plot": True,
                "high_threshold": args.high_threshold,
                "watch_threshold": args.watch_threshold,
                "delta_threshold": args.delta_threshold,
            })
            payload = result.get("stdout") or {}
            if result["ok"] and payload.get("status") == "success":
                refreshed.append(f"{field}:{disease}")
            else:
                failures.append({
                    "field": field,
                    "disease": disease,
                    "returncode": result.get("returncode"),
                    "stderr": result.get("stderr"),
                    "stdout": payload,
                })
        result = call_black_rot({
            "mode": "report",
            "field": field,
            "days": args.days,
            "date": observed_end,
            "force_refresh": True,
            "skip_forecast": True,
        })
        payload = result.get("stdout") or {}
        if result["ok"] and payload.get("status") == "success":
            refreshed.append(f"{field}:black_rot")
        else:
            failures.append({
                "field": field,
                "disease": "black_rot",
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
                "stdout": payload,
            })
    if failures:
        print("Vineyard Guard daily cache refresh incomplete.")
        print(json.dumps({"refreshed": refreshed, "failures": failures}, ensure_ascii=False)[:4000])
        return 1
    print(f"Vineyard Guard daily cache refreshed for {len(fields)} fields and 3 diseases.")
    return 0


def black_rot_alert_payload(args):
    black = call_black_rot({"mode": "report", "days": args.days})
    if not black["ok"]:
        return {
            "ok": False,
            "error": black.get("stderr") or json.dumps(black.get("stdout"), ensure_ascii=False)[:800],
        }
    black_payload = black.get("stdout") or {}
    alert_reports = []
    alert_fields = set()
    documented_fields = set()
    for report in black_payload.get("field_reports") or []:
        latest = report.get("latest") or {}
        forecast = report.get("forecast_prediction") or {}
        inoculum_confirmed = str(
            latest.get("black_rot_inoculum_status") or "unknown"
        ).strip().lower() == "present"
        if report.get("status") == "success" and inoculum_confirmed:
            documented_fields.add(report.get("field"))
        current_event = float(latest.get("black_rot_infection_index") or 0.0) >= 85.0
        forecast_event = bool(forecast.get("first_infection_day"))
        current_wetness_watch = bool(latest.get("black_rot_wetness_uncertain_watch"))
        forecast_wetness_watch = bool(forecast.get("first_uncertain_watch_day"))
        if report.get("status") == "success" and (
            current_event or forecast_event or current_wetness_watch or forecast_wetness_watch
        ):
            alert_reports.append(report)
            alert_fields.add(report.get("field"))
    successful_reports = [
        report for report in (black_payload.get("field_reports") or [])
        if report.get("status") == "success"
    ]
    if not successful_reports:
        return {"ok": False, "error": "no successful black-rot field reports"}
    black_text = str(black_payload.get("daily_summary") or "").strip()
    if not black_text:
        source_reports = alert_reports or successful_reports
        black_text = "\n\n".join(report.get("send_text") or "" for report in source_reports).strip()
    if alert_reports:
        black_media = [
            item for item in (black_payload.get("media") or [])
            if item.get("field") in alert_fields and item.get("disease") in (None, "", "black_rot")
        ][:2]
    else:
        black_media = []
    return {
        "ok": True,
        "send_text": black_text,
        "media": black_media,
        "has_alert": bool(alert_reports),
        "alert_fields": sorted(alert_fields),
        "documented_fields": sorted(field for field in documented_fields if field),
        "include_daily_summary": bool(documented_fields or alert_reports),
        "language": black_payload.get("language") or "",
    }


def mode_black_rot(args):
    payload = black_rot_alert_payload(args)
    if not payload.get("ok"):
        print("Vineyard Guard black-rot prognosis failed.")
        print(payload.get("error") or "unknown black-rot error")
        return 1
    black_text = payload.get("send_text") or ""
    black_media = payload.get("media") or []
    black_title = next((line.strip() for line in black_text.splitlines() if line.strip()), "Black-rot prognosis")
    notification = call_farmer_notify({
        "title": black_title,
        "message": black_text,
        "caption": black_title,
        "text_after_photo": black_text if black_media else "",
        "attachments": black_media,
        "media": black_media,
        "dispatch_role": "black_rot_alert" if payload.get("has_alert") else "black_rot_daily_summary",
        "has_alert": bool(payload.get("has_alert")),
        "alert_diseases": ["black_rot"] if payload.get("has_alert") else [],
        "alert_fields": payload.get("alert_fields") or [],
        "language": payload.get("language") or "",
        "outbox_dir": args.outbox,
        "channel": "picoclaw_telegram",
    })
    if not notification["ok"]:
        print("Vineyard Guard black-rot notification packaging failed.")
        print(notification.get("stderr") or json.dumps(notification.get("stdout"), ensure_ascii=False)[:800])
        return 1
    print(black_text)
    return 0


def mode_alert(args):
    disease_payloads = []
    for disease in ("downy_mildew", "powdery_mildew"):
        result = call_daily({
            "mode": "single_disease_report",
            "disease": disease,
            "days": args.days,
            "notify": False,
            "notify_mode": "risk_only",
            "board_only": True,
            "channel": "picoclaw_telegram",
            "high_threshold": args.high_threshold,
            "watch_threshold": args.watch_threshold,
            "delta_threshold": args.delta_threshold,
            "send_low_summary": True,
            "package_notification": False,
        })
        payload = result.get("stdout") or {}
        if not result.get("ok") or payload.get("status") not in {"success", "cache_missing"}:
            print(f"Vineyard Guard {disease} alert evaluation failed.")
            print(result.get("stderr") or json.dumps(payload, ensure_ascii=False)[:800])
            return 1
        disease_payloads.append(payload)

    black = black_rot_alert_payload(args)
    if not black.get("ok"):
        print("Vineyard Guard black-rot alert evaluation failed.")
        print(black.get("error") or "unknown black-rot error")
        return 1

    message_parts = [payload.get("send_text") or "" for payload in disease_payloads]
    if black.get("include_daily_summary"):
        message_parts.append(black.get("send_text") or "")
    message = "\n\n".join(part.strip() for part in message_parts if part and part.strip())
    alert_diseases = [payload.get("disease") for payload in disease_payloads if payload.get("has_alert")]
    if black.get("has_alert"):
        alert_diseases.append("black_rot")
    alert_fields = sorted({
        field
        for payload in disease_payloads + [black]
        if payload.get("has_alert")
        for field in (payload.get("alert_fields") or [])
        if field
    })

    media = []
    seen_paths = set()
    for payload in disease_payloads + [black]:
        if not payload.get("has_alert"):
            continue
        for item in payload.get("media") or []:
            path = item.get("path") or item.get("source_path")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            media.append(item)
    media = media[:6]
    language = next(
        (payload.get("language") for payload in disease_payloads if payload.get("language")),
        black.get("language") or "",
    )
    title = {
        "ca": "🍇 Resum diari de salut de la vinya",
        "es": "🍇 Resumen diario de salud del viñedo",
    }.get(str(language).lower()[:2], "🍇 Daily vineyard health summary")
    notification = call_farmer_notify({
        "title": title,
        "message": message,
        "caption": title,
        "text_after_photo": message if media else "",
        "attachments": media,
        "media": media,
        "dispatch_role": "three_disease_daily_overview",
        "has_alert": bool(alert_diseases),
        "alert_diseases": alert_diseases,
        "alert_fields": alert_fields,
        "language": language,
        "outbox_dir": args.outbox,
        "channel": "picoclaw_telegram",
    })
    if not notification.get("ok"):
        print("Vineyard Guard three-disease notification packaging failed.")
        print(notification.get("stderr") or json.dumps(notification.get("stdout"), ensure_ascii=False)[:800])
        return 1
    print(message)
    return 0


def mode_supabase(args):
    failures = []
    for disease in ("downy_mildew", "powdery_mildew", "black_rot"):
        result = call_vineyard_risk({
            "SKILL_MODE": "supabase_sync",
            "SKILL_REPO_PATH": REPO,
            "SKILL_DISEASE": disease,
            "SKILL_TIMEOUT": "900",
        })
        if not result["ok"]:
            failures.append(f"{disease}: {result.get('stderr') or result.get('stdout')}")
    if failures:
        print("Vineyard Guard Supabase sync failed:")
        print("\n".join(failures))
        return 1
    print("Vineyard Guard Supabase sync completed for downy mildew, powdery mildew, and black rot.")
    return 0


def mode_proactive(args):
    result = call_proactive({
        "mode": "tick",
        "repo_path": REPO,
        "state_dir": "/root/.picoclaw/workspace/proactive_field",
        "notify": True,
        "notify_threshold": args.proactive_notify_threshold,
        "research": bool(args.research),
    })
    payload = result.get("stdout") or {}
    if not result.get("ok") or payload.get("status") != "success":
        print("Proactive field cycle failed.")
        print(result.get("stderr") or json.dumps(payload, ensure_ascii=False)[:1600])
        return 1
    summary = {
        "fields": payload.get("fields") or [],
        "observations": payload.get("observations") or {},
        "operations": payload.get("operations") or {},
        "created_proposals": [
            {"id": item.get("id"), "field": item.get("field_id"), "kind": item.get("kind")}
            for item in payload.get("proposals") or []
        ],
        "notification": payload.get("notification") or {},
        "research_status": (payload.get("research") or {}).get("status"),
    }
    print("Proactive field cycle completed.")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def mode_research(args):
    """One budgeted research cycle over evidence the board already holds.

    This is the idle-hours duty. It reads journals and the board's own record,
    answers what it can, and produces no message: anything a person should see
    is picked up by the next proactive cycle.
    """
    result = call_research({
        "mode": "cycle",
        "repo_path": REPO,
        "state_dir": "/root/.picoclaw/workspace/research",
        "journal_dirs": args.journal_dirs,
        "evidence_journal": "/root/nano-os-agent/experiments.jsonl",
        "max_questions": args.research_max_questions,
        "max_seconds": args.research_max_seconds,
    })
    payload = result.get("stdout") or {}
    if not result.get("ok") or payload.get("status") != "success":
        print("Research cycle failed.")
        print(result.get("stderr") or json.dumps(payload, ensure_ascii=False)[:1600])
        return 1
    summary = {
        "packs": payload.get("packs") or [],
        "raised": payload.get("raised") or [],
        "investigated": [
            {
                "subject": item.get("subject"),
                "analysis": item.get("analysis"),
                "verdict": item.get("verdict"),
            }
            for item in payload.get("investigated") or []
        ],
        "reportable": len(payload.get("reportable") or []),
        "elapsed_seconds": payload.get("elapsed_seconds"),
    }
    print("Research cycle completed.")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["supabase", "refresh", "alert", "black-rot", "proactive", "research"],
    )
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--outbox", default="/tmp/picoclaw_outbox")
    parser.add_argument("--high-threshold", type=float, default=70)
    parser.add_argument("--watch-threshold", type=float, default=50)
    parser.add_argument("--delta-threshold", type=float, default=15)
    parser.add_argument("--proactive-notify-threshold", type=int, default=70)
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--journal-dirs", default="/tmp/monitors")
    parser.add_argument("--research-max-questions", type=int, default=3)
    parser.add_argument("--research-max-seconds", type=float, default=20)
    args = parser.parse_args()
    if args.mode == "supabase":
        return mode_supabase(args)
    if args.mode == "refresh":
        return mode_refresh(args)
    if args.mode == "black-rot":
        return mode_black_rot(args)
    if args.mode == "proactive":
        return mode_proactive(args)
    if args.mode == "research":
        return mode_research(args)
    return mode_alert(args)


if __name__ == "__main__":
    sys.exit(main())
