#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys


MODEL_INFO = {
    "model": "VitiMeteo grapevine black-rot infection and leaf-incubation model",
    "model_version": "vitimeteo_black_rot_infection_incubation_v2",
    "disease": "grapevine black rot",
    "pathogen": "Guignardia bidwellii",
    "pathogen_synonym": "Phyllosticta ampelicida",
    "scope_excludes": [
        "secondary grape bunch rots",
        "Aspergillus spp.",
        "Penicillium spp.",
        "other opportunistic bunch-rot fungi",
    ],
    "infection_index_unit": "degree-hours",
    "infection_thresholds": {"none": "<85", "light": "85-<150", "moderate": "150-300", "severe": ">300"},
    "incubation_target_degree_days": 175,
    "wetness_requirement": "leaf wetness; board fallback is an explicit rain/RH>=95% proxy",
    "wetness_uncertainty": "RH 90-<95% sensitivity upper bound; watch only, not a confirmed event",
    "implemented_model_evidence": [
        "doi:10.1007/s10658-015-0835-0",
        "https://wiki.vitimeteo.info/bin/view/Die%20Modelle%20/VM%20Blackrot%20/?language=en",
    ],
    "related_weather_model_validation": "doi:10.1002/ps.4277",
}


def load_params():
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def repo_path(params):
    candidates = [
        params.get("repo_path"),
        os.environ.get("SKILL_REPO_PATH"),
        "/root/.picoclaw/workspace/goidanich",
        "/Users/vbaulin/antigr/goidanich",
    ]
    return next((path for path in candidates if path and os.path.isdir(path)), candidates[2])


def load_config(repo):
    try:
        import yaml
        with open(os.path.join(repo, "agent_config.yaml"), encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


def configured_fields(repo, requested=""):
    fields = load_config(repo).get("fields") or []
    if requested:
        fields = [field for field in fields if field.get("id") == requested]
    return fields


def latest_observed_day(repo, fields):
    stations = []
    for field in fields:
        metadata = field.get("metadata") or {}
        station = field.get("station_code") or metadata.get("station_code")
        if station:
            stations.append(station)
    if not stations:
        return dt.date.today().isoformat()
    db = os.path.join(repo, "goidanich.db")
    placeholders = ",".join("?" for _ in stations)
    try:
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                f"""
                SELECT max(substr(data_lectura, 1, 10))
                FROM meteo_raw
                WHERE codi_estacio IN ({placeholders}) AND codi_variable IN (32, 33, 35)
                """,
                stations,
            ).fetchone()
        return str(row[0])[:10] if row and row[0] else dt.date.today().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def safe(value):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "")).strip("_")


def state_path(repo, field_id):
    return os.path.join(repo, "results", f"dashboard_state_black_rot_{safe(field_id)}.json")


def current_state(path, today):
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return None
    freshness = state.get("model_layer_freshness") or {}
    plot = state.get("plot_path") or ""
    if (
        state.get("ok")
        and str(state.get("end") or "")[:10] == today
        and freshness.get("history_current")
        and freshness.get("forecast_current")
        and freshness.get("black_rot_current")
        and freshness.get("black_rot_forecast_current")
        and plot
        and os.path.exists(plot)
    ):
        return state
    return None


def refresh(repo, field_id, days, today, skip_forecast=False):
    start = (dt.date.fromisoformat(today) - dt.timedelta(days=days - 1)).isoformat()
    cmd = [
        sys.executable,
        os.path.join(repo, "board_update_dashboard.py"),
        "--field", field_id,
        "--disease", "black_rot",
        "--start", start,
        "--end", today,
        "--days", str(days),
    ]
    if skip_forecast:
        cmd.append("--skip-forecast")
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, timeout=900)
    try:
        output = json.loads(proc.stdout)
    except Exception:
        output = {"raw": proc.stdout[-2000:]}
    return {"ok": proc.returncode == 0 and bool(output.get("ok")), "output": output, "stderr": proc.stderr[-2000:]}


def language(repo):
    config = load_config(repo)
    return str((config.get("notifications") or {}).get("language") or (config.get("board") or {}).get("preferred_language") or "en").lower()


def field_label(field, multi_field=False):
    if multi_field:
        return field.get("name") or field.get("location") or field.get("id")
    return field.get("location") or field.get("name") or field.get("id")


