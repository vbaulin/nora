#!/usr/bin/env python3
import datetime as dt
import json
import sys


def main():
    params = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    field = params.get("field") or None
    hour = int(params.get("hour", 8))
    minute = int(params.get("minute", 0))
    timezone = params.get("timezone") or "Europe/Madrid"
    high_threshold = float(params.get("high_threshold", 70))
    watch_threshold = float(params.get("watch_threshold", 50))
    delta_threshold = float(params.get("delta_threshold", 15))
    cron_expr = f"{minute} {hour} * * *"
    common_params = {
        "mode": "both_disease_report",
        "days": 31,
        "notify": False,
        "board_only": True,
        "high_threshold": high_threshold,
        "watch_threshold": watch_threshold,
        "delta_threshold": delta_threshold,
    }
    if field:
        common_params["field"] = field
    refresh_payload = {"skill_name": "daily-vineyard-briefing", "parameters": dict(common_params)}
    sync_payloads = [
        {
            "skill_name": "vineyard-disease-risk",
            "parameters": {
                "mode": "supabase_sync",
                "repo_path": "/root/.picoclaw/workspace/goidanich",
                "disease": disease,
                "timeout": 600,
            },
        }
        for disease in ("downy_mildew", "powdery_mildew")
    ]
    alert_params = {
        **common_params,
        "notify": False,
        "notify_mode": "risk_only",
        "channel": "picoclaw_telegram",
    }
    alert_payload = {"skill_name": "daily-vineyard-briefing", "parameters": alert_params}
    message = (
        "Call skill daily-vineyard-briefing with "
        + json.dumps(alert_payload["parameters"], separators=(",", ":"))
        + ". Preserve attachments/media. Do not summarize."
    )
    refresh_message = (
        "Call skill daily-vineyard-briefing with "
        + json.dumps(refresh_payload["parameters"], separators=(",", ":"))
        + ". Refresh all configured YAML fields if field is omitted. Preserve structured result."
    )
    sync_messages = [
        (
            "Call skill vineyard-disease-risk with "
            + json.dumps(payload["parameters"], separators=(",", ":"))
            + ". Pull neighbours/network/risk signals and push pending farmer feedback/events. Preserve structured result."
        )
        for payload in sync_payloads
    ]
    print(json.dumps({
        "status": "success",
        "scheduler": "picoclaw_gateway_cronservice",
        "do_not_use": ["busybox_crontab", "while_true_loop", "rc.local_watchdog", "vague_agent_turn"],
        "timezone": timezone,
        "cron_expr": cron_expr,
        "field_scope": field or "all fields from agent_config.yaml",
        "thresholds": {
            "high_threshold": high_threshold,
            "watch_threshold": watch_threshold,
            "delta_threshold": delta_threshold,
        },
        "daily_refresh_skill_call": refresh_payload,
        "supabase_sync_skill_calls": sync_payloads,
        "risk_only_alert_skill_call": alert_payload,
        "agent_turn_messages_if_command_jobs_are_unavailable": {
            "supabase_sync": sync_messages,
            "refresh": refresh_message,
            "risk_only_alert": message,
        },
        "jobs": [
            {
                "name": "Vineyard Guard Supabase sync downy mildew",
                "schedule": {"kind": "cron", "expr": f"{(minute - 5) % 60} {hour - 1 if minute < 5 else hour} * * *", "timezone": timezone},
                "payload": {
                    "kind": "skill_call",
                    **sync_payloads[0],
                },
                "sync": "supabase",
            },
            {
                "name": "Vineyard Guard Supabase sync powdery mildew",
                "schedule": {"kind": "cron", "expr": f"{(minute - 4) % 60} {hour - 1 if minute < 4 else hour} * * *", "timezone": timezone},
                "payload": {
                    "kind": "skill_call",
                    **sync_payloads[1],
                },
                "sync": "supabase",
            },
            {
                "name": "Vineyard Guard daily cache refresh",
                "schedule": {"kind": "cron", "expr": cron_expr, "timezone": timezone},
                "payload": {
                    "kind": "skill_call",
                    **refresh_payload,
                },
                "notify": False,
            },
            {
                "name": "Vineyard Guard risk-only Telegram alert",
                "schedule": {"kind": "cron", "expr": f"{(minute + 5) % 60} {hour + ((minute + 5) // 60)} * * *", "timezone": timezone},
                "payload": {
                    "kind": "skill_call",
                    **alert_payload,
                },
                "notify": "risk_only",
            }
        ],
        "validation": [
            "dashboard_state_downy_mildew.json updated today",
            "dashboard_state_powdery_mildew.json updated today",
            "forecast_current true for both diseases",
            "forecast_refresh_ok true for both diseases",
            "both dashboard_latest_*_mildew.png files exist and include renderer version",
        ],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }))


if __name__ == "__main__":
    main()
