#!/usr/bin/env python3
"""Deterministic Vineyard Guard cron runner for PicoClaw command jobs."""

import argparse
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
                "notify": False,
                "board_only": True,
                "force_refresh": True,
                "skip_forecast": True,
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
    if failures:
        print("Vineyard Guard daily cache refresh incomplete.")
        print(json.dumps({"refreshed": refreshed, "failures": failures}, ensure_ascii=False)[:4000])
        return 1
    print(f"Vineyard Guard daily cache refreshed for {len(fields)} fields and 2 diseases.")
    return 0


def mode_alert(args):
    result = call_daily({
        "mode": "both_disease_report",
        "days": args.days,
        "notify": False,
        "notify_mode": "risk_only",
        "board_only": True,
        "channel": "picoclaw_telegram",
        "high_threshold": args.high_threshold,
        "watch_threshold": args.watch_threshold,
        "delta_threshold": args.delta_threshold,
        "send_low_summary": True,
    })
    text = text_from_result(result)
    if text:
        print(text)
    elif not result["ok"]:
        print("Vineyard Guard risk alert failed.")
        print(result.get("stderr") or json.dumps(result.get("stdout"), ensure_ascii=False)[:800])
        return 1
    return 0


def mode_supabase(args):
    failures = []
    for disease in ("downy_mildew", "powdery_mildew"):
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
    print("Vineyard Guard Supabase sync completed for downy and powdery mildew.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["supabase", "refresh", "alert"])
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--high-threshold", type=float, default=70)
    parser.add_argument("--watch-threshold", type=float, default=50)
    parser.add_argument("--delta-threshold", type=float, default=15)
    args = parser.parse_args()
    if args.mode == "supabase":
        return mode_supabase(args)
    if args.mode == "refresh":
        return mode_refresh(args)
    return mode_alert(args)


if __name__ == "__main__":
    sys.exit(main())