def wetness_evidence(values, lang, forecast=False):
    suffix = "_projection" if forecast else ""
    driver = str(values.get(f"black_rot_wetness_driver{suffix}") or values.get("wetness_driver") or "none")
    wet_hours = int(float(values.get(f"black_rot_wet_hours{suffix}") or values.get("wet_hours") or 0))
    humidity_hours = int(float(values.get(f"black_rot_humidity_wet_hours{suffix}") or values.get("humidity_wet_hours") or 0))
    rain_hours = int(float(values.get(f"black_rot_rain_wet_hours{suffix}") or values.get("rain_wet_hours") or 0))
    near_saturation_hours = int(float(
        values.get(f"black_rot_near_saturation_hours{suffix}")
        or values.get("near_saturation_hours")
        or 0
    ))
    potential_index = float(
        values.get(f"black_rot_potential_infection_index{suffix}")
        or values.get("potential_infection_index")
        or 0.0
    )
    max_humidity = values.get(f"black_rot_max_humi{suffix}")
    if max_humidity is None:
        max_humidity = values.get("max_humidity")
    max_humidity_text = f"{float(max_humidity):.1f}%" if max_humidity is not None else "n/a"
    if lang.startswith("ca"):
        local_driver = {
            "humidity": "humitat alta",
            "rain": "pluja",
            "rain_and_humidity": "pluja i humitat alta",
            "measured": "sensor d'humectació",
            "none": "sense humectació",
        }.get(driver, driver)
        hours_label = {
            "measured": f"{wet_hours} h mesurades pel sensor",
            "humidity": f"{wet_hours} h estimades pel proxy d'humitat",
            "rain": f"{wet_hours} h estimades amb suport de pluja",
            "rain_and_humidity": f"{wet_hours} h estimades amb pluja i humitat",
            "none": f"{wet_hours} h estimades",
        }.get(driver, f"{wet_hours} h estimades")
        return (
            f"{hours_label} ({humidity_hours} h amb HR >=95%, {rain_hours} h amb pluja; "
            f"{near_saturation_hours} h amb HR 90-<95%; HR màxima {max_humidity_text}); "
            f"origen: {local_driver}; índex potencial si el dosser era humit: {potential_index:.1f} graus-hora"
        )
    if lang.startswith("es"):
        local_driver = {
            "humidity": "humedad alta",
            "rain": "lluvia",
            "rain_and_humidity": "lluvia y humedad alta",
            "measured": "sensor de humectación",
            "none": "sin humectación",
        }.get(driver, driver)
        hours_label = {
            "measured": f"{wet_hours} h medidas por el sensor",
            "humidity": f"{wet_hours} h estimadas por el proxy de humedad",
            "rain": f"{wet_hours} h estimadas con apoyo de lluvia",
            "rain_and_humidity": f"{wet_hours} h estimadas con lluvia y humedad",
            "none": f"{wet_hours} h estimadas",
        }.get(driver, f"{wet_hours} h estimadas")
        return (
            f"{hours_label} ({humidity_hours} h con HR >=95%, {rain_hours} h con lluvia; "
            f"{near_saturation_hours} h con HR 90-<95%; HR máxima {max_humidity_text}); "
            f"origen: {local_driver}; índice potencial si el dosel estaba húmedo: {potential_index:.1f} grados-hora"
        )
    local_driver = {
        "humidity": "high humidity",
        "rain": "rain",
        "rain_and_humidity": "rain and high humidity",
        "measured": "leaf-wetness sensor",
        "none": "no wetness",
    }.get(driver, driver)
    hours_label = {
        "measured": f"{wet_hours} sensor-measured h",
        "humidity": f"{wet_hours} h estimated by the humidity proxy",
        "rain": f"{wet_hours} h estimated with rain support",
        "rain_and_humidity": f"{wet_hours} h estimated from rain and humidity",
        "none": f"{wet_hours} estimated h",
    }.get(driver, f"{wet_hours} estimated h")
    return (
        f"{hours_label} ({humidity_hours} h at RH >=95%, {rain_hours} h with rain; "
        f"{near_saturation_hours} h at RH 90-<95%; maximum RH {max_humidity_text}); "
        f"source: {local_driver}; potential index if the canopy was wet: {potential_index:.1f} degree-hours"
    )


def wetness_uncertain_watch(values, forecast=False):
    suffix = "_projection" if forecast else ""
    return bool(
        values.get(f"black_rot_wetness_uncertain_watch{suffix}")
        or values.get("wetness_uncertain_watch")
    )


def forecast_event_evidence(forecast):
    explicit = str(forecast.get("event_evidence") or "").strip()
    if explicit:
        return explicit
    driver = str(forecast.get("wetness_driver") or "none")
    if driver == "humidity" and float(forecast.get("rain_wet_hours") or 0) <= 0:
        return "humidity_proxy"
    if driver in {"rain", "rain_and_humidity"}:
        return "rain_supported_proxy"
    if driver == "measured":
        return "measured_leaf_wetness"
    return "unknown"


def subthreshold_wetness_state(latest, forecast):
    current_index = float(latest.get("black_rot_infection_index") or 0.0)
    current_wet_hours = int(float(latest.get("black_rot_wet_hours") or 0))
    forecast_index = float(forecast.get("max_infection_index") or 0.0)
    forecast_wet_hours = int(float(forecast.get("wet_hours") or 0))
    candidates = []
    if 0.0 < current_index < 85.0 and current_wet_hours > 0:
        candidates.append({
            "index": current_index,
            "day": str(latest.get("day") or "")[:10],
            "forecast": False,
        })
    if 0.0 < forecast_index < 85.0 and forecast_wet_hours > 0:
        candidates.append({
            "index": forecast_index,
            "day": str(forecast.get("max_day") or "")[:10],
            "forecast": True,
        })
    return max(candidates, key=lambda item: item["index"]) if candidates else None


def subthreshold_wetness(latest, forecast):
    return bool(subthreshold_wetness_state(latest, forecast))


def collapse_equivalent_reports(reports):
    latest_keys = (
        "day", "black_rot_infection_index", "black_rot_potential_infection_index",
        "black_rot_wetness_uncertain_watch", "black_rot_wetness_driver",
        "black_rot_wet_hours", "black_rot_humidity_wet_hours", "black_rot_rain_wet_hours",
        "black_rot_near_saturation_hours", "black_rot_max_humi", "black_rot_inoculum_status",
    )
    forecast_keys = (
        "first_infection_day", "first_uncertain_watch_day", "max_infection_index", "max_day",
        "max_potential_infection_index", "max_potential_day", "event_evidence", "wetness_driver",
        "wet_hours", "humidity_wet_hours", "rain_wet_hours", "near_saturation_hours",
        "max_humidity",
    )
    grouped = {}
    for report in reports:
        latest = report.get("latest") or {}
        forecast = report.get("forecast_prediction") or {}
        signature = (
            tuple(latest.get(key) for key in latest_keys),
            tuple(forecast.get(key) for key in forecast_keys),
            forecast_event_evidence(forecast),
        )
        label = report.get("field_label") or report.get("field")
        if signature not in grouped:
            grouped[signature] = {**report, "_field_labels": [label]}
        else:
            grouped[signature]["_field_labels"].append(label)
    output = []
    for report in grouped.values():
        report = dict(report)
        report["field_label"] = ", ".join(report.pop("_field_labels"))
        output.append(report)
    return output


