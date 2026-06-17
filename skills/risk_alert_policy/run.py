#!/usr/bin/env python3
import datetime as dt
import json
import os
import sys


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def rows_from_status(status):
    if not isinstance(status, dict):
        return []
    result = status.get("result", status)
    if isinstance(result, dict) and "current_status" in result:
        result = result["current_status"]
    if isinstance(result, dict) and "result" in result:
        result = result["result"]
    return result.get("rows", []) if isinstance(result, dict) else []


def trained_personalized(row):
    value = row.get("trained")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "trained"}


def first_float(row, keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return None


def risk_value(row, disease=""):
    disease = str(disease or row.get("disease") or row.get("disease_id") or "").lower()
    if disease == "powdery_mildew":
        value = first_float(row, ("powdery_risk", "powdery_uc_risk", "powdery_conidial_ri", "powdery_ascospore_risk"))
        return value if value is not None else 0.0
    if trained_personalized(row):
        value = first_float(row, ("personalized_risk", "risk"))
        if value is not None:
            return value
    value = first_float(row, ("rossi_risk", "baseline_risk", "goidanich_daily_risk"))
    if value is not None:
        return value
    return 0.0


def treatment_due(row):
    for key in ("powdery_pmi_treatment_due", "treatment_due", "first_treatment_due", "pmi_reapply", "rain_reapply"):
        try:
            if float(row.get(key) or 0) > 0:
                return True
        except Exception:
            if row.get(key) in (True, "true", "yes", "due"):
                return True
    action = str(row.get("powdery_pmi_action") or row.get("action") or "").lower()
    return "due" in action or "reapply" in action


def main():
    params = json.load(sys.stdin)
    rows = rows_from_status(params.get("status", params))
    disease = str(params.get("disease") or "").lower()
    memory_path = params.get("memory_path") or "/tmp/vineyard_alert_memory.json"
    high = float(params.get("high_threshold", 70))
    watch = float(params.get("watch_threshold", 50))
    delta_threshold = float(params.get("delta_threshold", 15))
    cooldown_hours = float(params.get("cooldown_hours", 24))
    update_memory = bool(params.get("update_memory", True))
    now = dt.datetime.now(dt.timezone.utc)
    memory = load_json(memory_path, {})

    alerts = []
    for row in rows:
        field = str(row.get("field_id") or row.get("field") or "all")
        day = str(row.get("day") or "")
        risk = risk_value(row, disease)
        previous = memory.get(field, {})
        previous_risk = float(previous.get("risk", 0) or 0)
        last_alert = previous.get("last_alert_at")
        cooldown_active = False
        if last_alert:
            try:
                age_h = (now - dt.datetime.fromisoformat(last_alert)).total_seconds() / 3600
                cooldown_active = age_h < cooldown_hours
            except Exception:
                cooldown_active = False

        severity = "normal"
        if risk >= high:
            severity = "high"
        elif risk >= watch:
            severity = "watch"
        elif treatment_due(row):
            severity = "watch"

        delta = risk - previous_risk
        notify = False
        reason = "below threshold"
        if severity == "high" and not cooldown_active:
            notify = True
            reason = "risk crossed high threshold"
        elif severity == "watch" and delta >= delta_threshold and not cooldown_active:
            notify = True
            reason = "risk rose sharply into watch range"
        elif cooldown_active:
            reason = "cooldown active"

        alerts.append({
            "field": field,
            "day": day,
            "risk": risk,
            "previous_risk": previous_risk,
            "delta": round(delta, 2),
            "severity": severity,
            "notify": notify,
            "reason": reason,
            "cooldown_active": cooldown_active,
            "row": row,
        })

        if update_memory:
            memory[field] = {
                "risk": risk,
                "day": day,
                "severity": severity,
                "last_seen_at": now.isoformat(),
                "last_alert_at": now.isoformat() if notify else previous.get("last_alert_at"),
            }

    if update_memory:
        os.makedirs(os.path.dirname(memory_path) or ".", exist_ok=True)
        with open(memory_path, "w", encoding="utf-8") as handle:
            json.dump(memory, handle)

    notify_any = any(item["notify"] for item in alerts)
    severity_order = {"normal": 0, "watch": 1, "high": 2}
    top = max(alerts, key=lambda item: severity_order.get(item["severity"], 0), default={})
    print(json.dumps({
        "status": "success",
        "notify": notify_any,
        "severity": top.get("severity", "normal"),
        "reason": "; ".join(item["reason"] for item in alerts if item["notify"]) or top.get("reason", "no rows"),
        "alerts": alerts,
        "memory_path": memory_path,
    }))


if __name__ == "__main__":
    main()
