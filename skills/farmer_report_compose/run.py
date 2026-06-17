#!/usr/bin/env python3
import json
import sys


def as_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def avg(values):
    values = [as_float(value) for value in values]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def max_value(values):
    values = [as_float(value) for value in values]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def min_value(values):
    values = [as_float(value) for value in values]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def sum_value(rows, key):
    values = [as_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def latest_value(rows, key):
    for row in reversed(rows):
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def fmt_value(value, suffix=""):
    if value is None or value == "":
        return "not available"
    try:
        return f"{float(value):.1f}{suffix}"
    except Exception:
        return str(value)


def fmt_range(rows):
    if not rows:
        return "not available"
    return f"{rows[0].get('day', '?')} to {rows[-1].get('day', '?')}"


def trend_text(rows):
    if len(rows) < 2:
        return "not enough rows to assess trend"
    first = as_float(rows[0].get("risk"), 0.0)
    last = as_float(rows[-1].get("risk"), 0.0)
    delta = last - first
    if abs(delta) < 2:
        return f"stable (change {delta:+.1f} points)"
    if delta > 0:
        return f"increasing (change {delta:+.1f} points)"
    return f"decreasing (change {delta:+.1f} points)"


def trend_text_for_key(rows, key):
    if len(rows) < 2:
        return "not enough rows to assess trend"
    first = as_float(rows[0].get(key), 0.0)
    last = as_float(rows[-1].get(key), 0.0)
    delta = last - first
    if abs(delta) < 2:
        return f"stable (change {delta:+.1f} points)"
    if delta > 0:
        return f"increasing (change {delta:+.1f} points)"
    return f"decreasing (change {delta:+.1f} points)"


def pressure_label(value):
    value = as_float(value)
    if value is None:
        return "not available"
    if value >= 70:
        return "elevated"
    if value >= 50:
        return "moderate"
    return "low"


def is_trained(row):
    value = row.get("trained")
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        return int(float(value)) == 1
    except Exception:
        return str(value).strip().lower() in {"true", "yes", "trained"}


def first_forecast_event(rows, keys, threshold):
    for row in rows:
        for key in keys:
            value = as_float(row.get(key))
            if value is not None and value >= threshold:
                return row.get("day"), key, value
    return None, None, None


def treatment_text(disease, risk, pmi_due):
    if disease == "powdery_mildew" and pmi_due:
        return "Powdery PMI indicates a protection check/treatment decision is due; confirm with field inspection and treatment records."
    if risk >= 70:
        return "High risk: inspect now and consider treatment only after field confirmation."
    if risk >= 50:
        return "Moderate risk: inspect this week and record feedback."
    return "Low risk: no disease-model treatment signal; continue monitoring."


def compact_status(value):
    if isinstance(value, dict):
        keys = ["ok", "returncode", "rows", "forecast_rows", "line_rows", "forecast_line_rows"]
        compact = {key: value.get(key) for key in keys if key in value}
        stdout = value.get("stdout")
        if isinstance(stdout, dict):
            compact["stdout_ok"] = stdout.get("ok")
            compact["fields"] = list((stdout.get("fields") or {}).keys())
        return compact or value
    return value


def main():
    params = json.load(sys.stdin)
    alert = params.get("alert") or {}
    alerts = alert.get("alerts") or []
    item = ([row for row in alerts if row.get("notify")] or alerts[:1] or [{}])[0]
    disease = params.get("disease") or "downy_mildew"
    plot_path = params.get("plot_path") or ""
    report = params.get("report") or {}
    state = params.get("dashboard_state") or {}
    history = state.get("history") or []
    forecast_rows = state.get("forecast") or []
    line_rows = state.get("line_predictions") or []
    forecast_line_rows = state.get("forecast_line_predictions") or []
    agent = state.get("agent") or {}
    meta = agent.get("metadata") or {}

    row = item.get("row") or {}
    if history:
        row = {**history[-1], **row}

    field = params.get("field") or item.get("field") or row.get("field_id") or "field"
    location = meta.get("location") or agent.get("name") or field
    station = row.get("station") or meta.get("station_code") or "not available"
    variety = meta.get("variety") or "not available"
    day = item.get("day") or row.get("day") or params.get("day") or "today"
    trained_personalized = is_trained(row)
    risk = float(item.get("risk", row.get("personalized_risk") or row.get("risk") or 0))
    if disease == "powdery_mildew":
        powdery_risk = latest_value(history, "powdery_risk")
        if powdery_risk is not None:
            risk = float(powdery_risk)
    severity = item.get("severity") or ("high" if risk >= 70 else "watch" if risk >= 50 else "low")
    risk_label = "high" if risk >= 70 else "moderate" if risk >= 50 else "low"
    reason = item.get("reason") or alert.get("reason") or "standard report requested"
    if reason in {"no current status rows", "no latest row"}:
        reason = "low risk threshold not reached"

    recent = history[-7:]
    previous = history[-14:-7]
    month = history[-31:]
    if disease == "powdery_mildew":
        forecast_keys = ["powdery_projection", "pmi_projection"]
    else:
        forecast_keys = [
            "goidanich_daily_projection",
            "goidanich_accumulated_projection",
            "rossi_projection",
        ]
    watch_day, watch_key, watch_value = first_forecast_event(forecast_rows, forecast_keys, 50)
    high_day, high_key, high_value = first_forecast_event(forecast_rows, forecast_keys, 70)

    latest_pmi_due = as_float(latest_value(history, "powdery_pmi_treatment_due"), 0.0) > 0
    treatment = treatment_text(disease, risk, latest_pmi_due)
    disease_label = disease.replace("_", " ")
    title = f"{disease_label.capitalize()} report for {location}"
    risk_key = "powdery_risk" if disease == "powdery_mildew" else ("risk" if trained_personalized else "baseline_risk")
    if disease == "powdery_mildew":
        risk_name = "Powdery UC risk"
    elif trained_personalized:
        risk_name = "Personalized risk"
    else:
        risk_name = "Goidanich daily risk"

    lines = [
        "## Risk today",
        f"Location: {location}",
        f"Field: {field}",
        f"Station: {station}",
        f"Variety: {variety}",
        f"Date: {day}",
    ]
    if disease == "powdery_mildew":
        powdery_now = as_float(latest_value(history, "powdery_risk"), risk)
        risk_label = "high" if powdery_now >= 70 else "moderate" if powdery_now >= 50 else "low"
        lines.append(f"Powdery UC risk: {powdery_now:.1f}% ({risk_label}).")
        lines.extend([
            f"Powdery UC model: {fmt_value(latest_value(history, 'powdery_risk'), '%')}.",
            f"Powdery PMI: {fmt_value(latest_value(history, 'powdery_pmi'))}.",
            f"PMI action: {latest_value(history, 'powdery_pmi_action') or 'not available'}.",
            f"PMI treatment signal: {'yes' if latest_pmi_due else 'no'}.",
        ])
    else:
        downy_now = as_float(row.get("baseline_risk"), 0.0) or 0.0
        if downy_now >= 70 or high_day:
            downy_signal = "DOWNY ALERT"
        elif downy_now >= 50 or watch_day:
            downy_signal = "DOWNY WATCH"
        else:
            downy_signal = "NO DOWNY ALERT"
        if trained_personalized:
            lines.append(f"Personalized risk: {risk:.1f}% ({risk_label}).")
        else:
            lines.append("Field-specific learned model: not trained yet; using original Goidanich/Rossi layers.")
        lines.append(f"Goidanich daily risk: {fmt_value(row.get('baseline_risk'), '%')}.")
        rossi = row.get("rossi_risk", row.get("rossi_state"))
        lines.append(f"Rossi state/risk: {fmt_value(rossi, '%')} ({pressure_label(rossi)}).")
        lines.append(f"Signal: {downy_signal}.")

    lines.extend([
        "",
        "## General situation",
        f"Alert status: {severity}.",
        f"Reason: {reason}.",
        f"Observed plot window: {fmt_range(month)}.",
        f"{risk_name} trend this week: {trend_text_for_key(recent or history, risk_key)}.",
        f"This week {risk_name}: average {fmt_value(avg(r.get(risk_key) for r in recent), '%')}.",
        f"Last week {risk_name}: average {fmt_value(avg(r.get(risk_key) for r in previous), '%')}.",
        f"Last month {risk_name}: average {fmt_value(avg(r.get(risk_key) for r in month), '%')}, min {fmt_value(min_value(r.get(risk_key) for r in month), '%')}, max {fmt_value(max_value(r.get(risk_key) for r in month), '%')}.",
        f"Neighbour/regional fungal pressure: {fmt_value(row.get('neighbor_alert_risk'), '%')}.",
        f"Observed rain: {fmt_value(sum_value(recent, 'rain'), ' mm')} in 7 days; {fmt_value(sum_value(month, 'rain'), ' mm')} in last month.",
        f"Observed weather this week: average temperature {fmt_value(avg(r.get('temp') for r in recent), ' C')}, average humidity {fmt_value(avg(r.get('humi') for r in recent), '%')}.",
        "",
        "## Weather-based prediction",
        f"Forecast rows: {len(forecast_rows)}.",
        f"Forecast window: {fmt_range(forecast_rows)}.",
        f"Forecast rain total: {fmt_value(sum_value(forecast_rows, 'forecast_rain'), ' mm')}.",
        f"Forecast average temperature: {fmt_value(avg(r.get('forecast_temp') for r in forecast_rows), ' C')}.",
        f"Forecast average humidity: {fmt_value(avg(r.get('forecast_humi') for r in forecast_rows), '%')}.",
        f"First forecast watch signal: {watch_day or 'none'} ({watch_key or 'none'} {fmt_value(watch_value, '%')}).",
        f"First forecast high signal: {high_day or 'none'} ({high_key or 'none'} {fmt_value(high_value, '%')}).",
    ])
    if disease == "powdery_mildew":
        lines.extend([
            f"Max powdery forecast projection: {fmt_value(max_value(r.get('powdery_projection') for r in forecast_rows), '%')}.",
            f"Max PMI forecast projection: {fmt_value(max_value(r.get('pmi_projection') for r in forecast_rows))}.",
        ])
    else:
        lines.extend([
            f"Max Goidanich daily projection: {fmt_value(max_value(r.get('goidanich_daily_projection') for r in forecast_rows), '%')}.",
            f"Max Goidanich accumulated projection: {fmt_value(max_value(r.get('goidanich_accumulated_projection') for r in forecast_rows), '%')}.",
            f"Max Rossi projection: {fmt_value(max_value(r.get('rossi_projection') for r in forecast_rows), '%')}.",
            f"Observed accumulated Goidanich line rows: {len(line_rows)}.",
            f"Forecast accumulated Goidanich line rows: {len(forecast_line_rows)}.",
        ])
    lines.append("Forecast/projection values are warning context, not observed infection labels.")

    lines.extend(["", "## Fungal pressure"])
    if disease == "powdery_mildew":
        lines.extend([
            f"Powdery UC model now: {fmt_value(latest_value(history, 'powdery_risk'), '%')} ({pressure_label(latest_value(history, 'powdery_risk'))}).",
            f"PMI now: {fmt_value(latest_value(history, 'powdery_pmi'))}; action: {latest_value(history, 'powdery_pmi_action') or 'not available'}.",
            f"PMI since treatment: {fmt_value(latest_value(history, 'powdery_pmi_since_treatment'))}.",
        ])
    else:
        rossi = row.get("rossi_risk", row.get("rossi_state"))
        lines.extend([
            f"Rossi comparison model: {fmt_value(rossi, '%')} ({pressure_label(rossi)}).",
            f"This week max Rossi: {fmt_value(max_value(r.get('rossi_risk') for r in recent), '%')}.",
            f"Rossi primary events this week: {sum(int(as_float(r.get('rossi_primary_events'), 0) or 0) for r in recent)}.",
            f"Rossi oilspot events this week: {sum(int(as_float(r.get('rossi_oilspot_events'), 0) or 0) for r in recent)}.",
        ])

    lines.extend([
        "",
        "## Treatment guidance",
        treatment,
        "Treatment is never automatic: confirm canopy state, recent protection, and scouting observations before action.",
        "Record clean inspection, detected mildew, grade, treatment, or false alarm feedback after field inspection.",
        "",
        "## Evidence",
        f"Model version: {row.get('model_version', 'unknown')}.",
        f"Personalized model trained: {'yes' if trained_personalized else 'no; farmer-facing risk uses original Goidanich/Rossi layers'}." if disease != "powdery_mildew" else "Powdery headline uses UC/PMI disease-specific model fields.",
        f"Dashboard database: {state.get('db', 'not available')}.",
        f"Dashboard state rows: {state.get('rows', len(history))}.",
        f"Gap fill: {compact_status(state.get('fill_gaps', 'not available'))}.",
        f"Forecast refresh: {compact_status(state.get('forecast_refresh', 'not available'))}.",
    ])
    if report.get("report"):
        lines.append(f"Report artifact: {report['report']}.")
    lines.append("Plot: attached as image." if plot_path else "Plot: not available; do not send report until plot is generated.")

    print(json.dumps({
        "status": "success",
        "title": title,
        "message": "\n".join(lines),
        "plot_path": plot_path,
        "field": field,
        "severity": severity,
        "risk": risk,
        "treatment_guidance": treatment,
    }))


if __name__ == "__main__":
    main()