def message_for(field, state, lang, label=None):
    latest = state.get("latest") or {}
    forecast = state.get("forecast_prediction") or {}
    location = label or field_label(field)
    index = float(latest.get("black_rot_infection_index") or 0.0)
    severity = latest.get("black_rot_severity") or "none"
    event = bool(latest.get("black_rot_infection_event"))
    symptom = latest.get("black_rot_symptom_date") or "outside the current horizon"
    inoculum = latest.get("black_rot_inoculum_status") or "unknown"
    wetness = latest.get("black_rot_wetness_source") or "unknown"
    forecast_max = forecast.get("max_infection_index")
    forecast_day = forecast.get("max_day")
    first_event = forecast.get("first_infection_day")
    forecast_evidence_class = forecast_event_evidence(forecast)
    first_uncertain_watch = forecast.get("first_uncertain_watch_day")
    current_uncertain_watch = wetness_uncertain_watch(latest)
    current_wetness = wetness_evidence(latest, lang)
    forecast_wetness = wetness_evidence(forecast, lang, forecast=True)
    if lang.startswith("ca"):
        severity_local = {"none": "cap", "light": "lleu", "moderate": "moderat", "severe": "greu"}.get(severity, severity)
        inoculum_local = {"unknown": "desconegut", "present": "present", "not_reported": "no notificat"}.get(inoculum, inoculum)
        wetness_local = "proxy de pluja o HR >=95%" if wetness == "rain_or_rh95_proxy_v1" else wetness
        symptom_local = "fora de l'horitzó actual" if symptom == "outside the current horizon" else symptom
        if first_event:
            if forecast_evidence_class == "humidity_proxy":
                forecast_text = (
                    f"vigilància d'infecció basada en el proxy d'humitat el {first_event}; "
                    f"l'índex arriba a {float(forecast_max):.1f} graus-hora el {forecast_day} "
                    "si HR >=95% equival a humectació foliar contínua; cap sensor ho confirma."
                )
            else:
                forecast_text = f"primer episodi >=85 graus-hora el {first_event}; màxim {float(forecast_max):.1f} el {forecast_day}."
        elif first_uncertain_watch:
            forecast_text = (
                f"possible humectació no mesurada el {first_uncertain_watch}; "
                f"índex principal màxim {float(forecast_max):.1f} graus-hora i índex potencial "
                f"{float(forecast.get('max_potential_infection_index') or 0):.1f} graus-hora."
            )
        elif forecast_max is not None:
            forecast_text = f"cap episodi modelitzat; màxim {float(forecast_max):.1f} graus-hora el {forecast_day}."
        else:
            forecast_text = "no disponible."
        current_watch_text = (
            "⚠️ Vigilància d'humectació: la HR de 90-<95% pot correspondre a rosada o a un dosser més humit que l'estació; inspeccioneu el camp.\n"
            if current_uncertain_watch else ""
        )
        return (
            f"🍇 Black rot de la vinya (Guignardia bidwellii) - {location}\n"
            f"Data: {latest.get('day')} | Índex d'infecció: {index:.1f} graus-hora ({severity_local}).\n"
            f"Nou episodi d'infecció avui: {'sí' if event else 'no'}.\n"
            f"{current_watch_text}"
            f"Previsió: {forecast_text}\n"
            f"Data prevista de símptomes foliars: {symptom_local}.\n"
            f"Inòcul local: {inoculum_local}. Humectació foliar: {wetness_local}.\n"
            f"Evidència d'humectació avui: {current_wetness}.\n"
            f"Evidència al primer episodi/pic previst: {forecast_wetness}.\n"
            "L'índex principal 0 no és una probabilitat de malaltia del 0%; significa que el proxy no ha confirmat humectació foliar. "
            "La previsió indica condicions d'infecció, no malaltia confirmada, i no quantifica les lesions ja presents. "
            "Aquest model no avalua les podridures secundàries del raïm causades per Aspergillus, Penicillium o altres fongs oportunistes. "
            "Confirmeu amb inspecció abans de decidir un tractament."
        )
    if lang.startswith("es"):
        severity_local = {"none": "ninguno", "light": "leve", "moderate": "moderado", "severe": "grave"}.get(severity, severity)
        inoculum_local = {"unknown": "desconocido", "present": "presente", "not_reported": "no notificado"}.get(inoculum, inoculum)
        wetness_local = "proxy de lluvia o HR >=95%" if wetness == "rain_or_rh95_proxy_v1" else wetness
        symptom_local = "fuera del horizonte actual" if symptom == "outside the current horizon" else symptom
        if first_event:
            if forecast_evidence_class == "humidity_proxy":
                forecast_text = (
                    f"vigilancia de infección basada en el proxy de humedad el {first_event}; "
                    f"el índice alcanza {float(forecast_max):.1f} grados-hora el {forecast_day} "
                    "si HR >=95% equivale a humectación foliar continua; ningún sensor lo confirma."
                )
            else:
                forecast_text = f"primer episodio >=85 grados-hora el {first_event}; máximo {float(forecast_max):.1f} el {forecast_day}."
        elif first_uncertain_watch:
            forecast_text = (
                f"posible humectación no medida el {first_uncertain_watch}; "
                f"índice principal máximo {float(forecast_max):.1f} grados-hora e índice potencial "
                f"{float(forecast.get('max_potential_infection_index') or 0):.1f} grados-hora."
            )
        elif forecast_max is not None:
            forecast_text = f"ningún episodio modelizado; máximo {float(forecast_max):.1f} grados-hora el {forecast_day}."
        else:
            forecast_text = "no disponible."
        current_watch_text = (
            "⚠️ Vigilancia de humectación: la HR de 90-<95% puede corresponder a rocío o a un dosel más húmedo que la estación; inspeccione el campo.\n"
            if current_uncertain_watch else ""
        )
        return (
            f"🍇 Black rot de la vid (Guignardia bidwellii) - {location}\n"
            f"Fecha: {latest.get('day')} | Índice de infección: {index:.1f} grados-hora ({severity_local}).\n"
            f"Nuevo episodio de infección hoy: {'sí' if event else 'no'}.\n"
            f"{current_watch_text}"
            f"Predicción: {forecast_text}\n"
            f"Fecha prevista de síntomas foliares: {symptom_local}.\n"
            f"Inóculo local: {inoculum_local}. Humectación foliar: {wetness_local}.\n"
            f"Evidencia de humectación hoy: {current_wetness}.\n"
            f"Evidencia en el primer episodio/pico previsto: {forecast_wetness}.\n"
            "Un índice principal 0 no es una probabilidad de enfermedad del 0%; significa que el proxy no confirmó humectación foliar. "
            "La predicción indica condiciones de infección, no enfermedad confirmada, y no cuantifica las lesiones ya presentes. "
            "Este modelo no evalúa las podredumbres secundarias de la uva causadas por Aspergillus, Penicillium u otros hongos oportunistas. "
            "Confirme mediante inspección antes de decidir un tratamiento."
        )
    if first_event:
        if forecast_evidence_class == "humidity_proxy":
            forecast_text = (
                f"humidity-proxy infection watch on {first_event}; the index reaches "
                f"{float(forecast_max):.1f} degree-hours on {forecast_day} if RH >=95% "
                "represents continuous leaf wetness; no sensor confirms it."
            )
        else:
            forecast_text = f"first event >=85 degree-hours on {first_event}; maximum {float(forecast_max):.1f} on {forecast_day}."
    elif first_uncertain_watch:
        forecast_text = (
            f"possible unmeasured leaf wetness on {first_uncertain_watch}; primary maximum "
            f"{float(forecast_max):.1f} degree-hours and potential index "
            f"{float(forecast.get('max_potential_infection_index') or 0):.1f} degree-hours."
        )
    elif forecast_max is not None:
        forecast_text = f"no modeled event; maximum {float(forecast_max):.1f} degree-hours on {forecast_day}."
    else:
        forecast_text = "unavailable."
    current_watch_text = (
        "⚠️ Wetness watch: RH 90-<95% may represent dew or a wetter canopy than the station; inspect the field.\n"
        if current_uncertain_watch else ""
    )
    return (
        f"🍇 Grapevine black rot (Guignardia bidwellii) - {location}\n"
        f"Date: {latest.get('day')} | Infection index: {index:.1f} degree-hours ({severity}).\n"
        f"New infection event today: {'yes' if event else 'no'}.\n"
        f"{current_watch_text}"
        f"Forecast: {forecast_text}\n"
        f"Projected leaf-symptom date: {symptom}.\n"
        f"Local inoculum: {inoculum}. Leaf wetness: {wetness}.\n"
        f"Wetness evidence today: {current_wetness}.\n"
        f"Wetness evidence at the first forecast event/peak: {forecast_wetness}.\n"
        "A primary index of 0 is not 0% disease probability; it means the proxy did not confirm leaf wetness. "
        "The forecast identifies infection conditions, not confirmed disease, and does not quantify existing lesions. "
        "This model does not assess secondary grape bunch rots caused by Aspergillus, Penicillium, or other opportunistic fungi. "
        "Confirm by scouting before a treatment decision."
    )


def technical_daily_summary_for(reports, lang):
    successful = collapse_equivalent_reports(
        [report for report in reports if report.get("status") == "success"]
    )
    day = next((str((report.get("latest") or {}).get("day") or "")[:10] for report in successful), "")
    if lang.startswith("ca"):
        lines = ["🍇 Previsió de black rot de la vinya (Guignardia bidwellii)"]
        if day:
            lines.append(f"Data: {day}")
        for report in successful:
            latest = report.get("latest") or {}
            forecast = report.get("forecast_prediction") or {}
            label = report.get("field_label") or report.get("field")
            index = float(latest.get("black_rot_infection_index") or 0.0)
            first_event = forecast.get("first_infection_day")
            first_uncertain_watch = forecast.get("first_uncertain_watch_day")
            maximum = float(forecast.get("max_infection_index") or 0.0)
            max_day = forecast.get("max_day") or ""
            inoculum = latest.get("black_rot_inoculum_status") or "unknown"
            current_wetness = wetness_evidence(latest, lang)
            forecast_wetness = wetness_evidence(forecast, lang, forecast=True)
            inoculum_note = " Inòcul local present." if inoculum == "present" else ""
            current_uncertain_watch = wetness_uncertain_watch(latest)
            subthreshold = subthreshold_wetness_state(latest, forecast)
            potential = float(latest.get("black_rot_potential_infection_index") or 0.0)
            current_humidity_proxy = latest.get("black_rot_wetness_driver") == "humidity"
            forecast_humidity_proxy = forecast_event_evidence(forecast) == "humidity_proxy"
            if index >= 85.0:
                if current_humidity_proxy:
                    lines.append(
                        f"⚠️ {label}: vigilància d'infecció basada en el proxy d'humitat, índex "
                        f"{index:.1f} graus-hora; {current_wetness}. Sense sensor d'humectació no "
                        f"es confirma l'episodi.{inoculum_note}"
                    )
                else:
                    lines.append(f"⚠️ {label}: episodi actual, índex {index:.1f} graus-hora; humectació {current_wetness}.{inoculum_note}")
            elif current_uncertain_watch:
                lines.append(
                    f"⚠️ {label}: possible humectació foliar no mesurada; índex principal {index:.1f} "
                    f"graus-hora, però índex potencial {potential:.1f}; {current_wetness}.{inoculum_note}"
                )
            elif first_event:
                if forecast_humidity_proxy:
                    lines.append(
                        f"⚠️ {label}: vigilància d'infecció basada en el proxy d'humitat el {first_event}; "
                        f"màxim {maximum:.1f} graus-hora el {max_day} si HR >=95% equival a humectació "
                        f"foliar contínua; {forecast_wetness}. Cap sensor ho confirma.{inoculum_note}"
                    )
                else:
                    lines.append(
                        f"⚠️ {label}: cap episodi avui; primer episodi previst el {first_event} "
                        f"(màxim {maximum:.1f} graus-hora el {max_day}); humectació prevista {forecast_wetness}.{inoculum_note}"
                    )
            elif first_uncertain_watch:
                lines.append(
                    f"⚠️ {label}: possible humectació foliar prevista no mesurada el {first_uncertain_watch}; "
                    f"{forecast_wetness}.{inoculum_note}"
                )
            elif subthreshold:
                subthreshold_evidence = forecast_wetness if subthreshold["forecast"] else current_wetness
                lines.append(
                    f"🟡 {label}: període humit subllindar; màxim {subthreshold['index']:.1f} de 85 graus-hora"
                    + (f" el {subthreshold['day']}; humectació del pic {subthreshold_evidence}." if subthreshold["day"] else ".")
                    + inoculum_note
                    + " No és risc zero ni un episodi d'infecció confirmat."
                )
            elif inoculum == "present":
                lines.append(
                    f"🟡 {label}: cap nou episodi d'infecció modelitzat; màxim {maximum:.1f} de 85 graus-hora"
                    + (f" el {max_day}." if max_day else ".")
                    + " Inòcul local present; el model no quantifica les lesions existents."
                )
            else:
                lines.append(
                    f"🟢 {label}: cap episodi actual ni previst; màxim {maximum:.1f} graus-hora"
                    + (f" el {max_day}; humectació del pic {forecast_wetness}." if max_day else ".") + inoculum_note
                )
        lines.append(
            "La humectació foliar és una estimació basada en pluja/HR >=95%; "
            "la HR de 90-<95% activa una vigilància d'incertesa, no un episodi confirmat. "
            "Un índex principal 0 no significa una probabilitat de malaltia del 0%. "
            "Aquest model no avalua les podridures secundàries del raïm per Aspergillus, Penicillium o altres fongs oportunistes."
        )
        return "\n".join(lines)
    if lang.startswith("es"):
        lines = ["🍇 Predicción de black rot de la vid (Guignardia bidwellii)"]
        if day:
            lines.append(f"Fecha: {day}")
        for report in successful:
            latest = report.get("latest") or {}
            forecast = report.get("forecast_prediction") or {}
            label = report.get("field_label") or report.get("field")
            index = float(latest.get("black_rot_infection_index") or 0.0)
            first_event = forecast.get("first_infection_day")
            first_uncertain_watch = forecast.get("first_uncertain_watch_day")
            maximum = float(forecast.get("max_infection_index") or 0.0)
            max_day = forecast.get("max_day") or ""
            inoculum = latest.get("black_rot_inoculum_status") or "unknown"
            current_wetness = wetness_evidence(latest, lang)
            forecast_wetness = wetness_evidence(forecast, lang, forecast=True)
            inoculum_note = " Inóculo local presente." if inoculum == "present" else ""
            current_uncertain_watch = wetness_uncertain_watch(latest)
            subthreshold = subthreshold_wetness_state(latest, forecast)
            potential = float(latest.get("black_rot_potential_infection_index") or 0.0)
            current_humidity_proxy = latest.get("black_rot_wetness_driver") == "humidity"
            forecast_humidity_proxy = forecast_event_evidence(forecast) == "humidity_proxy"
            if index >= 85.0:
                if current_humidity_proxy:
                    lines.append(
                        f"⚠️ {label}: vigilancia de infección basada en el proxy de humedad, índice "
                        f"{index:.1f} grados-hora; {current_wetness}. Sin sensor de humectación no "
                        f"se confirma el episodio.{inoculum_note}"
                    )
                else:
                    lines.append(f"⚠️ {label}: episodio actual, índice {index:.1f} grados-hora; humectación {current_wetness}.{inoculum_note}")
            elif current_uncertain_watch:
                lines.append(
                    f"⚠️ {label}: posible humectación foliar no medida; índice principal {index:.1f} "
                    f"grados-hora, pero índice potencial {potential:.1f}; {current_wetness}.{inoculum_note}"
                )
            elif first_event:
                if forecast_humidity_proxy:
                    lines.append(
                        f"⚠️ {label}: vigilancia de infección basada en el proxy de humedad el {first_event}; "
                        f"máximo {maximum:.1f} grados-hora el {max_day} si HR >=95% equivale a humectación "
                        f"foliar continua; {forecast_wetness}. Ningún sensor lo confirma.{inoculum_note}"
                    )
                else:
                    lines.append(
                        f"⚠️ {label}: sin episodio hoy; primer episodio previsto el {first_event} "
                        f"(máximo {maximum:.1f} grados-hora el {max_day}); humectación prevista {forecast_wetness}.{inoculum_note}"
                    )
            elif first_uncertain_watch:
                lines.append(
                    f"⚠️ {label}: posible humectación foliar prevista no medida el {first_uncertain_watch}; "
                    f"{forecast_wetness}.{inoculum_note}"
                )
            elif subthreshold:
                subthreshold_evidence = forecast_wetness if subthreshold["forecast"] else current_wetness
                lines.append(
                    f"🟡 {label}: periodo húmedo subumbral; máximo {subthreshold['index']:.1f} de 85 grados-hora"
                    + (f" el {subthreshold['day']}; humectación del pico {subthreshold_evidence}." if subthreshold["day"] else ".")
                    + inoculum_note
                    + " No es riesgo cero ni un episodio de infección confirmado."
                )
            elif inoculum == "present":
                lines.append(
                    f"🟡 {label}: ningún episodio nuevo de infección modelizado; máximo {maximum:.1f} de 85 grados-hora"
                    + (f" el {max_day}." if max_day else ".")
                    + " Inóculo local presente; el modelo no cuantifica las lesiones existentes."
                )
            else:
                lines.append(
                    f"🟢 {label}: sin episodio actual ni previsto; máximo {maximum:.1f} grados-hora"
                    + (f" el {max_day}; humectación del pico {forecast_wetness}." if max_day else ".") + inoculum_note
                )
        lines.append(
            "La humedad foliar es una estimación basada en lluvia/HR >=95%; "
            "la HR de 90-<95% activa una vigilancia de incertidumbre, no un episodio confirmado. "
            "Un índice principal 0 no significa una probabilidad de enfermedad del 0%."
        )
        return "\n".join(lines)
    lines = ["🍇 Daily black-rot prognosis"]
    if day:
        lines.append(f"Date: {day}")
    for report in successful:
        latest = report.get("latest") or {}
        forecast = report.get("forecast_prediction") or {}
        label = report.get("field_label") or report.get("field")
        index = float(latest.get("black_rot_infection_index") or 0.0)
        first_event = forecast.get("first_infection_day")
        first_uncertain_watch = forecast.get("first_uncertain_watch_day")
        maximum = float(forecast.get("max_infection_index") or 0.0)
        max_day = forecast.get("max_day") or ""
        inoculum = latest.get("black_rot_inoculum_status") or "unknown"
        current_wetness = wetness_evidence(latest, lang)
        forecast_wetness = wetness_evidence(forecast, lang, forecast=True)
        inoculum_note = " Local inoculum is present." if inoculum == "present" else ""
        current_uncertain_watch = wetness_uncertain_watch(latest)
        subthreshold = subthreshold_wetness_state(latest, forecast)
        potential = float(latest.get("black_rot_potential_infection_index") or 0.0)
        current_humidity_proxy = latest.get("black_rot_wetness_driver") == "humidity"
        forecast_humidity_proxy = forecast_event_evidence(forecast) == "humidity_proxy"
        if index >= 85.0:
            if current_humidity_proxy:
                lines.append(
                    f"⚠️ {label}: humidity-proxy infection watch, index {index:.1f} degree-hours; "
                    f"{current_wetness}. Without a leaf-wetness sensor this is not a confirmed event.{inoculum_note}"
                )
            else:
                lines.append(f"⚠️ {label}: current event, index {index:.1f} degree-hours; wetness {current_wetness}.{inoculum_note}")
        elif current_uncertain_watch:
            lines.append(
                f"⚠️ {label}: possible unmeasured leaf wetness; primary index {index:.1f} "
                f"degree-hours, but potential index {potential:.1f}; {current_wetness}.{inoculum_note}"
            )
        elif first_event:
            if forecast_humidity_proxy:
                lines.append(
                    f"⚠️ {label}: humidity-proxy infection watch on {first_event}; maximum "
                    f"{maximum:.1f} degree-hours on {max_day} if RH >=95% represents continuous "
                    f"leaf wetness; {forecast_wetness}. No sensor confirms it.{inoculum_note}"
                )
            else:
                lines.append(
                    f"⚠️ {label}: no event today; first forecast event on {first_event} "
                    f"(maximum {maximum:.1f} degree-hours on {max_day}); forecast wetness {forecast_wetness}.{inoculum_note}"
                )
        elif first_uncertain_watch:
            lines.append(
                f"⚠️ {label}: possible unmeasured forecast leaf wetness on {first_uncertain_watch}; "
                f"{forecast_wetness}.{inoculum_note}"
            )
        elif subthreshold:
            subthreshold_evidence = forecast_wetness if subthreshold["forecast"] else current_wetness
            lines.append(
                f"🟡 {label}: subthreshold wet period; maximum {subthreshold['index']:.1f} of 85 degree-hours"
                + (f" on {subthreshold['day']}; peak wetness {subthreshold_evidence}." if subthreshold["day"] else ".")
                + inoculum_note
                + " This is neither zero risk nor a confirmed infection event."
            )
        elif inoculum == "present":
            lines.append(
                f"🟡 {label}: no new modeled infection event; maximum {maximum:.1f} of 85 degree-hours"
                + (f" on {max_day}." if max_day else ".")
                + " Local inoculum is present; the model does not quantify existing lesions."
            )
        else:
            lines.append(
                f"🟢 {label}: no current or forecast event; maximum {maximum:.1f} degree-hours"
                + (f" on {max_day}; peak wetness {forecast_wetness}." if max_day else ".") + inoculum_note
            )
    lines.append(
        "Leaf wetness is estimated from rain/RH >=95%; confirm local inoculum and scout before a treatment decision."
        " RH 90-<95% raises an uncertainty watch, not a confirmed event. A primary index of 0 is not 0% disease probability."
    )
    return "\n".join(lines)


def _days_between(start, end):
    try:
        return (dt.date.fromisoformat(str(end)[:10]) - dt.date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def daily_summary_for(reports, lang):
    """Return the action-oriented farmer summary; technical evidence stays in field_reports."""
    successful = collapse_equivalent_reports(
        [report for report in reports if report.get("status") == "success"]
    )
    day = next((str((report.get("latest") or {}).get("day") or "")[:10] for report in successful), "")
    language_code = "ca" if lang.startswith("ca") else "es" if lang.startswith("es") else "en"
    copy = {
        "ca": {
            "title": "🍇 Black rot de la vinya (Guignardia bidwellii)",
            "date": "Data",
            "current_humidity": "🔴 {label}: possible finestra d'infecció avui després d'una nit molt humida. Comproveu si les fulles han quedat mullades i inspeccioneu el camp avui.",
            "current_wet": "🔴 {label}: les condicions d'humectació poden haver permès una infecció avui. Inspeccioneu el camp i reviseu la protecció recent.",
            "current_uncertain": "🟠 {label}: pot haver-hi rosada o fulla mullada que l'estació no pot confirmar. Inspeccioneu les zones més humides avui.",
            "near_humidity": "🟠 {label}: risc elevat el {event} per humitat nocturna molt alta. És una alerta meteorològica, no una infecció confirmada. Comproveu la humectació real del dosser i inspeccioneu abans de decidir cap tractament.",
            "near_rain": "🟠 {label}: la pluja pot obrir una finestra d'infecció el {event}. Reviseu el camp i la protecció abans d'aquest dia.",
            "later_humidity": "🟡 {label}: possible finestra d'infecció cap al {event} si les nits continuen molt humides. No cal actuar ara; torneu a revisar la previsió 48 hores abans.",
            "later_rain": "🟡 {label}: possible finestra d'infecció cap al {event} associada a pluja. No cal actuar ara; torneu a revisar la previsió 48 hores abans.",
            "near_uncertain": "🟡 {label}: el {event} podria haver-hi rosada o fulla mullada, però no hi ha sensor que ho confirmi. Feu una inspecció ràpida de les zones humides.",
            "later_uncertain": "🟡 {label}: possible humectació cap al {event}, encara incerta. Reviseu la previsió més a prop de la data.",
            "subthreshold": "🟡 {label}: s'espera o s'ha observat un període humit, però el model no indica una nova infecció. Manteniu la inspecció rutinària.",
            "known_inoculum": "🟡 {label}: no es preveu una nova infecció meteorològica, però el black rot de la vinya ja s'ha confirmat al camp. Reviseu les zones amb símptomes coneguts.",
            "not_reported": "ℹ️ {label}: avui el model no dona cap senyal meteorològic i l'inòcul de Guignardia bidwellii no s'ha verificat al camp.",
            "unknown_inoculum": "ℹ️ {label}: avui el model no dona cap senyal meteorològic i l'inòcul de Guignardia bidwellii no s'ha verificat al camp.",
            "confirmation": " Senyal meteorològic no confirmat: responeu després de la inspecció amb «símptomes compatibles», «cap símptoma» o «fals avís» perquè el sistema incorpori el resultat.",
            "low": "🟢 {label}: no hi ha condicions actuals ni previstes d'infecció. Manteniu la inspecció rutinària.",
            "unknown": " No sabem si hi ha inòcul al camp; és una alerta meteorològica, no una infecció confirmada.",
            "decision": "Decisió de tractament: no tracteu només per aquesta previsió. Confirmeu fulla mullada o símptomes i reviseu l'última protecció abans de decidir.",
            "scope": "Abast: només black rot de la vinya per Guignardia bidwellii; no inclou les podridures secundàries del raïm per Aspergillus, Penicillium o altres fongs oportunistes.",
        },
        "es": {
            "title": "🍇 Black rot de la vid (Guignardia bidwellii)",
            "date": "Fecha",
            "current_humidity": "🔴 {label}: posible ventana de infección hoy tras una noche muy húmeda. Compruebe si las hojas han quedado mojadas e inspeccione el campo hoy.",
            "current_wet": "🔴 {label}: las condiciones de humedad pueden haber permitido una infección hoy. Inspeccione el campo y revise la protección reciente.",
            "current_uncertain": "🟠 {label}: puede haber rocío u hoja mojada que la estación no confirma. Inspeccione hoy las zonas más húmedas.",
            "near_humidity": "🟠 {label}: riesgo elevado el {event} por humedad nocturna muy alta. Es una alerta meteorológica, no una infección confirmada. Compruebe la humedad real del dosel e inspeccione antes de decidir un tratamiento.",
            "near_rain": "🟠 {label}: la lluvia puede abrir una ventana de infección el {event}. Revise el campo y la protección antes de ese día.",
            "later_humidity": "🟡 {label}: posible ventana de infección hacia el {event} si las noches siguen muy húmedas. No hace falta actuar ahora; revise de nuevo la predicción 48 horas antes.",
            "later_rain": "🟡 {label}: posible ventana de infección hacia el {event} asociada a lluvia. No hace falta actuar ahora; revise de nuevo la predicción 48 horas antes.",
            "near_uncertain": "🟡 {label}: el {event} podría haber rocío u hoja mojada, pero ningún sensor lo confirma. Inspeccione brevemente las zonas húmedas.",
            "later_uncertain": "🟡 {label}: posible humectación hacia el {event}, todavía incierta. Revise la predicción más cerca de la fecha.",
            "subthreshold": "🟡 {label}: se espera o se ha observado un periodo húmedo, pero el modelo no indica una infección nueva. Mantenga la inspección rutinaria.",
            "known_inoculum": "🟡 {label}: no se prevé una nueva infección meteorológica, pero el black rot de la vid ya se ha confirmado en el campo. Revise las zonas con síntomas conocidos.",
            "not_reported": "ℹ️ {label}: hoy el modelo no emite una señal meteorológica y el inóculo de Guignardia bidwellii no se ha verificado en el campo.",
            "unknown_inoculum": "ℹ️ {label}: hoy el modelo no emite una señal meteorológica y el inóculo de Guignardia bidwellii no se ha verificado en el campo.",
            "confirmation": " Señal meteorológica no confirmada: responda después de la inspección con «síntomas compatibles», «sin síntomas» o «falsa alarma» para que el sistema incorpore el resultado.",
            "low": "🟢 {label}: no hay condiciones actuales ni previstas de infección. Mantenga la inspección rutinaria.",
            "unknown": " No sabemos si hay inóculo en el campo; es una alerta meteorológica, no una infección confirmada.",
            "decision": "Decisión de tratamiento: no trate solo por esta predicción. Confirme hoja mojada o síntomas y revise la última protección antes de decidir.",
            "scope": "Alcance: solo black rot de la vid por Guignardia bidwellii; no incluye podredumbres secundarias de la uva por Aspergillus, Penicillium u otros hongos oportunistas.",
        },
        "en": {
            "title": "🍇 Grapevine black rot (Guignardia bidwellii)",
            "date": "Date",
            "current_humidity": "🔴 {label}: a possible infection window exists today after a very humid night. Check whether leaves stayed wet and scout today.",
            "current_wet": "🔴 {label}: wet conditions may have allowed infection today. Scout the field and review recent protection.",
            "current_uncertain": "🟠 {label}: dew or leaf wetness may be present but the station cannot confirm it. Inspect the dampest areas today.",
            "near_humidity": "🟠 {label}: elevated risk on {event} from very high overnight humidity. This is a weather alert, not confirmed infection. Check actual canopy wetness and scout before any treatment decision.",
            "near_rain": "🟠 {label}: rain may open an infection window on {event}. Check the field and protection before that day.",
            "later_humidity": "🟡 {label}: a possible infection window around {event} if nights remain very humid. No action now; review the forecast again 48 hours beforehand.",
            "later_rain": "🟡 {label}: a possible rain-related infection window around {event}. No action now; review the forecast again 48 hours beforehand.",
            "near_uncertain": "🟡 {label}: dew or leaf wetness may occur on {event}, but no sensor confirms it. Briefly inspect damp areas.",
            "later_uncertain": "🟡 {label}: possible wetness around {event}, still uncertain. Review the forecast closer to the date.",
            "subthreshold": "🟡 {label}: a wet period is expected or observed, but the model does not indicate a new infection. Continue routine scouting.",
            "known_inoculum": "🟡 {label}: no new weather-driven infection is forecast, but black rot is already present. Check areas with known symptoms.",
            "not_reported": "ℹ️ {label}: the model gives no weather signal today and Guignardia bidwellii inoculum has not been verified in the field.",
            "unknown_inoculum": "ℹ️ {label}: the model gives no weather signal today and Guignardia bidwellii inoculum has not been verified in the field.",
            "confirmation": " Unconfirmed weather signal: reply after scouting with 'compatible symptoms', 'no symptoms', or 'false alarm' so the system can incorporate the result.",
            "low": "🟢 {label}: no current or forecast infection conditions. Continue routine scouting.",
            "unknown": " Local inoculum is unknown; this is a weather alert, not confirmed infection.",
            "decision": "Treatment decision: do not treat from this forecast alone. Confirm wet leaves or symptoms and review the last protection before deciding.",
            "scope": "Scope: grapevine black rot caused by Guignardia bidwellii only; secondary bunch rots caused by Aspergillus, Penicillium, or other opportunistic fungi are not included.",
        },
    }[language_code]

    lines = [copy["title"]]
    if day:
        lines.append(f"{copy['date']}: {day}")
    for report in successful:
        latest = report.get("latest") or {}
        forecast = report.get("forecast_prediction") or {}
        label = report.get("field_label") or report.get("field")
        index = float(latest.get("black_rot_infection_index") or 0.0)
        first_event = str(forecast.get("first_infection_day") or "")[:10]
        first_uncertain = str(forecast.get("first_uncertain_watch_day") or "")[:10]
        inoculum = latest.get("black_rot_inoculum_status") or "unknown"
        current_humidity = latest.get("black_rot_wetness_driver") == "humidity"
        forecast_humidity = forecast_event_evidence(forecast) == "humidity_proxy"
        forecast_rain = (
            forecast.get("wetness_driver") == "rain"
            or float(forecast.get("rain_wet_hours") or 0.0) > 0.0
        )
        current_uncertain = wetness_uncertain_watch(latest)
        subthreshold = subthreshold_wetness_state(latest, forecast)
        has_model_signal = bool(
            index >= 85.0 or current_uncertain or first_event or first_uncertain
        )

        if inoculum == "not_reported" and not has_model_signal:
            message = copy["not_reported"].format(label=label)
        elif inoculum != "present" and not has_model_signal:
            message = copy["unknown_inoculum"].format(label=label)
        elif index >= 85.0:
            key = "current_humidity" if current_humidity else "current_wet"
            message = copy[key].format(label=label)
        elif current_uncertain:
            message = copy["current_uncertain"].format(label=label)
        elif first_uncertain and (not first_event or first_uncertain < first_event):
            days = _days_between(day, first_uncertain)
            key = "near_uncertain" if days is None or days <= 2 else "later_uncertain"
            message = copy[key].format(label=label, event=first_uncertain)
        elif first_event:
            days = _days_between(day, first_event)
            near = days is None or days <= 2
            if forecast_humidity:
                key = "near_humidity" if near else "later_humidity"
            elif forecast_rain:
                key = "near_rain" if near else "later_rain"
            else:
                key = "near_uncertain" if near else "later_uncertain"
            message = copy[key].format(label=label, event=first_event)
        elif subthreshold:
            message = copy["subthreshold"].format(label=label)
        elif inoculum == "present":
            message = copy["known_inoculum"].format(label=label)
        else:
            message = copy["low"].format(label=label)
        if has_model_signal and inoculum != "present":
            message += copy["confirmation"]
        lines.append(message)
    lines.append(copy["decision"])
    lines.append(copy["scope"])
    return "\n".join(lines)


def main():
    params = load_params()
    mode = str(params.get("mode") or "report")
    if mode == "model_info":
        print(json.dumps({"status": "success", "mode": mode, **MODEL_INFO}, ensure_ascii=False))
        return
    repo = repo_path(params)
    days = int(params.get("days") or 31)
    fields = configured_fields(repo, str(params.get("field") or ""))
    if not fields:
        print(json.dumps({"status": "error", "error": "no matching field in agent_config.yaml"}))
        raise SystemExit(1)
    today = str(params.get("date") or params.get("end") or latest_observed_day(repo, fields))[:10]
    lang = language(repo)
    reports = []
    media = []
    multi_field = len(fields) > 1
    for field in fields:
        path = state_path(repo, field["id"])
        state = None if params.get("force_refresh") else current_state(path, today)
        update = {"ok": True, "cached": True}
        if state is None:
            update = refresh(repo, field["id"], days, today, bool(params.get("skip_forecast")))
            state = current_state(path, today)
        if state is None:
            reports.append({"field": field["id"], "status": "error", "refresh": update})
            continue
        label = field_label(field, multi_field=multi_field)
        text = message_for(field, state, lang, label=label)
        plot = state.get("plot_path")
        item = {
            "type": "photo", "path": plot, "source_path": plot,
            "caption": text.splitlines()[0], "mime_type": "image/png",
            "exists": bool(plot and os.path.exists(plot)), "disease": "black_rot",
            "field": field["id"],
        }
        media.append(item)
        reports.append({
            "field": field["id"], "status": "success", "cached": bool(update.get("cached")),
            "field_label": label,
            "send_text": text, "state_path": path, "plot_path": plot,
            "latest": state.get("latest"), "forecast_prediction": state.get("forecast_prediction"),
        })
    successes = [report for report in reports if report.get("status") == "success"]
    combined = "\n\n".join(report["send_text"] for report in successes)
    daily_summary = daily_summary_for(reports, lang)
    primary = media[0]["path"] if media else ""
    result = {
        "status": "success" if len(successes) == len(fields) else "partial" if successes else "error",
        "mode": mode,
        "disease": "black_rot",
        "fields": [field["id"] for field in fields],
        "language": lang,
        "field_reports": reports,
        "daily_summary": daily_summary,
        "send_text": combined,
        "send_photo_path": primary,
        "send_image_path": primary,
        "attachments": media,
        "media": media,
        "telegram": {
            "method": "sendMediaGroup" if len(media) > 1 else "sendPhoto" if primary else "sendMessage",
            "photo": primary,
            "caption": "🍇 Grapevine black rot (Guignardia bidwellii)",
            "text_after_photo": combined,
            "media": media,
        },
        "must_attach_image": bool(media),
        "must_send_text": bool(combined),
        "must_send_exactly": True,
        "model_info": MODEL_INFO,
    }
    print(json.dumps(result, ensure_ascii=False))
    if not successes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
