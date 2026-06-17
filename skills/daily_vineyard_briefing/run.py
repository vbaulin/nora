#!/usr/bin/env python3
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import re


LANGUAGE_ALIASES = {
    "ca": "ca",
    "cat": "ca",
    "catalan": "ca",
    "català": "ca",
    "catalan_ca": "ca",
    "en": "en",
    "eng": "en",
    "english": "en",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "castellano": "es",
    "castellà": "es",
}


def normalize_language(value):
    value = str(value or "").strip().lower().replace("-", "_")
    return LANGUAGE_ALIASES.get(value, value if value in {"ca", "en", "es"} else "")


def load_agent_config(repo_path):
    config_path = os.path.join(repo_path or "/root/.picoclaw/workspace/goidanich", "agent_config.yaml")
    try:
        import yaml
        return yaml.safe_load(open(config_path, encoding="utf-8")) or {}
    except Exception:
        return {}


def preferred_language(repo_path, field_id="", params=None):
    params = params or {}
    explicit = normalize_language(params.get("language") or os.environ.get("SKILL_LANGUAGE"))
    if explicit:
        return explicit
    config = load_agent_config(repo_path)
    for field in config.get("fields") or []:
        if field.get("id") == field_id:
            language = normalize_language(
                field.get("preferred_language")
                or (field.get("metadata") or {}).get("preferred_language")
                or field.get("language")
                or (field.get("metadata") or {}).get("language")
            )
            if language:
                return language
    board = config.get("board") or {}
    language = normalize_language(board.get("preferred_language") or board.get("language"))
    if language:
        return language
    notifications = config.get("notifications") or {}
    language = normalize_language(notifications.get("preferred_language") or notifications.get("language"))
    if language:
        return language
    return "en"


CA_REPLACEMENTS = [
    ("Vineyard treatment watch", "Seguiment de tractament de la vinya"),
    ("Vineyard risk overview", "Resum general del risc de la vinya"),
    ("Vineyard risk report", "Informe de risc de la vinya"),
    ("Vineyard risk summary", "Resum de risc de la vinya"),
    ("Vineyard disease report", "Informe de malalties de la vinya"),
    ("Downy Mildew", "Míldiu"),
    ("Powdery Mildew", "Oïdi"),
    ("Powdery mildew is the active issue", "L'oïdi és el problema actiu"),
    ("Downy mildew remains low", "El míldiu es manté baix"),
    ("Downy mildew today", "Míldiu avui"),
    ("Powdery mildew today", "Oïdi avui"),
    ("Downy mildew", "Míldiu"),
    ("Powdery mildew", "Oïdi"),
    ("Downy signal", "Senyal de míldiu"),
    ("Powdery signal", "Senyal d'oïdi"),
    ("Downy:", "Míldiu:"),
    ("Powdery:", "Oïdi:"),
    ("Signal:", "Senyal:"),
    ("NO DOWNY ALERT: Goidanich/Rossi are low for this field; continue normal scouting.",
     "SENSE ALERTA DE MILDIU: Goidanich/Rossi són baixos per a aquest camp; continueu la inspecció normal."),
    ("DOWNY WATCH: inspect during the forecast watch window and check protection status.",
     "VIGILANCIA DE MILDIU: inspeccioneu durant la finestra de vigilància prevista i comproveu l'estat de protecció."),
    ("DOWNY ALERT: inspect before the forecast/current high-risk window; treat only after scouting and protection-record check.",
     "ALERTA DE MILDIU: inspeccioneu abans de la finestra prevista/actual d'alt risc; tracteu només després d'inspecció i comprovació del registre de protecció."),
    ("NO DOWNY ALERT", "SENSE ALERTA DE MILDIU"),
    ("DOWNY WATCH", "VIGILANCIA DE MILDIU"),
    ("DOWNY ALERT", "ALERTA DE MILDIU"),
    ("CHECK PROTECTION", "COMPROVAR PROTECCIÓ"),
    ("PROTECT DECISION: inspect now. Apply protection only if cover is missing/expired or powdery mildew is confirmed.",
     "DECISIÓ DE PROTECCIÓ: inspeccioneu ara. Apliqueu protecció només si la cobertura falta, ha caducat o es confirma oïdi."),
    ("WATCH: inspect within 24-48h and check treatment records before deciding on protection.",
     "VIGILAR: inspeccioneu en 24-48 h i reviseu els registres de tractament abans de decidir sobre la protecció."),
    ("PROTECT DECISION", "DECISIÓ DE PROTECCIÓ"),
    ("WATCH NOW", "VIGILAR ARA"),
    ("WATCH", "VIGILAR"),
    ("MONITOR", "MONITORAR"),
    ("Date:", "Data:"),
    ("Station:", "Estació:"),
    ("Variety:", "Varietat:"),
    ("Forecast window:", "Finestra de previsió:"),
    ("Weather window:", "Finestra meteorològica:"),
    ("Weather forecast:", "Previsió meteorològica:"),
    ("Forecast rain:", "Pluja prevista:"),
    ("Future action:", "Acció futura:"),
    ("Advice:", "Consell:"),
    ("Problem:", "Problema:"),
    ("Plots:", "Gràfics:"),
    ("Disease forecast:", "Previsió de malaltia:"),
    ("Downy daily disease forecast", "Previsió diària de míldiu"),
    ("Powdery UC disease forecast", "Previsió UC d'oïdi"),
    ("Forecast prediction", "Previsió de malaltia"),
    ("Goidanich daily risk", "Risc diari Goidanich"),
    ("Goidanich daily", "Goidanich diari"),
    ("Rossi state/risk", "Estat/risc Rossi"),
    ("Powdery UC risk", "Risc UC d'oïdi"),
    ("Powdery UC", "UC d'oïdi"),
    ("UC risk", "risc UC"),
    ("PMI", "PMI"),
    ("Field-specific learned model: not trained yet; using original Goidanich/Rossi layers.",
     "El model après específic del camp encara no està entrenat; s'utilitzen les capes originals Goidanich/Rossi."),
    ("forecast weather-suitability for UC powdery mildew", "idoneïtat meteorològica prevista per a l'oïdi UC"),
    ("watch context, not a continuation of today's UC risk", "context de vigilància, no una continuació del risc UC d'avui"),
    ("watch context, not a continuation of today's risc UC", "context de vigilància, no una continuació del risc UC d'avui"),
    ("forecast daily-risk line", "línia prevista de risc diari"),
    ("forecast curve, not today's risk", "corba de previsió, no el risc d'avui"),
    ("forecast peaks at", "el pic previst és"),
    ("inspect before the forecast risk date and verify protection; no automatic treatment.",
     "inspeccionar abans de la data de risc prevista i verificar la protecció; no hi ha tractament automàtic."),
    ("inspect now; apply protection only if cover is missing/expired or powdery mildew is confirmed.",
     "inspeccioneu ara; apliqueu protecció només si la cobertura falta, ha caducat o es confirma oïdi."),
    ("inspect leaves and bunch zone and verify sulfur/protection cover",
     "inspeccionar fulles i zona de raïms i verificar la cobertura de sofre/protecció"),
    ("check canopy infection symptoms and protection status",
     "revisar símptomes d'infecció al dosser i l'estat de protecció"),
    ("inspect within 24-48h and check recent protection before deciding",
     "inspeccioneu en 24-48 h i comproveu la protecció recent abans de decidir"),
    ("inspect within 24-48h and check treatment records before deciding on protection.",
     "inspeccioneu en 24-48 h i reviseu els registres de tractament abans de decidir sobre la protecció."),
    ("normal scouting; no powdery action from the model",
     "inspecció normal; el model no indica cap acció contra l'oïdi"),
    ("mostly dry; do not treat from rain pressure alone, but keep the forecast-risk scouting date.",
     "majoritàriament sec; no tractar només per pressió de pluja, però mantenir la data d'inspecció pel risc previst."),
    ("the forecast is mostly dry, so there is no rain-driven treatment trigger.",
     "la previsió és majoritàriament seca, per tant no hi ha activador de tractament per pluja."),
    ("check cover before the wet period and scout after it.",
     "comprovar la cobertura abans del període humit i inspeccionar després."),
    ("Decision rule: treatment is not automatic; act only after scouting and recent protection history.",
     "Regla de decisió: el tractament no és automàtic; actuar només després d'inspecció i historial recent de protecció."),
    ("Please confirm after scouting: clean canopy, mildew detected, false alarm, or treatment applied. If treated, include product, dose, water volume, area, method, and date.",
     "Confirmeu després de la inspecció: dosser net, míldiu detectat, falsa alarma o tractament aplicat. Si s'ha tractat, incloeu producte, dosi, volum d'aigua, àrea, mètode i data."),
    ("Please confirm after scouting: clean canopy, powdery mildew detected, or protection already applied. If protection was applied, include product, dose, water volume, treated area, method, and date.",
     "Confirmeu després de la inspecció: dosser net, oïdi detectat o protecció ja aplicada. Si s'ha aplicat protecció, incloeu producte, dosi, volum d'aigua, àrea tractada, mètode i data."),
    ("No treatment record is stored for this field. Please confirm recent applications.",
     "No hi ha cap registre de tractament per a aquest camp. Confirmeu les aplicacions recents."),
    ("Reply with scouting result or treatment details: product, dose, water volume, area, method, and date.",
     "Responeu amb el resultat de la inspecció o els detalls del tractament: producte, dosi, volum d'aigua, àrea, mètode i data."),
    ("No field has a forecast or current risk alert today.",
     "Avui cap camp té alerta de risc actual o prevista."),
    ("No alert among refreshed fields; some fields are not refreshed yet.",
     "No hi ha cap alerta entre els camps actualitzats; alguns camps encara no s'han actualitzat."),
    ("Fields not refreshed yet:", "Camps encara no actualitzats:"),
    ("not refreshed", "no actualitzats"),
    ("Action: routine scouting only; no forecast-driven treatment preparation from the model.",
     "Acció: només inspecció rutinària; el model no demana preparar tractament per la previsió."),
    ("No high-risk alert. Continue normal monitoring.",
     "Sense alerta d'alt risc. Continueu el seguiment normal."),
    ("No alt-risk alert. Continue normal monitoring.",
     "Sense alerta de risc alt. Continueu el seguiment normal."),
    ("No powdery protection check from PMI/UC model; continue monitoring.",
     "El model PMI/UC no demana comprovació de protecció contra l'oïdi; continueu monitorant."),
    ("No powdery protection check", "Sense comprovació de protecció contra l'oïdi"),
    ("first sulfur/protection check due", "primera comprovació de sofre/protecció pendent"),
    ("risc UC is baix; verify first sulfur/protection record, no treatment from risk alone",
     "el risc UC és baix; verifiqueu el primer registre de sofre/protecció, sense tractament només pel risc"),
    ("risc UC is low", "el risc UC és baix"),
    ("risc UC is moderate", "el risc UC és moderat"),
    ("risc UC is high", "el risc UC és alt"),
    ("risc UC is baix", "el risc UC és baix"),
    ("UC risk", "risc UC"),
    ("protection check due", "comprovació de protecció pendent"),
    ("downy and powdery plots were generated for each alert field",
     "s'han generat gràfics de míldiu i oïdi per a cada camp amb alerta"),
    ("Telegram sent this compact overview only to avoid flooding",
     "Telegram ha enviat només aquest resum compacte per evitar massa missatges"),
    ("representative downy and powdery plots are attached for",
     "s'adjunten gràfics representatius de míldiu i oïdi per a"),
    ("plots were generated for each alert field",
     "s'han generat gràfics per a cada camp amb alerta"),
    ("Reply with", "Responeu amb"),
    ("' or '", "' o '"),
    ("to receive both disease plots for one field", "per rebre els dos gràfics de malaltia d'un camp"),
    ("downy and powdery plots are attached for the alert field(s)",
     "els gràfics de míldiu i oïdi estan adjunts per als camps amb alerta"),
    ("verify first sulfur/protection record", "verifiqueu el primer registre de sofre/protecció"),
    ("no treatment from risk alone", "sense tractament només pel risc"),
    ("protection check", "comprovació de protecció"),
    ("action:", "acció:"),
    ("continue normal scouting", "continueu la inspecció normal"),
    ("continue routine scouting", "continueu la inspecció rutinària"),
    ("continue monitoring", "continueu monitorant"),
    ("not available", "no disponible"),
    ("not due", "no pendent"),
    ("due", "pendent"),
    ("HIGH", "ALT"),
    ("LOW", "BAIX"),
    ("Fields needing attention:", "Camps que necessiten atenció:"),
    ("Other fields without alerts:", "Altres camps sense alertes:"),
    ("Other fields:", "Altres camps:"),
    ("without alerts", "sense alertes"),
    ("with alerts", "amb alertes"),
    ("routine scouting", "inspecció rutinària"),
    ("no automatic treatment", "sense tractament automàtic"),
    ("treatment is not automatic", "el tractament no és automàtic"),
    ("Treatment outlook:", "Perspectiva de tractament:"),
    ("tractament automàtic signal", "senyal automàtic de tractament"),
    ("use scouting and recent treatment history before applying anything.",
     "useu la inspecció i l'historial recent de tractament abans d'aplicar res."),
    ("Use scouting and the protection record before deciding.",
     "Useu la inspecció i el registre de protecció abans de decidir."),
    ("before deciding", "abans de decidir"),
    ("treatment signal", "senyal de tractament"),
    ("Treatment outlook: the forecast is mostly dry, so there is no rain-driven treatment trigger. Use scouting and the protection record before deciding.",
     "Perspectiva de tractament: la previsió és majoritàriament seca, per tant no hi ha activador de tractament per pluja. Useu la inspecció i el registre de protecció abans de decidir."),
    ("Treatment outlook: dry forecast and low current models; no immediate treatment signal, keep normal scouting.",
     "Perspectiva de tractament: previsió seca i models actuals baixos; sense senyal immediat de tractament, manteniu la inspecció normal."),
    ("Today's cached vineyard report is not available yet for this field/disease. The board should refresh it in the scheduled daily field jobs.",
     "L'informe en memòria cau d'avui encara no està disponible per a aquest camp/malaltia. La placa l'hauria d'actualitzar en les tasques diàries programades per camp."),
    ("Today's vineyard cache is incomplete for:", "La memòria cau de la vinya d'avui és incompleta per a:"),
    ("Scheduled single-field refresh jobs run before the daily Telegram summary.",
     "Les tasques programades d'actualització per camp s'executen abans del resum diari de Telegram."),
    ("Today's vineyard cache is incomplete. Scheduled single-field refresh jobs should rebuild it.",
     "La memòria cau de la vinya d'avui és incompleta. Les tasques programades per camp l'haurien de reconstruir."),
    ("Treatment outlook: no automatic treatment signal; use scouting and recent treatment history before applying anything.",
     "Perspectiva de tractament: sense senyal automàtic de tractament; useu la inspecció i l'historial recent abans d'aplicar res."),
    ("Treatment is never automatic: confirm canopy state, recent protection, and scouting observations before action.",
     "El tractament no és mai automàtic: confirmeu l'estat del dosser, la protecció recent i les observacions d'inspecció abans d'actuar."),
    ("PMI is a protection-clock reminder, not a disease-probability alert. Because risc UC is baix, check canopy and recent protection; do not treat automatically.",
     "El PMI és un recordatori del rellotge de protecció, no una alerta de probabilitat de malaltia. Com que el risc UC és baix, reviseu el dosser i la protecció recent; no tracteu automàticament."),
    ("PMI is a protection-clock reminder, not a disease-probability alert. Because risc UC is low, check canopy and recent protection; do not treat automatically.",
     "El PMI és un recordatori del rellotge de protecció, no una alerta de probabilitat de malaltia. Com que el risc UC és baix, reviseu el dosser i la protecció recent; no tracteu automàticament."),
    ("PMI is a protection-clock reminder, not a disease-probability alert. Because UC risk is low, check canopy and recent protection; do not treat automatically.",
     "El PMI és un recordatori del rellotge de protecció, no una alerta de probabilitat de malaltia. Com que el risc UC és baix, reviseu el dosser i la protecció recent; no tracteu automàticament."),
    ("Forecast", "Previsió"),
    ("Guidance", "Guia"),
    ("Clarification", "Aclariment"),
    ("Plots are attached.", "Els gràfics estan adjunts."),
    ("substantial", "important"),
    ("very little", "molt lleu"),
    ("light", "lleuger"),
    ("low", "baix"),
    ("moderate", "moderat"),
    ("high", "alt"),
]


def localize_text(text, language):
    if normalize_language(language) != "ca" or not text:
        return text
    out = str(text)
    for source, target in CA_REPLACEMENTS:
        out = out.replace(source, target)
    out = re.sub(
        r"Checked (\d+) field(s?): (\d+) amb alertes, (\d+) sense alertes, (\d+) no actualitzats\.",
        lambda m: (
            f"S'han revisat {m.group(1)} camp{'s' if m.group(1) != '1' else ''}: "
            f"{m.group(3)} amb alertes, {m.group(4)} sense alertes, {m.group(5)} no actualitzats."
        ),
        out,
    )
    out = re.sub(
        r"Checked (\d+) field(s?): (\d+) amb alertes, (\d+) sense alertes\.",
        lambda m: f"S'han revisat {m.group(1)} camp{'s' if m.group(1) != '1' else ''}: {m.group(3)} amb alertes, {m.group(4)} sense alertes.",
        out,
    )
    out = re.sub(r"\bon (\d{4}-\d{2}-\d{2})", r"el \1", out)
    out = re.sub(r"\breaches ([0-9.]+%) el (\d{4}-\d{2}-\d{2})", r"arriba a \1 el \2", out)
    out = re.sub(r"\bis ([0-9.]+%) el (\d{4}-\d{2}-\d{2}) and", r"és \1 el \2 i", out)
    out = re.sub(r"\bbefore (\d{4}-\d{2}-\d{2})", r"abans del \1", out)
    out = re.sub(r"\bstarting around (\d{4}-\d{2}-\d{2})", r"comencant aproximadament el \1", out)
    out = re.sub(
        r"Finestra de previsió: (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})\.",
        r"Finestra de previsió: del \1 al \2.",
        out,
    )
    out = re.sub(
        r"Previsió meteorològica: temp ([0-9.]+)-([0-9.]+) C \(avg ([0-9.]+) C\), humidity avg ([0-9.]+)%, rain total ([0-9.]+) mm\.",
        r"Previsió meteorològica: temperatura \1-\2 C (mitjana \3 C), humitat mitjana \4%, pluja total \5 mm.",
        out,
    )
    out = re.sub(
        r"Previsió meteorològica: temp ([0-9.]+)-([0-9.]+) C \(avg ([0-9.]+) C\), rain total ([0-9.]+) mm\.",
        r"Previsió meteorològica: temperatura \1-\2 C (mitjana \3 C), pluja total \4 mm.",
        out,
    )
    out = re.sub(
        r"Pluja prevista: ([0-9.]+) mm total over 15 days \(([0-9.]+) mm in the next 5 days, first wet day ([0-9-]+); ([^)]+) event\)\.",
        lambda m: (
            f"Pluja prevista: {m.group(1)} mm totals en 15 dies "
            f"({m.group(2)} mm en els pròxims 5 dies, primer dia humit {m.group(3)}; "
            f"episodi {localize_text(m.group(4), 'ca')})."
        ),
        out,
    )
    out = re.sub(
        r"Pluja prevista: ([0-9.]+) mm total over 15 days \(([0-9.]+) mm in the next 5 days; dry window\)\.",
        r"Pluja prevista: \1 mm totals en 15 dies (\2 mm en els pròxims 5 dies; finestra seca).",
        out,
    )
    out = re.sub(
        r"Previsió diària de míldiu: (ALT|VIGILAR|BAIX); first >=([0-9]+)% el ([0-9-]+); maximum ([0-9.]+%) el ([0-9-]+)\.",
        r"Previsió diària de míldiu: \1; primer dia amb >=\2% el \3; màxim \4 el \5.",
        out,
    )
    out = re.sub(
        r"Previsió UC d'oïdi: (ALT|VIGILAR|BAIX); first >=([0-9]+)% el ([0-9-]+); maximum ([0-9.]+%) el ([0-9-]+)\.",
        r"Previsió UC d'oïdi: \1; primer dia amb >=\2% el \3; màxim \4 el \5.",
        out,
    )
    out = re.sub(
        r"(Previsió diària de míldiu|Previsió UC d'oïdi): (ALT|VIGILAR|BAIX); maximum ([0-9.]+%) el ([0-9-]+)\.",
        r"\1: \2; màxim \3 el \4.",
        out,
    )
    return out


def localize_value(value, language):
    if isinstance(value, str):
        return localize_text(value, language)
    return value


def localize_media(media, language):
    localized = []
    for item in media or []:
        if isinstance(item, dict):
            item = dict(item)
            item["caption"] = localize_text(item.get("caption", ""), language)
        localized.append(item)
    return localized


def configured_fields(repo_path):
    config_path = os.path.join(repo_path, "agent_config.yaml")
    try:
        import yaml
        config = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
        fields = config.get("fields") or []
        return [field.get("id") for field in fields if field.get("id")]
    except Exception:
        try:
            text = open(config_path, encoding="utf-8").read()
        except Exception:
            return []
        ids = []
        in_fields = False
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped == "fields:":
                in_fields = True
                continue
            if in_fields:
                match = re.match(r"-\s+id:\s*['\"]?([^'\"]+)['\"]?", stripped)
                if match:
                    ids.append(match.group(1).strip())
                elif stripped and not raw.startswith(" ") and not stripped.startswith("-"):
                    break
        return ids


def configured_field_label(repo_path, field_id):
    config_path = os.path.join(repo_path or "/root/.picoclaw/workspace/goidanich", "agent_config.yaml")
    try:
        import yaml
        config = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
        for field in config.get("fields") or []:
            if field.get("id") == field_id:
                return field.get("name") or field.get("location") or field_id
    except Exception:
        pass
    try:
        text = open(config_path, encoding="utf-8").read()
    except Exception:
        return field_id
    in_target = False
    found = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        match = re.match(r"-\s+id:\s*['\"]?([^'\"]+)['\"]?", stripped)
        if match:
            in_target = match.group(1).strip() == field_id
            found = {}
            continue
        if in_target:
            kv = re.match(r"(name|location):\s*['\"]?([^'\"]+)['\"]?", stripped)
            if kv:
                found[kv.group(1)] = kv.group(2).strip()
            elif stripped and not raw.startswith(" ") and not stripped.startswith("-"):
                break
    return found.get("name") or found.get("location") or field_id


def short_caption(title, message, limit=900):
    lines = [line.strip("# ").strip() for line in str(message or "").splitlines() if line.strip()]
    selected = [str(title or "Vineyard disease report")]
    for line in lines:
        if line == selected[0]:
            continue
        candidate = "\n".join(selected + [line])
        if len(candidate) > limit:
            break
        selected.append(line)
        if len(selected) >= 8:
            break
    return "\n".join(selected).strip()[:limit].rstrip()


def telegram_plain_id(value):
    return str(value or "").replace("_", "\\_")


def field_is_explicitly_mentioned(repo_path, text, field_id):
    if not field_id or not text:
        return False
    lower = str(text).lower()
    field_lower = str(field_id).lower()
    if field_lower in lower:
        return True
    label = configured_field_label(repo_path, field_id)
    label_lower = str(label or "").lower()
    if label_lower and label_lower != field_lower and label_lower in lower:
        return True
    return False


def unique_by_path(items):
    unique = []
    seen = set()
    for item in items or []:
        path = str((item or {}).get("path") or (item or {}).get("source_path") or "")
        key = path or json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def append_unique_text(parts, text):
    text = (text or "").strip()
    if not text:
        return
    if text in parts:
        return
    parts.append(text)


def field_ok_line(repo_path, field, report=None):
    label = configured_field_label(repo_path, field)
    summaries = []
    if isinstance(report, dict):
        summaries = report.get("reports") or []
    day = ""
    station = ""
    downy = {}
    powdery = {}
    for item in summaries:
        if not isinstance(item, dict):
            continue
        if item.get("disease") == "downy_mildew":
            downy = item
        elif item.get("disease") == "powdery_mildew":
            powdery = item
    day = downy.get("date") or powdery.get("date") or ""
    station = downy.get("station") or powdery.get("station") or ""
    detail = []
    if downy:
        detail.append(f"downy {format_percent(downy.get('goidanich_daily_risk'))}")
    if powdery:
        detail.append(f"powdery {format_percent(powdery.get('powdery_uc_risk'))}")
    suffix = f" ({', '.join(detail)})" if detail else ""
    date_part = f" on {day}" if day else ""
    station_part = f", station {station}" if station else ""
    return f"OK: {label}{date_part}{station_part}{suffix}."


def field_report_summaries(report):
    if isinstance(report, dict) and isinstance(report.get("reports"), list):
        return [item for item in report.get("reports") if isinstance(item, dict)]
    if isinstance(report, dict):
        summary = compact_report_summary(report)
        return [summary] if summary else []
    return []


def field_report_day(report):
    for item in field_report_summaries(report):
        day = str(item.get("date") or "")[:10]
        if day:
            return day
    return ""


def numeric_summary(items, key, percent=True):
    values = []
    for item in items or []:
        try:
            values.append(float(item.get(key)))
        except Exception:
            pass
    if not values:
        return ""
    low = min(values)
    high = max(values)
    def render(value):
        return format_percent(value) if percent else f"{value:.1f}"

    if abs(low - high) < 0.05:
        return render(high)
    return f"{render(low)}-{render(high)}"


def fleet_problem_lines(repo_path, alert_field_reports):
    summaries = []
    for report in alert_field_reports or []:
        summaries.extend(field_report_summaries(report))
    downy = [item for item in summaries if item.get("disease") == "downy_mildew"]
    powdery = [item for item in summaries if item.get("disease") == "powdery_mildew"]
    lines = []
    if powdery:
        powdery_risk = numeric_summary(powdery, "powdery_uc_risk")
        pmi = numeric_summary(powdery, "powdery_pmi", percent=False)
        pmi_due = any(bool(item.get("powdery_pmi_treatment_due")) for item in powdery)
        detail = []
        if powdery_risk:
            detail.append(f"UC risk {powdery_risk}")
        if pmi:
            detail.append(f"PMI {pmi}")
        if pmi_due:
            detail.append("protection check due")
        if detail:
            lines.append("Problem: Powdery mildew is the active issue: " + ", ".join(detail) + ".")
    if downy:
        goidanich = numeric_summary(downy, "goidanich_daily_risk")
        rossi = numeric_summary(downy, "rossi_risk")
        if goidanich or rossi:
            lines.append(
                "Downy mildew remains low: "
                + ", ".join(
                    part
                    for part in [
                        f"Goidanich daily {goidanich}" if goidanich else "",
                        f"Rossi {rossi}" if rossi else "",
                    ]
                    if part
                )
                + "."
            )
    forecast_messages = []
    for item in powdery + downy:
        message = item.get("forecast_prediction_message")
        if message and message not in forecast_messages:
            forecast_messages.append(message)
    if forecast_messages:
        lines.append("Disease forecast: " + " | ".join(forecast_messages[:2]))
    if summaries:
        lines.append(rain_window_text(summaries))
        lines.append(treatment_readiness_message(summaries))
    if len(alert_field_reports or []) > 2:
        sample_label = configured_field_label(repo_path, alert_field_reports[0].get("field"))
        lines.append(
            f"Plots: representative downy and powdery plots are attached for {sample_label}; "
            "plots were generated for each alert field. "
            f"Reply with 'plots {sample_label}' or 'full report {sample_label}' to receive both disease plots for one field."
        )
    elif alert_field_reports:
        lines.append("Plots: downy and powdery plots are attached for the alert field(s).")
    return lines


def fleet_overview_message(repo_path, fields, alert_field_reports, ok_field_reports, missing_field_reports=None):
    missing_field_reports = missing_field_reports or []
    total = len(fields)
    alert_count = len(alert_field_reports)
    ok_count = len(ok_field_reports)
    missing_count = len(missing_field_reports)
    day = next((field_report_day(report) for report in alert_field_reports + ok_field_reports + missing_field_reports if field_report_day(report)), "")
    lines = ["🍇 Vineyard risk overview"]
    if day:
        lines.append(f"Date: {day}")
    status_parts = [
        f"{alert_count} with alerts",
        f"{ok_count} without alerts",
    ]
    if missing_count:
        status_parts.append(f"{missing_count} not refreshed")
    lines.append(f"Checked {total} field{'s' if total != 1 else ''}: " + ", ".join(status_parts) + ".")
    if alert_field_reports:
        alert_names = [configured_field_label(repo_path, report.get("field")) for report in alert_field_reports]
        lines.append("Fields needing attention: " + ", ".join(alert_names) + ".")
        lines.extend(fleet_problem_lines(repo_path, alert_field_reports))
        if ok_count:
            if ok_count <= 6:
                ok_names = [configured_field_label(repo_path, report.get("field")) for report in ok_field_reports]
                lines.append("Other fields without alerts: " + ", ".join(ok_names) + ".")
            else:
                lines.append(f"Other fields: {ok_count} without alerts; keep routine scouting.")
        if missing_count:
            missing_names = [configured_field_label(repo_path, report.get("field")) for report in missing_field_reports]
            if missing_count <= 6:
                lines.append("Fields not refreshed yet: " + ", ".join(missing_names) + ".")
            else:
                lines.append(f"Fields not refreshed yet: {missing_count}.")
    else:
        if missing_count:
            missing_names = [configured_field_label(repo_path, report.get("field")) for report in missing_field_reports]
            lines.append("No alert among refreshed fields; some fields are not refreshed yet.")
            if missing_count <= 6:
                lines.append("Fields not refreshed yet: " + ", ".join(missing_names) + ".")
        else:
            lines.append("No field has a forecast or current risk alert today.")
        if total and not missing_count:
            lines.append("Action: routine scouting only; no forecast-driven treatment preparation from the model.")
    return "\n".join(lines)


def compact_field_report(report):
    if not isinstance(report, dict):
        return {}
    return {
        "field": report.get("field"),
        "status": report.get("status"),
        "has_alert": bool(report.get("has_alert")),
        "alert_diseases": report.get("alert_diseases") or [],
        "reports": field_report_summaries(report),
    }


def report_has_incomplete_cache(report):
    if not isinstance(report, dict):
        return True
    if report.get("status") in {"cache_missing", "partial", "error"}:
        return True
    for item in report.get("reports") or []:
        if item.get("status") in {"cache_missing", "partial", "error"}:
            return True
    return False


def cache_incomplete_message(repo_path, missing_fields, language):
    labels = [configured_field_label(repo_path, field) for field in missing_fields]
    if labels:
        message = (
            "Today's vineyard cache is incomplete for: "
            + ", ".join(labels)
            + ". Scheduled single-field refresh jobs run before the daily Telegram summary."
        )
    else:
        message = "Today's vineyard cache is incomplete. Scheduled single-field refresh jobs should rebuild it."
    return localize_text(message, language)


def call_skill(skill, payload, timeout=300):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_dir = os.path.join(base, skill)
    md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(md):
        return {"status": "error", "message": f"skill missing: {skill}"}
    text = open(md, encoding="utf-8").read()
    input_fmt = "env"
    match = re.search(r"^input_format:\s*([A-Za-z0-9_-]+)", text, re.MULTILINE)
    if match:
        input_fmt = match.group(1)
    run_sh = os.path.join(skill_dir, "run.sh")
    run_py = os.path.join(skill_dir, "run.py")
    env = os.environ.copy()
    stdin = None
    if input_fmt == "env":
        for key, value in payload.items():
            env["SKILL_" + key.upper()] = str(value)
    else:
        stdin = json.dumps(payload)
    if os.path.exists(run_sh):
        proc = subprocess.run([run_sh], input=stdin, text=True, capture_output=True, timeout=timeout, env=env)
    elif os.path.exists(run_py):
        proc = subprocess.run(["python3", run_py], input=stdin, text=True, capture_output=True, timeout=timeout, env=env)
    else:
        return {"status": "error", "message": f"skill has no runner: {skill}"}
    raw = proc.stdout.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return {"status": "error", "message": raw[-1000:], "stderr": proc.stderr[-1000:], "returncode": proc.returncode}


def plot_path_from_report(report):
    result = report.get("result", report)
    if isinstance(result, dict) and isinstance(result.get("command"), dict):
        stdout = result["command"].get("stdout")
        if isinstance(stdout, dict) and stdout.get("plot"):
            return stdout["plot"]
    if isinstance(result, dict) and result.get("plot"):
        return result["plot"]
    stdout = result.get("stdout") if isinstance(result, dict) else None
    if isinstance(stdout, dict):
        plot = stdout.get("plot")
        if isinstance(plot, dict):
            for value in plot.values():
                if isinstance(value, str) and (value.endswith(".png") or value.endswith(".svg")):
                    return value
        if isinstance(plot, str) and (plot.endswith(".png") or plot.endswith(".svg")):
            return plot
    return ""


def guard_context(params):
    repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    disease = params.get("disease") or "downy_mildew"
    field = params.get("field") or ""
    if not field:
        fields = configured_fields(repo)
        if fields:
            field = fields[0]
    common = {"repo_path": repo, "disease": disease}
    if field:
        common["field"] = field
    if params.get("db_path"):
        common["db_path"] = params["db_path"]
    return common


def safe_disease_name(disease):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", disease or "downy_mildew").strip("_") or "disease"


def safe_cache_name(value):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "").strip("_")


def disease_plot_path(repo_path, disease, output_dir=None, field_id=""):
    directory = output_dir or os.path.join(repo_path, "results")
    suffix = f"_{safe_cache_name(field_id)}" if field_id else ""
    return os.path.join(directory, f"dashboard_latest_{safe_disease_name(disease)}{suffix}.png")


def dashboard_state_path(repo_path, disease, output_dir=None, field_id=""):
    directory = output_dir or os.path.join(repo_path, "results")
    suffix = f"_{safe_cache_name(field_id)}" if field_id else ""
    return os.path.join(directory, f"dashboard_state_{safe_disease_name(disease)}{suffix}.json")


def dashboard_report_path(repo_path, disease, output_dir=None, field_id=""):
    directory = output_dir or os.path.join(repo_path, "results")
    suffix = f"_{safe_cache_name(field_id)}" if field_id else ""
    return os.path.join(directory, f"dashboard_report_{safe_disease_name(disease)}{suffix}.md")


def is_generic_dashboard_path(path):
    return os.path.basename(str(path or "")) in {"dashboard_latest.png", "dashboard.png"}


def valid_disease_plot(path, repo_path, disease, output_dir=None, field_id=""):
    expected = disease_plot_path(repo_path, disease, output_dir, field_id)
    generic_expected = disease_plot_path(repo_path, disease, output_dir)
    if not path:
        return ""
    if os.path.abspath(path) not in {os.path.abspath(expected), os.path.abspath(generic_expected)}:
        return ""
    if not os.path.exists(path) or os.path.getsize(path) < 20000:
        return ""
    return path


def period_window(params):
    days = int(params.get("days", 31))
    today = dt.date.today()
    start = params.get("start") or (today - dt.timedelta(days=days - 1)).isoformat()
    end = params.get("end") or today.isoformat()
    key = params.get("key") or f"daily_{end}"
    return start, end, key


def trigger_daily_update(params):
    if params.get("board_only", False):
        return run_board_prediction(params)
    common = guard_context(params)
    date = params.get("date") or dt.date.today().isoformat()
    return call_skill("vineyard_disease_risk", {
        **common,
        "mode": "cron_daily",
        "date": date,
        "timeout": params.get("timeout", 900),
    }, int(params.get("timeout", 900)) + 100)


def run_board_prediction(params):
    common = guard_context(params)
    payload = {**common, "mode": "board_predict"}
    for key in ("date", "start", "end", "days", "model_path"):
        if params.get(key):
            payload[key] = params[key]
    return call_skill("vineyard_disease_risk", payload, 120)


def get_current_risk(params):
    return call_skill("vineyard_disease_risk", {
        **guard_context(params),
        "mode": "current_status",
    }, 60)


def fill_source_gaps(params):
    start, end, _ = period_window(params)
    payload = {
        **guard_context(params),
        "mode": "board_fill_gaps",
        "start": start,
        "end": end,
        "retry_attempts": params.get("retry_attempts", 2),
        "retry_delay_minutes": params.get("retry_delay_minutes", 0),
        "timeout": params.get("timeout", 300),
    }
    return call_skill("vineyard_disease_risk", payload, int(params.get("timeout", 300)) + 60)


def generate_period_plot(params):
    start, end, key = period_window(params)
    if params.get("board_only", False) or params.get("plot_backend") == "board":
        report = call_skill("vineyard_disease_risk", {
            **guard_context(params),
            "mode": "board_plot",
            "start": start,
            "end": end,
            "key": key,
        }, 120)
        return {
            "status": report.get("status", "error"),
            "start": start,
            "end": end,
            "key": key,
            "report": report,
            "plot_path": plot_path_from_report(report),
        }
    report = call_skill("vineyard_disease_risk", {
        **guard_context(params),
        "mode": "predict_period",
        "start": start,
        "end": end,
        "key": key,
        "no_plot": params.get("no_plot", False),
    }, 900)
    return {
        "status": report.get("status", "error"),
        "start": start,
        "end": end,
        "key": key,
        "report": report,
        "plot_path": plot_path_from_report(report),
    }


def update_dashboard_files(params):
    start, end, _ = period_window(params)
    repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    disease = params.get("disease") or "downy_mildew"
    payload = {
        **guard_context(params),
        "mode": "board_update_dashboard",
        "start": start,
        "end": end,
        "days": params.get("days", 31),
    }
    if params.get("output_dir"):
        payload["output_dir"] = params["output_dir"]
    if params.get("skip_predict"):
        payload["skip_predict"] = params["skip_predict"]
    if params.get("skip_forecast"):
        payload["skip_forecast"] = params["skip_forecast"]
    result = call_skill("vineyard_disease_risk", payload, 180)
    stdout = dashboard_stdout(result)
    plot = stdout.get("plot") if isinstance(stdout, dict) else ""
    expected = disease_plot_path(repo, disease, params.get("output_dir"))
    if plot and os.path.abspath(plot) != os.path.abspath(expected):
        if isinstance(stdout, dict):
            stdout["plot"] = ""
            stdout["rejected_plot"] = plot
            stdout["expected_plot"] = expected
        result["status"] = "error"
        result["message"] = "Rejected generic or wrong-disease dashboard plot path"
    if isinstance(stdout, dict) and not int(stdout.get("forecast_rows") or 0):
        result["status"] = "error"
        result["message"] = "Dashboard forecast rows are missing; refusing to send a no-forecast plot"
    if isinstance(result, dict):
        result["field"] = params.get("field") or ""
        result["disease"] = disease
        result["repo_path"] = repo
    store_field_cache(params, result)
    return result


def copy_if_different(source, target):
    if not source or not target or not os.path.exists(source):
        return False
    try:
        if os.path.exists(target) and os.path.samefile(source, target):
            return False
    except OSError:
        pass
    shutil.copy2(source, target)
    return True


def store_field_cache(params, dashboard):
    field = params.get("field") or ""
    if not field:
        return dashboard
    repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    output_dir = params.get("output_dir") or os.path.join(repo, "results")
    disease = params.get("disease") or "downy_mildew"
    stdout = dashboard_stdout(dashboard)
    if not isinstance(stdout, dict) or not stdout.get("state"):
        return dashboard
    try:
        state = json.load(open(stdout["state"], encoding="utf-8"))
    except Exception:
        return dashboard
    if state.get("field") != field or state.get("disease") != disease:
        return dashboard

    field_state = dashboard_state_path(repo, disease, output_dir, field)
    field_report = dashboard_report_path(repo, disease, output_dir, field)
    field_plot = disease_plot_path(repo, disease, output_dir, field)

    os.makedirs(output_dir, exist_ok=True)
    source_plot = stdout.get("plot") or state.get("plot_path") or disease_plot_path(repo, disease, output_dir)
    source_report = stdout.get("report") or os.path.join(output_dir, f"dashboard_report_{safe_disease_name(disease)}.md")
    if source_plot and os.path.exists(source_plot):
        copy_if_different(source_plot, field_plot)
        state["plot_path"] = field_plot
        stdout["plot"] = field_plot
    if source_report and os.path.exists(source_report):
        copy_if_different(source_report, field_report)
        stdout["report"] = field_report
    state["field_cache"] = True
    state["field_cache_created_at"] = dt.datetime.now(dt.UTC).isoformat()
    with open(field_state, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    stdout["state"] = field_state
    return dashboard


def cached_dashboard(params):
    repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    output_dir = params.get("output_dir") or os.path.join(repo, "results")
    disease = params.get("disease") or "downy_mildew"
    safe_disease = safe_disease_name(disease)
    field = params.get("field") or ""
    state_path = dashboard_state_path(repo, disease, output_dir, field) if field else os.path.join(output_dir, f"dashboard_state_{safe_disease}.json")
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return None
    plot_path = valid_disease_plot(
        state.get("plot_path") or disease_plot_path(repo, disease, output_dir, field),
        repo,
        disease,
        output_dir,
        field,
    )
    if not plot_path:
        return None
    if state.get("disease") != disease:
        return None
    if field and state.get("field") != field:
        return None
    updated_at = state.get("updated_at") or ""
    if not updated_at.startswith(dt.date.today().isoformat()):
        return None
    today = dt.date.today().isoformat()
    history = state.get("history") or []
    if not history or str(history[-1].get("day", ""))[:10] != today:
        return None
    forecast = state.get("forecast") or []
    if not forecast:
        return None
    model_layer_freshness = state.get("model_layer_freshness") or {}
    if model_layer_freshness.get("forecast_current") is False:
        return None
    requested_days = int(params.get("days", 31))
    requested_start = (dt.date.today() - dt.timedelta(days=requested_days - 1)).isoformat()
    if str(state.get("start") or "9999-99-99") > requested_start:
        return None
    latest = history[-1]
    if disease == "downy_mildew" and latest.get("rossi_risk") is None:
        return None
    if disease == "powdery_mildew":
        required = ("powdery_risk", "powdery_pmi", "powdery_pmi_treatment_due")
        if any(latest.get(key) is None for key in required):
            return None
        model_refresh = state.get("model_refresh") or {}
        powdery_refresh = model_refresh.get("powdery") or {}
        if not powdery_refresh.get("ok") and not powdery_refresh.get("skipped") is False:
            return None
    return {
        "status": "success",
        "mode": "cached_dashboard",
        "field": field,
        "disease": disease,
        "result": {
            "stdout": {
                "ok": True,
                "state": state_path,
                "plot": plot_path,
                "rows": state.get("rows", 0),
                "cached": True,
            }
        },
    }


def plot_path_from_dashboard(result):
    disease = ""
    field = ""
    repo = "/root/.picoclaw/workspace/goidanich"
    output_dir = ""
    if isinstance(result, dict):
        disease = result.get("disease") or result.get("disease_id") or ""
        field = result.get("field") or ""
        repo = result.get("repo_path") or repo
        data_for_dir = result.get("result", result)
        if isinstance(data_for_dir, dict) and isinstance(data_for_dir.get("stdout"), dict):
            state_path = data_for_dir["stdout"].get("state", "")
            if state_path:
                output_dir = os.path.dirname(state_path)
    data = result.get("result", result) if isinstance(result, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("stdout"), dict):
        plot = data["stdout"].get("plot", "")
        if is_generic_dashboard_path(plot):
            return ""
        if disease:
            return valid_disease_plot(plot, repo, disease, output_dir, field)
        return plot if plot and os.path.exists(plot) and os.path.getsize(plot) >= 20000 else ""
    if isinstance(data, dict) and isinstance(data.get("command"), dict):
        stdout = data["command"].get("stdout")
        if isinstance(stdout, dict):
            plot = stdout.get("plot", "")
            if is_generic_dashboard_path(plot):
                return ""
            return plot if plot and os.path.exists(plot) and os.path.getsize(plot) >= 20000 else ""
    return ""


def dashboard_stdout(result):
    data = result.get("result", result) if isinstance(result, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("stdout"), dict):
        return data["stdout"]
    if isinstance(data, dict) and isinstance(data.get("command"), dict):
        stdout = data["command"].get("stdout")
        if isinstance(stdout, dict):
            return stdout
    return {}


def load_dashboard_state(dashboard):
    stdout = dashboard_stdout(dashboard)
    state_path = stdout.get("state")
    if not state_path:
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def risk_label(value):
    try:
        risk = float(value)
    except Exception:
        risk = 0.0
    if risk >= 70:
        return "high"
    if risk >= 50:
        return "moderate"
    return "low"


def risk_marker(value):
    label = risk_label(value)
    if label == "high":
        return "🔴"
    if label == "moderate":
        return "🟡"
    return "🟢"


def format_percent(value):
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "not available"


def human_action(value):
    raw = str(value or "not available").strip()
    labels = {
        "first_sulfur_or_protection_due": "first sulfur/protection check due",
        "reapply_after_rain": "reapply check after rain",
        "reapply_pmi_threshold": "reapply check from PMI threshold",
        "treatment_recorded_reset": "treatment recorded; PMI reset",
        "monitor": "monitor",
        "not available": "not available",
    }
    return labels.get(raw, raw.replace("_", " "))


def powdery_action_signal(risk, pmi_due):
    try:
        risk = float(risk or 0)
    except Exception:
        risk = 0.0
    if risk >= 70:
        return (
            "PROTECT DECISION",
            "inspect now; apply protection only if cover is missing/expired or powdery mildew is confirmed",
        )
    if risk >= 50:
        return (
            "WATCH",
            "inspect within 24-48h and check recent protection before deciding",
        )
    if pmi_due:
        return (
            "CHECK PROTECTION",
            "UC risk is low; verify first sulfur/protection record, no treatment from risk alone",
        )
    return ("MONITOR", "normal scouting; no powdery action from the model")


def clarification_prompt(disease, latest):
    if disease == "powdery_mildew" and latest.get("powdery_pmi_treatment_due"):
        return (
            "Please confirm after scouting: clean canopy, powdery mildew detected, "
            "or protection already applied. If protection was applied, include product, "
            "dose, water volume, treated area, method, and date."
        )
    return (
        "Please confirm after scouting: clean canopy, mildew detected, false alarm, "
        "or treatment applied. If treated, include product, dose, water volume, area, method, and date."
    )


def fast_cached_standard_report(params, dashboard):
    state = load_dashboard_state(dashboard)
    history = state.get("history") or []
    latest = history[-1] if history else {}
    disease = params.get("disease") or state.get("disease") or "downy_mildew"
    field = params.get("field") or state.get("field") or latest.get("field_id") or ""
    plot_path = plot_path_from_dashboard(dashboard)
    if not state or not latest or not plot_path:
        return None

    repo_path = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    agent = state.get("agent") if isinstance(state.get("agent"), dict) else {}
    agent_meta = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    location = (
        state.get("field_name")
        or state.get("location")
        or agent.get("name")
        or configured_field_label(repo_path, field)
        or agent_meta.get("location")
        or field
    )
    station = (
        latest.get("station")
        or state.get("station")
        or agent_meta.get("station_code")
        or agent_meta.get("station")
        or ""
    )
    variety = state.get("variety") or agent_meta.get("variety") or ""
    day = str(latest.get("day") or "")[:10]
    baseline = latest.get("baseline_risk")
    forecast = state.get("forecast") or []
    forecast_start = str((forecast[0] or {}).get("day") or "")[:10] if forecast else ""
    forecast_end = str((forecast[-1] or {}).get("day") or "")[:10] if forecast else ""
    language = preferred_language(repo_path, field, params)
    forecast_rain = sum(
        float(row.get("forecast_rain") or row.get("rain") or row.get("rain_sum") or 0)
        for row in forecast
        if isinstance(row, dict)
    )
    forecast_temp = [
        float(row.get("forecast_temp") if row.get("forecast_temp") is not None else row.get("temp") if row.get("temp") is not None else row.get("temp_avg"))
        for row in forecast
        if isinstance(row, dict)
        and (row.get("forecast_temp") is not None or row.get("temp") is not None or row.get("temp_avg") is not None)
    ]
    forecast_humi = [
        float(row.get("forecast_humi") if row.get("forecast_humi") is not None else row.get("humi") if row.get("humi") is not None else row.get("humidity"))
        for row in forecast
        if isinstance(row, dict)
        and (row.get("forecast_humi") is not None or row.get("humi") is not None or row.get("humidity") is not None)
    ]
    forecast_prediction = forecast_prediction_from_state(state, disease)
    weather_forecast_line = f"Weather forecast: rain total {forecast_rain:.1f} mm."
    if forecast_temp:
        weather_forecast_line = (
            f"Weather forecast: temp {min(forecast_temp):.1f}-{max(forecast_temp):.1f} C "
            f"(avg {sum(forecast_temp) / len(forecast_temp):.1f} C)"
        )
        if forecast_humi:
            weather_forecast_line += f", humidity avg {sum(forecast_humi) / len(forecast_humi):.0f}%"
        weather_forecast_line += f", rain total {forecast_rain:.1f} mm."

    disease_title = "Powdery mildew" if disease == "powdery_mildew" else "Downy mildew"
    lines = [
        f"🍇 {disease_title} - {location}",
        f"Date: {day} | Station: {station} | Variety: {variety}",
    ]
    if disease == "powdery_mildew":
        risk = latest.get("powdery_risk")
        pmi = latest.get("powdery_pmi")
        pmi_due = latest.get("powdery_pmi_treatment_due")
        action = human_action(latest.get("powdery_pmi_action"))
        pmi_status = "due" if pmi_due else "not due"
        signal, signal_detail = powdery_action_signal(risk, pmi_due)
        forecast_severity = str(forecast_prediction.get("severity") or "").lower()
        forecast_day = (
            forecast_prediction.get("first_high_day")
            or forecast_prediction.get("first_watch_day")
            or forecast_prediction.get("max_day")
            or ""
        )
        lines.extend([
            f"{risk_marker(risk)} Powdery UC risk: {format_percent(risk)} ({risk_label(risk)}).",
            f"PMI: {float(pmi or 0):.1f}; action: {action}; protection check: {pmi_status}.",
            f"Signal: {signal} - {signal_detail}.",
        ])
        if float(risk or 0) >= 70:
            guidance = (
                "PROTECT DECISION: inspect now. Apply protection only if cover is missing/expired "
                "or powdery mildew is confirmed."
            )
        elif float(risk or 0) >= 50:
            guidance = (
                "WATCH: inspect within 24-48h and check treatment records before deciding on protection."
            )
        elif forecast_severity in {"high", "watch"} and forecast_day:
            guidance = (
                f"CHECK PROTECTION: today's UC risk is low, but the forecast reaches {forecast_severity} "
                f"on {forecast_day}. Inspect canopy and confirm active protection before that date; "
                "do not treat automatically from PMI alone."
            )
        elif pmi_due:
            guidance = (
                "PMI is a protection-clock reminder, not a disease-probability alert. "
                "Because UC risk is low, check canopy and recent protection; do not treat automatically."
            )
        else:
            guidance = "No powdery protection check from PMI/UC model; continue monitoring."
    else:
        risk = latest.get("risk")
        trained = latest.get("trained")
        trained = trained not in (None, False, 0, "0", "false", "False")
        forecast_severity = str(forecast_prediction.get("severity") or "").lower()
        downy_now = float(baseline or 0)
        if downy_now >= 70 or forecast_severity == "high":
            downy_signal = "DOWNY ALERT"
            guidance = "DOWNY ALERT: inspect before the forecast/current high-risk window; treat only after scouting and protection-record check."
        elif downy_now >= 50 or forecast_severity == "watch":
            downy_signal = "DOWNY WATCH"
            guidance = "DOWNY WATCH: inspect during the forecast watch window and check protection status."
        else:
            downy_signal = "NO DOWNY ALERT"
            guidance = "NO DOWNY ALERT: Goidanich/Rossi are low for this field; continue normal scouting."
        if trained:
            lines.append(f"{risk_marker(risk)} Personalized risk: {format_percent(risk)} ({risk_label(risk)}).")
        else:
            lines.append("Field-specific learned model: not trained yet; using original Goidanich/Rossi layers.")
        lines.extend([
            f"{risk_marker(baseline)} Goidanich daily risk: {format_percent(baseline)} ({risk_label(baseline)}).",
            f"Rossi state/risk: {format_percent(latest.get('rossi_risk') or 0)} ({risk_label(latest.get('rossi_risk') or 0)}).",
            f"Signal: {downy_signal}.",
        ])

    lines.extend([
        "",
        "Forecast",
        f"Forecast window: {forecast_start} to {forecast_end}." if forecast else "Forecast window: not available.",
        forecast_prediction.get("message", "Forecast prediction: not available."),
        weather_forecast_line,
        "",
        "Guidance",
        guidance,
        "Treatment is never automatic: confirm canopy state, recent protection, and scouting observations before action.",
        "",
        "Clarification",
        clarification_prompt(disease, latest),
        "",
        "Plots are attached.",
    ])
    message = localize_text("\n".join(lines), language)
    title = localize_text(f"{disease.replace('_', ' ').capitalize()} report for {location}", language)
    caption = short_caption(title, message)
    attachment = {
        "type": "photo",
        "path": plot_path,
        "source_path": plot_path,
        "caption": caption,
        "mime_type": "image/png",
        "exists": True,
        "disease": disease,
    }
    return {
        "status": "success",
        "mode": "standard_report",
        "source": "cached_dashboard_state",
        "dashboard": dashboard,
        "dashboard_state": state,
        "field": field,
        "disease": disease,
        "language": language,
        "send_text": message,
        "plot_path": plot_path,
        "image_path": plot_path,
        "photo_path": plot_path,
        "send_image_path": plot_path,
        "send_photo_path": plot_path,
        "attachments": [attachment],
        "media": [attachment],
        "telegram": {
            "method": "sendPhoto",
            "photo": plot_path,
            "caption": caption,
            "text_after_photo": "",
        },
        "must_attach_image": True,
        "must_send_text": True,
    }


def compact_report_summary(report):
    state = report.get("dashboard_state") or {}
    history = state.get("history") or []
    latest = history[-1] if history else {}
    forecast = state.get("forecast") or []
    forecast_rain = 0.0
    forecast_rain_5d = 0.0
    forecast_rain_10d = 0.0
    first_rain_day = ""
    for row in forecast:
        if not isinstance(row, dict):
            continue
        try:
            rain = float(row.get("forecast_rain") or row.get("rain") or row.get("rain_sum") or 0)
        except Exception:
            rain = 0.0
        forecast_rain += rain
        try:
            horizon = int(row.get("horizon_days") or 0)
        except Exception:
            horizon = 0
        if horizon <= 0:
            horizon = len([item for item in forecast[: forecast.index(row) + 1] if isinstance(item, dict)])
        if horizon <= 5:
            forecast_rain_5d += rain
        if horizon <= 10:
            forecast_rain_10d += rain
        if rain >= 1.0 and not first_rain_day:
            first_rain_day = str(row.get("day") or "")[:10]
    disease = report.get("disease") or (report.get("report") or {}).get("disease") or ""
    forecast_prediction = forecast_prediction_from_state(state, disease)
    summary = {
        "status": report.get("status"),
        "field": report.get("field"),
        "disease": disease,
        "source": report.get("source") or "generated",
        "plot": report.get("send_photo_path") or report.get("send_image_path") or report.get("plot_path"),
        "date": str(latest.get("day") or "")[:10],
        "station": latest.get("station"),
        "goidanich_daily_risk": latest.get("baseline_risk"),
        "rossi_risk": latest.get("rossi_risk"),
        "powdery_uc_risk": latest.get("powdery_risk"),
        "powdery_pmi": latest.get("powdery_pmi"),
        "powdery_pmi_treatment_due": latest.get("powdery_pmi_treatment_due"),
        "powdery_pmi_action": latest.get("powdery_pmi_action"),
        "forecast_rows": len(state.get("forecast") or []),
        "forecast_rain_total": round(forecast_rain, 1),
        "forecast_rain_5d": round(forecast_rain_5d, 1),
        "forecast_rain_10d": round(forecast_rain_10d, 1),
        "first_forecast_rain_day": first_rain_day,
        "forecast_prediction_message": forecast_prediction.get("message"),
        "forecast_prediction_severity": forecast_prediction.get("severity"),
        "forecast_prediction_max_risk": forecast_prediction.get("max_risk"),
        "forecast_prediction_max_day": forecast_prediction.get("max_day"),
        "forecast_prediction_first_watch_day": forecast_prediction.get("first_watch_day"),
        "forecast_prediction_first_high_day": forecast_prediction.get("first_high_day"),
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [])}


def rain_amount_label(mm):
    mm = float(mm or 0)
    if mm >= 20:
        return "substantial"
    if mm >= 10:
        return "moderate"
    if mm >= 2:
        return "light"
    return "very little"


def rain_window_text(summaries):
    if not summaries:
        return "Forecast rain: not available."
    total = max(float(item.get("forecast_rain_total") or 0) for item in summaries)
    next5 = max(float(item.get("forecast_rain_5d") or 0) for item in summaries)
    next10 = max(float(item.get("forecast_rain_10d") or 0) for item in summaries)
    first_day = next((str(item.get("first_forecast_rain_day") or "") for item in summaries if item.get("first_forecast_rain_day")), "")
    if first_day:
        return (
            f"Forecast rain: {total:.1f} mm total over 15 days "
            f"({next5:.1f} mm in the next 5 days, first wet day {first_day}; {rain_amount_label(total)} event)."
        )
    return f"Forecast rain: {total:.1f} mm total over 15 days ({next5:.1f} mm in the next 5 days; dry window)."


def forecast_prediction_from_state(state, disease):
    existing = state.get("forecast_prediction") if isinstance(state, dict) else None
    existing_message = str((existing or {}).get("message") or "")
    if (
        isinstance(existing, dict)
        and existing.get("message")
        and not (disease != "powdery_mildew" and "accumulated" in existing_message.lower())
    ):
        return existing
    forecast = state.get("forecast") if isinstance(state, dict) else []
    if disease == "powdery_mildew":
        key = "powdery_projection"
        label = "Powdery UC disease forecast"
    else:
        key = "goidanich_daily_projection"
        label = "Downy daily disease forecast"
    points = []
    for row in forecast or []:
        if not isinstance(row, dict):
            continue
        value = row.get(key)
        if value is None:
            continue
        try:
            risk = float(value)
        except Exception:
            continue
        day = str(row.get("day") or "")[:10]
        if day:
            points.append({"day": day, "risk": risk})
    if not points:
        return {"available": False, "severity": "unavailable", "message": f"{label}: not available."}
    max_point = max(points, key=lambda item: item["risk"])
    first_watch = next((item for item in points if item["risk"] >= 50), None)
    first_high = next((item for item in points if item["risk"] >= 70), None)
    if first_high:
        severity = "high"
        message = f"{label}: HIGH; first >=70% on {first_high['day']}; maximum {max_point['risk']:.1f}% on {max_point['day']}."
    elif first_watch:
        severity = "watch"
        message = f"{label}: WATCH; first >=50% on {first_watch['day']}; maximum {max_point['risk']:.1f}% on {max_point['day']}."
    else:
        severity = "low"
        message = f"{label}: LOW; maximum {max_point['risk']:.1f}% on {max_point['day']}."
    return {
        "available": True,
        "severity": severity,
        "max_risk": round(max_point["risk"], 3),
        "max_day": max_point["day"],
        "first_watch_day": first_watch["day"] if first_watch else None,
        "first_high_day": first_high["day"] if first_high else None,
        "message": message,
    }


def treatment_readiness_message(summaries, alert_reports=None, high_threshold=70):
    alert_reports = alert_reports or []
    downy = next((item for item in summaries if item.get("disease") == "downy_mildew"), {})
    powdery = next((item for item in summaries if item.get("disease") == "powdery_mildew"), {})
    forecast_rain = max(float(item.get("forecast_rain_total") or 0) for item in summaries) if summaries else 0.0
    forecast_rain_5d = max(float(item.get("forecast_rain_5d") or 0) for item in summaries) if summaries else 0.0
    first_rain_day = next((str(item.get("first_forecast_rain_day") or "") for item in summaries if item.get("first_forecast_rain_day")), "")
    pmi_due = bool(powdery.get("powdery_pmi_treatment_due"))
    powdery_risk = float(powdery.get("powdery_uc_risk") or 0)
    downy_risk = float(downy.get("goidanich_daily_risk") or 0)
    future_high = any((report.get("risk_alert_policy") or {}).get("notify") for report in alert_reports)
    rain_window = "next 5 days" if forecast_rain_5d >= 2 else "next 10-15 days"
    wet_day = f" starting around {first_rain_day}" if first_rain_day else ""

    powdery_signal, powdery_signal_detail = powdery_action_signal(powdery_risk, pmi_due)

    if pmi_due and powdery_risk >= 50 and forecast_rain >= 5:
        return (
            f"{powdery_signal}: be ready to decide in the {rain_window}{wet_day}; "
            f"{powdery_signal_detail}."
        )
    if pmi_due and forecast_rain >= 5:
        return (
            f"{powdery_signal}: PMI asks for a powdery protection check in the {rain_window}{wet_day}; "
            f"{powdery_signal_detail}."
        )
    if pmi_due:
        return (
            "Treatment outlook: the forecast is mostly dry, so there is no rain-driven treatment trigger. "
            "Use scouting and the protection record before deciding."
        )
    if future_high and forecast_rain >= 5:
        return (
            f"Treatment outlook: watch the {rain_window}{wet_day}. A forecast model reaches watch/high levels "
            "and rain is expected, so be ready to inspect and protect if field scouting confirms pressure."
        )
    if forecast_rain >= 10:
        return (
            f"Treatment outlook: {rain_amount_label(forecast_rain)} rain is forecast{wet_day}. "
            "Current risk is still the priority, but check coverage before and after the wet period."
        )
    if max(downy_risk, powdery_risk) < 50 and forecast_rain < 2:
        return "Treatment outlook: dry forecast and low current models; no immediate treatment signal, keep normal scouting."
    return "Treatment outlook: no automatic treatment signal; use scouting and recent treatment history before applying anything."


def low_risk_summary_message(field, reports, repo_path=None):
    field_label = configured_field_label(repo_path, field)
    summaries = [compact_report_summary(report) for report in reports]
    downy = next((item for item in summaries if item.get("disease") == "downy_mildew"), {})
    powdery = next((item for item in summaries if item.get("disease") == "powdery_mildew"), {})
    day = downy.get("date") or powdery.get("date") or dt.date.today().isoformat()
    station = downy.get("station") or powdery.get("station") or ""
    downy_risk = downy.get("goidanich_daily_risk")
    rossi = downy.get("rossi_risk")
    powdery_risk = powdery.get("powdery_uc_risk")
    pmi = powdery.get("powdery_pmi")
    pmi_due = bool(powdery.get("powdery_pmi_treatment_due"))
    lines = [
        f"🍇 Vineyard risk summary - {field_label}",
        f"Date: {day}" + (f" | Station: {station}" if station else ""),
        f"🟢 Downy mildew: low. Goidanich daily {format_percent(downy_risk)}, Rossi {format_percent(rossi or 0)}.",
        f"🟢 Powdery mildew: low. UC risk {format_percent(powdery_risk)}, PMI {float(pmi or 0):.1f}.",
    ]
    powdery_signal, powdery_signal_detail = powdery_action_signal(powdery_risk, pmi_due)
    if pmi_due:
        lines.append(f"Powdery signal: {powdery_signal} - {powdery_signal_detail}.")
    else:
        lines.append("No high-risk alert. Continue normal monitoring.")
    for item in (downy, powdery):
        message = item.get("forecast_prediction_message")
        if message:
            lines.append(f"Disease forecast: {message}")
    lines.append(rain_window_text(summaries))
    lines.append(treatment_readiness_message(summaries))
    return "\n".join(lines)


def recent_treatments(repo_path, field, limit=3):
    db_path = os.path.join(repo_path or "/root/.picoclaw/workspace/goidanich", "goidanich.db")
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT timestamp, disease_id, notes, metadata
            FROM farmer_feedback
            WHERE field_id = ?
              AND feedback_type = 'treatment'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (field, int(limit)),
        ).fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        metadata = {}
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except Exception:
            metadata = {}
        treatment = metadata.get("treatment") or {}
        out.append({
            "timestamp": str(row["timestamp"] or ""),
            "date": str(row["timestamp"] or "")[:10],
            "disease_id": row["disease_id"],
            "product": treatment.get("product") or "product not recorded",
            "product_number": treatment.get("product_number") or "",
            "dose": treatment.get("dose") or "",
            "water_volume": treatment.get("water_volume") or "",
            "area": treatment.get("area") or "",
            "method": treatment.get("method") or "",
            "treatment_type": treatment.get("treatment_type") or "",
        })
    return out


def treatment_history_line(repo_path, field):
    treatments = recent_treatments(repo_path, field, 2)
    if not treatments:
        return "No treatment record is stored for this field. Please confirm recent applications."
    latest = treatments[0]
    parts = [f"Last treatment: {latest['product']} on {latest['date']}"]
    if latest.get("dose"):
        parts.append(f"dose {latest['dose']}")
    if latest.get("water_volume"):
        parts.append(f"water {latest['water_volume']}")
    if latest.get("area"):
        parts.append(f"area {latest['area']}")
    if latest.get("method"):
        parts.append(f"method {latest['method']}")
    if latest.get("product_number"):
        parts.append(f"code {latest['product_number']}")
    return "; ".join(parts) + "."


def forecast_high_signal(report, threshold):
    state = report.get("dashboard_state") or {}
    disease = report.get("disease") or (report.get("report") or {}).get("disease") or ""
    forecast = state.get("forecast") or []
    if disease == "powdery_mildew":
        keys = ("powdery_projection",)
    else:
        keys = ("goidanich_daily_projection", "rossi_projection")
    best = None
    starts = {}
    for row in forecast:
        if not isinstance(row, dict):
            continue
        for key in keys:
            try:
                value = float(row.get(key) or 0)
            except Exception:
                continue
            if value > 0 and key not in starts:
                starts[key] = (value, str(row.get("day") or "")[:10])
            if best is None or value > best[0]:
                best = (value, str(row.get("day") or "")[:10], key)
    if best and best[0] >= float(threshold):
        start_value, start_day = starts.get(best[2], (None, ""))
        return {
            "notify": True,
            "risk": best[0],
            "day": best[1],
            "key": best[2],
            "start_value": start_value,
            "start_day": start_day,
        }
    return {"notify": False}


def future_action_message(summaries, alert_reports, high_threshold):
    alert_reports = alert_reports or []
    forecast_rain = max(float(item.get("forecast_rain_total") or 0) for item in summaries) if summaries else 0.0
    forecast_rain_5d = max(float(item.get("forecast_rain_5d") or 0) for item in summaries) if summaries else 0.0
    first_rain_day = next((str(item.get("first_forecast_rain_day") or "") for item in summaries if item.get("first_forecast_rain_day")), "")
    rain_window = "next 5 days" if forecast_rain_5d >= 2 else "next 10-15 days"
    wet_day = f" starting around {first_rain_day}" if first_rain_day else ""
    actions = []
    has_forecast_high = False
    has_current_alert = False
    for report in alert_reports:
        disease = report.get("disease") or (report.get("report") or {}).get("disease") or ""
        title = "Powdery" if disease == "powdery_mildew" else "Downy"
        future = forecast_high_signal(report, high_threshold)
        alert = report.get("risk_alert_policy") or {}
        if future.get("notify"):
            has_forecast_high = True
            first_day = future.get("start_day") or future.get("day")
            peak_day = future.get("day")
            peak = format_percent(future.get("risk"))
            if disease == "powdery_mildew":
                actions.append(
                    f"{title}: before {first_day}, inspect leaves and bunch zone and verify sulfur/protection cover; "
                    f"forecast peaks at {peak} on {peak_day}."
                )
            else:
                actions.append(
                    f"{title}: before {first_day}, check canopy infection symptoms and protection status; "
                    f"forecast peaks at {peak} on {peak_day}."
                )
        elif alert.get("notify"):
            has_current_alert = True
            actions.append(
                f"{title}: current alert is active; scout now and use treatment records before deciding."
            )
    if not actions:
        return "Future action: no forecast high-risk window is active; continue routine scouting."
    if has_forecast_high and forecast_rain >= 2:
        advice = (
            "Advice: TREATMENT DECISION WINDOW - prepare to inspect and decide before the risk/weather window; "
            "treat only if protection is absent/expired or disease is confirmed."
        )
    elif has_current_alert:
        advice = (
            "Advice: WATCH NOW - scout the field and check recent protection; treatment is a decision after inspection."
        )
    else:
        advice = (
            "Advice: WATCH - inspect before the forecast risk date and verify protection; no automatic treatment."
        )
    actions.insert(0, advice)
    if forecast_rain >= 2:
        actions.append(
            f"Weather window: {rain_amount_label(forecast_rain)} rain in the {rain_window}{wet_day}; "
            "check cover before the wet period and scout after it."
        )
    else:
        actions.append(
            "Weather window: mostly dry; do not treat from rain pressure alone, but keep the forecast-risk scouting date."
        )
    actions.append("Decision rule: treatment is not automatic; act only after scouting and recent protection history.")
    return "Future action:\n" + "\n".join(f"- {line}" for line in actions)


def risk_alert_summary_message(field, reports, alert_reports, high_threshold, repo_path=None):
    field_label = configured_field_label(repo_path, field)
    summaries = [compact_report_summary(report) for report in reports]
    downy = next((item for item in summaries if item.get("disease") == "downy_mildew"), {})
    powdery = next((item for item in summaries if item.get("disease") == "powdery_mildew"), {})
    day = downy.get("date") or powdery.get("date") or dt.date.today().isoformat()
    station = downy.get("station") or powdery.get("station") or ""
    lines = [
        f"🍇 Vineyard treatment watch - {field_label}",
        f"Date: {day}" + (f" | Station: {station}" if station else ""),
        f"Downy mildew today: Goidanich {format_percent(downy.get('goidanich_daily_risk'))}, Rossi {format_percent(downy.get('rossi_risk') or 0)}.",
        f"Powdery mildew today: UC risk {format_percent(powdery.get('powdery_uc_risk'))}, PMI {float(powdery.get('powdery_pmi') or 0):.1f}.",
    ]
    downy_risk = float(downy.get("goidanich_daily_risk") or 0)
    downy_forecast = str(downy.get("forecast_prediction_severity") or "").lower()
    if downy_risk >= 70 or downy_forecast == "high":
        lines.append("Downy signal: DOWNY ALERT.")
    elif downy_risk >= 50 or downy_forecast == "watch":
        lines.append("Downy signal: DOWNY WATCH.")
    else:
        lines.append("Downy signal: NO DOWNY ALERT.")
    for report in alert_reports:
        disease = report.get("disease") or (report.get("report") or {}).get("disease") or ""
        title = "Powdery mildew" if disease == "powdery_mildew" else "Downy mildew"
        future = forecast_high_signal(report, high_threshold)
        alert = report.get("risk_alert_policy") or {}
        if future.get("notify"):
            key = str(future.get("key") or "")
            if "accumulated" in key:
                lines.append(
                    f"⚠️ {title}: accumulated forecast line reaches {format_percent(future.get('risk'))} "
                    f"on {future.get('day')} (warning context, not today's daily risk)."
                )
            else:
                if disease == "powdery_mildew":
                    start = ""
                    if future.get("start_day") and future.get("start_value") is not None:
                        start = f" is {format_percent(future.get('start_value'))} on {future.get('start_day')} and"
                    lines.append(
                        f"⚠️ {title}: forecast weather-suitability for UC powdery mildew{start} "
                        f"reaches {format_percent(future.get('risk'))} on {future.get('day')} "
                        "(watch context, not a continuation of today's UC risk)."
                    )
                else:
                    start = ""
                    if future.get("start_day") and future.get("start_value") is not None:
                        start = f" starts at {format_percent(future.get('start_value'))} on {future.get('start_day')} and"
                    lines.append(
                        f"⚠️ {title}: forecast daily-risk line{start} reaches {format_percent(future.get('risk'))} "
                        f"on {future.get('day')} (forecast curve, not today's risk)."
                    )
        elif alert.get("notify"):
            lines.append(f"⚠️ {title}: {alert.get('reason') or 'risk alert'}")
    if powdery.get("powdery_pmi_treatment_due"):
        signal, detail = powdery_action_signal(powdery.get("powdery_uc_risk"), True)
        lines.append(f"Powdery signal: {signal} - {detail}.")
    lines.append(future_action_message(summaries, alert_reports, high_threshold))
    lines.append(rain_window_text(summaries))
    lines.append(treatment_history_line(repo_path, field))
    lines.append("Reply with scouting result or treatment details: product, dose, water volume, area, method, and date.")
    return "\n".join(lines)


def evaluate_alert_policy(params, status=None):
    status = status or params.get("status") or get_current_risk(params)
    return call_skill("risk_alert_policy", {
        "status": status,
        "memory_path": params.get("memory_path") or "/tmp/vineyard_alert_memory.json",
        "high_threshold": params.get("high_threshold", 70),
        "watch_threshold": params.get("watch_threshold", 50),
        "delta_threshold": params.get("delta_threshold", 15),
        "cooldown_hours": params.get("cooldown_hours", 24),
        "update_memory": params.get("update_memory", True),
    }, 30)


def optionally_capture_canopy_photo(params, alert):
    if not params.get("capture_on_alert", False) or not alert.get("notify"):
        return {"status": "skipped", "reason": "capture_on_alert disabled or no alert"}
    output_path = params.get("photo_path") or f"/tmp/vineyard_guard_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    return call_skill("capture_image", {
        "output_path": output_path,
        "width": params.get("photo_width", 320),
        "height": params.get("photo_height", 240),
    }, 45)


def package_farmer_alert(params, alert=None, report=None, plot_path="", photo=None):
    alert = alert or params.get("alert") or {}
    report = report or params.get("report") or {}
    repo_path = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    language = preferred_language(repo_path, params.get("field") or "", params)
    composed = call_skill("farmer_report_compose", {
        "alert": alert,
        "report": report.get("result", report),
        "plot_path": plot_path or params.get("plot_path", ""),
        "disease": params.get("disease") or "downy_mildew",
        "language": language,
    }, 30)
    message = localize_text(composed.get("message", ""), language)
    if photo and photo.get("status") == "success" and photo.get("path"):
        message = f"{message}\nPhoto: {photo['path']}".strip()
    notification = call_skill("farmer_notify", {
        "title": localize_text(composed.get("title", "Vineyard alert"), language),
        "message": message,
        "plot_path": plot_path or composed.get("plot_path", ""),
        "language": language,
        "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
        "channel": params.get("channel") or "picoclaw_telegram",
    }, 30)
    return {"status": notification.get("status", "error"), "message": composed, "notification": notification}


def rows_from_status(status):
    result = status.get("result", status) if isinstance(status, dict) else {}
    if isinstance(result, dict) and "current_status" in result:
        result = result["current_status"]
    if isinstance(result, dict) and "result" in result:
        result = result["result"]
    return result.get("rows", []) if isinstance(result, dict) else []


def needs_rossi_regeneration(status):
    rows = rows_from_status(status)
    if not rows:
        return False
    for row in rows[:3]:
        if row.get("rossi_available") in (0, "0", False):
            return True
        if row.get("rossi_risk") is None:
            return True
    return False


def alert_from_latest_status(status):
    rows = rows_from_status(status)
    if not rows:
        return {
            "status": "success",
            "notify": False,
            "severity": "low",
            "reason": "low risk threshold not reached",
            "alerts": [],
        }
    row = rows[0]
    disease = status.get("disease") or status.get("disease_id") or ""
    risk = row.get("personalized_risk", row.get("risk", 0)) or 0
    if disease == "powdery_mildew":
        risk = row.get("powdery_risk", risk) or risk
    try:
        risk = float(risk)
    except Exception:
        risk = 0.0
    severity = "high" if risk >= 70 else "watch" if risk >= 50 else "low"
    reason = "low risk" if severity == "low" else "risk threshold reached"
    return {
        "status": "success",
        "notify": severity in {"high", "watch"},
        "severity": severity,
        "reason": reason,
        "alerts": [{
            "field": row.get("field_id") or row.get("field") or "field",
            "day": row.get("day", ""),
            "risk": risk,
            "severity": severity,
            "notify": severity in {"high", "watch"},
            "reason": reason,
            "row": row,
        }],
    }


def standard_report(params):
    repo_path = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    language = preferred_language(repo_path, params.get("field") or "", params)
    dashboard = cached_dashboard(params)
    if dashboard and not params.get("force_refresh"):
        cached_report = fast_cached_standard_report(params, dashboard)
        if cached_report:
            return cached_report
    if params.get("cache_only") and not params.get("force_refresh"):
        disease = params.get("disease") or "downy_mildew"
        field = params.get("field") or ""
        message = localize_text(
            "Today's cached vineyard report is not available yet for this field/disease. "
            "The board should refresh it in the scheduled daily field jobs.",
            language,
        )
        return {
            "status": "cache_missing",
            "mode": "standard_report",
            "field": field,
            "disease": disease,
            "language": language,
            "notify": False,
            "has_alert": False,
            "reason": "today_cache_missing",
            "send_text": message,
            "attachments": [],
            "media": [],
            "telegram": {"method": "sendMessage", "text_after_photo": message, "media": []},
            "must_send_text": bool(message),
            "must_attach_image": False,
            "must_send_exactly": True,
        }
    if params.get("force_refresh") or not dashboard:
        dashboard = update_dashboard_files({**params, "days": params.get("days", 31)})
    dashboard_result = dashboard.get("result") if isinstance(dashboard, dict) else {}
    dashboard_stdout = dashboard_result.get("stdout") if isinstance(dashboard_result, dict) else {}
    prediction = dashboard_stdout.get("prediction") if isinstance(dashboard_stdout, dict) else None
    if not prediction:
        prediction = run_board_prediction({**params, "days": params.get("days", 31)})
    dashboard_plot_path = plot_path_from_dashboard(dashboard)
    plot = {"status": "success" if dashboard_plot_path else "error", "report": dashboard, "plot_path": dashboard_plot_path}
    if not dashboard_plot_path:
        return {
            "status": "error",
            "mode": "standard_report",
            "message": "real dashboard plot is unavailable; not sending fallback plot",
            "dashboard": dashboard,
            "must_send_exactly": True,
        }
    status = get_current_risk(params)
    source_gap_fill = {"status": "skipped", "reason": "source rows present"}
    if needs_rossi_regeneration(status):
        source_gap_fill = fill_source_gaps({**params, "days": params.get("days", 31)})
        dashboard = update_dashboard_files({**params, "days": params.get("days", 31)})
        dashboard_result = dashboard.get("result") if isinstance(dashboard, dict) else {}
        dashboard_stdout = dashboard_result.get("stdout") if isinstance(dashboard_result, dict) else {}
        prediction = dashboard_stdout.get("prediction") if isinstance(dashboard_stdout, dict) else prediction
        dashboard_plot_path = plot_path_from_dashboard(dashboard)
        plot = {"status": "success" if dashboard_plot_path else "error", "report": dashboard, "plot_path": dashboard_plot_path}
        if not dashboard_plot_path:
            return {
                "status": "error",
                "mode": "standard_report",
                "message": "real dashboard plot is unavailable after regeneration; not sending fallback plot",
                "dashboard": dashboard,
                "source_gap_fill": source_gap_fill,
                "must_send_exactly": True,
            }
        status = get_current_risk(params)
    alert = alert_from_latest_status(status)
    state = load_dashboard_state(dashboard)
    composed = call_skill("farmer_report_compose", {
        "alert": alert,
        "report": plot.get("report", {}),
        "dashboard_state": state,
        "plot_path": plot.get("plot_path", ""),
        "disease": params.get("disease") or "downy_mildew",
        "field": params.get("field", ""),
        "language": language,
    }, 30)
    telegram_payload = {
        "title": localize_text(composed.get("title", "Vineyard disease report"), language),
        "message": localize_text(composed.get("message", ""), language),
        "plot_path": composed.get("plot_path") or plot.get("plot_path", ""),
        "image_path": composed.get("plot_path") or plot.get("plot_path", ""),
        "language": language,
    }
    telegram_payload["caption"] = short_caption(telegram_payload["title"], telegram_payload["message"])
    image_path = telegram_payload["image_path"]
    send_media = []
    if image_path:
        send_media.append({
            "type": "photo",
            "path": image_path,
            "caption": telegram_payload["caption"],
            "mime_type": "image/png" if image_path.lower().endswith(".png") else "image/jpeg",
            "exists": os.path.exists(image_path),
        })
    guard = call_skill("report_guard", {
        "text": telegram_payload["message"],
        "plot_path": telegram_payload["image_path"],
        "report": {
            "report": composed,
            "plot_path": telegram_payload["image_path"],
            "alert": alert,
        },
    }, 30)
    notification = {"status": "skipped", "reason": "notify=false"}
    if str(params.get("notify", "false")).lower() == "true":
        notification = call_skill("farmer_notify", {
            **telegram_payload,
            "language": language,
            "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
            "channel": params.get("channel") or "picoclaw_telegram",
        }, 30)
    effective_image_path = notification.get("photo_path") or notification.get("image_path") or image_path
    if send_media:
        send_media[0]["path"] = effective_image_path
        send_media[0]["source_path"] = image_path
        send_media[0]["exists"] = os.path.exists(effective_image_path)
    return {
        "status": "success" if composed.get("status") == "success" else "partial",
        "mode": "standard_report",
        "prediction": prediction,
        "current_status": status,
        "language": language,
        "model_refresh": dashboard.get("result", {}).get("stdout", {}).get("model_refresh") if isinstance(dashboard.get("result"), dict) else {},
        "source_gap_fill": source_gap_fill,
        "alert": alert,
        "dashboard": dashboard,
        "dashboard_state": state,
        "plot": plot,
        "report": composed,
        "plot_path": plot.get("plot_path", ""),
        "telegram_payload": telegram_payload,
        "send_text": telegram_payload["message"],
        "send_image_path": effective_image_path,
        "source_image_path": image_path,
        "send_photo_path": effective_image_path,
        "attachment_path": effective_image_path,
        "attachments": send_media,
        "media": send_media,
        "telegram": {
            "method": "sendPhoto" if image_path else "sendMessage",
            "photo": effective_image_path,
            "caption": telegram_payload["caption"],
            "text_after_photo": "",
        },
        "must_attach_image": bool(effective_image_path),
        "must_send_text": bool(telegram_payload["message"]),
        "must_send_exactly": True,
        "report_guard": guard,
        "notification": notification,
        "risk_wording": {
            "low": "<50%: low risk; no treatment signal from the model",
            "watch": "50-69.9%: moderate/watch risk; inspect this week",
            "high": ">=70%: high risk; inspect now and consider treatment only after field confirmation",
        },
    }


def both_disease_report(params):
    field = params.get("field", "")
    if not field:
        repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
        language = preferred_language(repo, "", params)
        notify_mode = str(params.get("notify_mode") or "").lower()
        send_low_summary = str(
            params.get("send_low_summary") or params.get("low_summary") or "false"
        ).lower() == "true"
        fields = configured_fields(repo)
        delivery_group = params.get("delivery_group") or (
            f"vineyard:{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}:{notify_mode or 'report'}"
        )
        multi_field_cache_only = bool(params.get("cache_only")) or (
            len(fields) > 2 and not params.get("force_refresh")
        )
        field_reports = [
            both_disease_report({
                **params,
                "field": current_field,
                "delivery_group": delivery_group,
                "cache_only": multi_field_cache_only,
            })
            for current_field in fields
        ]
        if notify_mode in {"risk_only", "alerts_only"}:
            alert_field_reports = [report for report in field_reports if report.get("has_alert")]
            missing_field_reports = [
                report for report in field_reports
                if not report.get("has_alert") and report_has_incomplete_cache(report)
            ]
            ok_field_reports = [
                report for report in field_reports
                if not report.get("has_alert") and not report_has_incomplete_cache(report)
            ]
            if alert_field_reports:
                all_attachments = []
                overview_message = localize_text(
                    fleet_overview_message(repo, fields, alert_field_reports, ok_field_reports, missing_field_reports),
                    language,
                )
                message_parts = [overview_message]
                missing_fields = [report.get("field") for report in missing_field_reports if report.get("field")]
                if missing_fields:
                    append_unique_text(message_parts, cache_incomplete_message(repo, missing_fields, language))
                for report in alert_field_reports:
                    all_attachments.extend(report.get("attachments") or [])
                    if len(alert_field_reports) <= 2 and report.get("send_text"):
                        append_unique_text(message_parts, str(report.get("send_text") or "").strip())
                all_attachments = localize_media(unique_by_path(all_attachments), language)
                if len(alert_field_reports) > 2:
                    attachments = localize_media(unique_by_path(alert_field_reports[0].get("attachments") or [])[:2], language)
                else:
                    attachments = all_attachments
                message = "\n\n".join(message_parts).strip()
                primary_photo = attachments[0]["path"] if attachments else ""
                notification = {"status": "skipped", "reason": "notify=false"}
                if str(params.get("notify", "false")).lower() == "true" or alert_field_reports:
                    notification = call_skill("farmer_notify", {
                        "title": localize_text("Vineyard risk report", language),
                        "message": overview_message,
                        "plot_path": primary_photo,
                        "image_path": primary_photo,
                        "caption": short_caption(localize_text("Vineyard risk report", language), overview_message),
                        "attachments": attachments,
                        "media": attachments,
                        "delivery_group": delivery_group,
                        "dispatch_role": "fleet_overview",
                        "language": language,
                        "field_scope": "alert_fields",
                        "alert_fields": [report.get("field") for report in alert_field_reports],
                        "ok_fields": [report.get("field") for report in ok_field_reports],
                        "has_alert": True,
                        "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
                        "channel": params.get("channel") or "picoclaw_telegram",
                    }, 30)
                return {
                    "status": "success",
                    "mode": "both_disease_report",
                    "field_scope": "alert_fields",
                    "fields": fields,
                    "alert_fields": [report.get("field") for report in alert_field_reports],
                    "ok_fields": [report.get("field") for report in ok_field_reports],
                    "cache_missing_fields": missing_fields,
                    "field_reports": [compact_field_report(report) for report in field_reports],
                    "notify": True,
                    "has_alert": True,
                    "language": language,
                    "send_text": message,
                    "send_image_path": primary_photo,
                    "send_photo_path": primary_photo,
                    "attachments": attachments,
                    "media": attachments,
                    "all_field_attachment_count": len(all_attachments),
                    "telegram": {
                        "method": "sendMediaGroup" if len(attachments) > 1 else "sendPhoto" if primary_photo else "sendMessage",
                        "photo": primary_photo,
                        "caption": short_caption(localize_text("Vineyard risk report", language), message),
                        "text_after_photo": message,
                        "media": attachments,
                    },
                    "notification": notification,
                    "must_attach_image": bool(attachments),
                    "must_send_text": bool(message),
                    "must_send_exactly": True,
                    "full_reports_omitted": True,
                }
            if missing_field_reports:
                missing_fields = [report.get("field") for report in missing_field_reports if report.get("field")]
                message = cache_incomplete_message(repo, missing_fields, language)
                notification = {"status": "skipped", "reason": "notify=false"}
                if send_low_summary:
                    notification = call_skill("farmer_notify", {
                        "title": localize_text("Vineyard risk summary", language),
                        "message": message,
                        "caption": short_caption(localize_text("Vineyard risk summary", language), message),
                        "attachments": [],
                        "media": [],
                        "delivery_group": delivery_group,
                        "dispatch_role": "fleet_cache_incomplete",
                        "language": language,
                        "field_scope": "cache_missing_fields",
                        "alert_fields": [],
                        "ok_fields": [report.get("field") for report in ok_field_reports],
                        "cache_missing_fields": missing_fields,
                        "has_alert": False,
                        "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
                        "channel": params.get("channel") or "picoclaw_telegram",
                    }, 30)
                return {
                    "status": "cache_missing",
                    "mode": "both_disease_report",
                    "field_scope": "cache_missing_fields",
                    "fields": fields,
                    "alert_fields": [],
                    "ok_fields": [report.get("field") for report in ok_field_reports],
                    "cache_missing_fields": missing_fields,
                    "field_reports": [compact_field_report(report) for report in field_reports],
                    "notify": bool(send_low_summary),
                    "has_alert": False,
                    "language": language,
                    "reason": "today cache incomplete; refusing to classify missing fields as low risk",
                    "send_text": message if send_low_summary else "",
                    "attachments": [],
                    "media": [],
                    "telegram": {
                        "method": "sendMessage",
                        "caption": short_caption(localize_text("Vineyard risk summary", language), message),
                        "text_after_photo": message if send_low_summary else "",
                        "media": [],
                    },
                    "notification": notification,
                    "must_attach_image": False,
                    "must_send_text": bool(send_low_summary and message),
                    "must_send_exactly": True,
                    "full_reports_omitted": True,
                }
            if send_low_summary:
                message = localize_text(fleet_overview_message(repo, fields, [], field_reports), language)
                notification = call_skill("farmer_notify", {
                    "title": localize_text("Vineyard risk summary", language),
                    "message": message,
                    "caption": short_caption(localize_text("Vineyard risk summary", language), message),
                    "attachments": [],
                    "media": [],
                    "delivery_group": delivery_group,
                    "dispatch_role": "fleet_overview",
                    "language": language,
                    "field_scope": "all_fields",
                    "alert_fields": [],
                    "ok_fields": fields,
                    "has_alert": False,
                    "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
                    "channel": params.get("channel") or "picoclaw_telegram",
                }, 30)
                return {
                    "status": "success",
                    "mode": "both_disease_report",
                    "field_scope": "all_fields",
                    "fields": fields,
                    "alert_fields": [],
                    "ok_fields": fields,
                    "field_reports": [compact_field_report(report) for report in field_reports],
                    "notify": True,
                    "has_alert": False,
                    "language": language,
                    "reason": "no field has a risk alert; sent text-only low summary",
                    "send_text": message,
                    "attachments": [],
                    "media": [],
                    "telegram": {
                        "method": "sendMessage",
                        "caption": short_caption(localize_text("Vineyard risk summary", language), message),
                        "text_after_photo": message,
                        "media": [],
                    },
                    "notification": notification,
                    "must_attach_image": False,
                    "must_send_text": True,
                    "must_send_exactly": True,
                    "full_reports_omitted": True,
                }
            return {
                "status": "success",
                "mode": "both_disease_report",
                "field_scope": "all_fields",
                "fields": fields,
                "alert_fields": [],
                "ok_fields": fields,
                "field_reports": [compact_field_report(report) for report in field_reports],
                "notify": False,
                "has_alert": False,
                "language": language,
                "reason": "no field has a risk alert",
                "send_text": "",
                "attachments": [],
                "media": [],
                "telegram": {"method": "sendMessage", "text_after_photo": "", "media": []},
                "must_attach_image": False,
                "must_send_text": False,
                "must_send_exactly": True,
                "full_reports_omitted": True,
            }
        attachments = []
        message_parts = []
        notify_any = False
        for report in field_reports:
            attachments.extend(report.get("attachments") or [])
            if report.get("send_text"):
                text = str(report.get("send_text") or "").strip()
                if text.startswith("🍇 Vineyard"):
                    append_unique_text(message_parts, text)
                else:
                    prefix = f"🍇 Vineyard risk summary - {configured_field_label(repo, report.get('field'))}"
                    append_unique_text(message_parts, f"{prefix}\n{text}")
            notify_any = notify_any or bool(report.get("notify"))
        attachments = localize_media(unique_by_path(attachments), language)
        message = localize_text("\n\n".join(message_parts).strip(), language)
        primary_photo = attachments[0]["path"] if attachments else ""
        notification = {"status": "skipped", "reason": "notify=false"}
        if str(params.get("notify", "false")).lower() == "true":
            notification = call_skill("farmer_notify", {
                "title": localize_text("Vineyard risk report", language),
                "message": message,
                "caption": short_caption(localize_text("Vineyard risk report", language), message),
                "plot_path": primary_photo,
                "image_path": primary_photo,
                "attachments": attachments,
                "media": attachments,
                "language": language,
                "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
                "channel": params.get("channel") or "picoclaw_telegram",
            }, 30)
            if notification.get("attachments"):
                attachments = notification.get("attachments") or attachments
                primary_photo = notification.get("photo_path") or notification.get("image_path") or primary_photo
        return {
            "status": "success" if field_reports else "error",
            "mode": "both_disease_report",
            "field_scope": "all_fields",
            "fields": fields,
            "field_reports": [compact_field_report(report) for report in field_reports],
            "notify": notify_any,
            "language": language,
            "send_text": message,
            "send_image_path": primary_photo,
            "send_photo_path": primary_photo,
            "attachments": attachments,
            "media": attachments,
            "telegram": {
                "method": "sendMediaGroup" if len(attachments) > 1 else "sendPhoto" if primary_photo else "sendMessage",
                "photo": primary_photo,
                "caption": short_caption(localize_text("Vineyard risk report", language), message),
                "text_after_photo": "",
                "media": attachments,
            },
            "notification": notification,
            "must_attach_image": bool(attachments),
            "must_send_text": bool(message),
            "must_send_exactly": True,
            "full_reports_omitted": True,
        }
    days = params.get("days", 31)
    notify_mode = str(params.get("notify_mode") or "").lower()
    reports = []
    attachments = []
    combined_parts = []
    alert_reports = []
    for disease in ("downy_mildew", "powdery_mildew"):
        report = standard_report({
            **params,
            "field": field,
            "disease": disease,
            "days": days,
            "notify": False,
        })
        reports.append(report)
        state = report.get("dashboard_state") or {}
        history = state.get("history") or []
        latest = history[-1] if history else {}
        alert = call_skill("risk_alert_policy", {
            "status": {"result": {"rows": [latest]}},
            "disease": disease,
            "memory_path": params.get("memory_path") or f"/tmp/vineyard_alert_memory_{disease}.json",
            "high_threshold": params.get("high_threshold", 70),
            "watch_threshold": params.get("watch_threshold", 50),
            "delta_threshold": params.get("delta_threshold", 15),
            "cooldown_hours": params.get("cooldown_hours", 24),
            "update_memory": notify_mode in {"risk_only", "alerts_only"},
        }, 30) if latest else {"status": "skipped", "notify": False, "reason": "no latest row"}
        current_notify = bool(alert.get("notify"))
        future_alert = forecast_high_signal(report, params.get("high_threshold", 70))
        if future_alert.get("notify"):
            alert = {
                **alert,
                "notify": True,
                "severity": "high",
                "current_notify": current_notify,
                "reason": (
                    f"forecast {future_alert.get('key')} reaches "
                    f"{format_percent(future_alert.get('risk'))} on {future_alert.get('day')}"
                ),
                "forecast_alert": future_alert,
            }
        else:
            alert = {**alert, "current_notify": current_notify}
        report["risk_alert_policy"] = alert
        if alert.get("notify"):
            alert_reports.append(report)
        title = ((report.get("report") or {}).get("title") or disease.replace("_", " ").title())
        text = report.get("send_text") or ((report.get("telegram") or {}).get("text_after_photo")) or ""
        if text:
            append_unique_text(combined_parts, text)
        image_path = report.get("send_photo_path") or report.get("send_image_path") or report.get("plot_path")
        if image_path:
            attachments.append({
                "type": "photo",
                "path": image_path,
                "source_path": report.get("source_image_path") or image_path,
                "caption": short_caption(title, text),
                "mime_type": "image/png",
                "exists": os.path.exists(image_path),
                "disease": disease,
            })
    attachments = unique_by_path(attachments)
    ok_reports = [report for report in reports if report.get("status") == "success"]
    repo_path = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
    language = preferred_language(repo_path, field, params)
    incomplete_reports = [report for report in reports if report.get("status") != "success"]
    if incomplete_reports and not alert_reports:
        cache_message = cache_incomplete_message(repo_path, [field], language)
        cache_message = localize_text(cache_message, language)
        return {
            "status": "cache_missing",
            "mode": "both_disease_report",
            "field": field,
            "days": days,
            "notify_mode": notify_mode,
            "notify": False,
            "has_alert": False,
            "alert_diseases": [],
            "language": language,
            "reason": "today cache incomplete; refusing to classify missing disease reports as low risk",
            "send_text": cache_message,
            "attachments": [],
            "media": [],
            "telegram": {
                "method": "sendMessage",
                "caption": short_caption(localize_text("Vineyard risk summary", language), cache_message),
                "text_after_photo": cache_message,
                "media": [],
            },
            "reports": [compact_report_summary(report) for report in reports],
            "must_attach_image": False,
            "must_send_text": True,
            "must_send_exactly": True,
            "full_reports_omitted": True,
        }
    if alert_reports:
        message = risk_alert_summary_message(
            field,
            reports,
            alert_reports,
            params.get("high_threshold", 70),
            repo_path,
        )
    else:
        message = low_risk_summary_message(field, reports, repo_path)
    message = localize_text(message, language)
    attachments = localize_media(attachments, language)
    if notify_mode in {"risk_only", "alerts_only"}:
        if not alert_reports:
            send_low_summary = str(
                params.get("send_low_summary") or params.get("low_summary") or "false"
            ).lower() == "true"
            if send_low_summary:
                low_message = localize_text(
                    low_risk_summary_message(field, reports, params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"),
                    language,
                )
                notification = call_skill("farmer_notify", {
                    "title": localize_text("Vineyard risk summary", language),
                    "message": low_message,
                    "caption": short_caption(localize_text("Vineyard risk summary", language), low_message),
                    "attachments": [],
                    "media": [],
                    "delivery_group": params.get("delivery_group") or "",
                    "dispatch_role": "field_ok",
                    "language": language,
                    "field": field,
                    "has_alert": False,
                    "alert_diseases": [],
                    "notify_mode": notify_mode,
                    "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
                    "channel": params.get("channel") or "picoclaw_telegram",
                }, 30)
                return {
                    "status": "success",
                    "mode": "both_disease_report",
                    "field": field,
                    "days": days,
                    "notify_mode": notify_mode,
                    "notify": True,
                    "has_alert": False,
                    "alert_diseases": [],
                    "language": language,
                    "reason": "no high-risk alert; sent low-risk summary only",
                    "send_text": low_message,
                    "attachments": [],
                    "media": [],
                    "telegram": {
                        "method": "sendMessage",
                        "caption": short_caption(localize_text("Vineyard risk summary", language), low_message),
                        "text_after_photo": low_message,
                        "media": [],
                    },
                    "notification": notification,
                    "reports": [compact_report_summary(report) for report in reports],
                    "must_attach_image": False,
                    "must_send_text": True,
                    "must_send_exactly": True,
                    "full_reports_omitted": True,
                }
            return {
                "status": "success",
                "mode": "both_disease_report",
                "field": field,
                "days": days,
                "notify_mode": notify_mode,
                "notify": False,
                "has_alert": False,
                "alert_diseases": [],
                "language": language,
                "reason": "no risk alert or treatment signal after daily refresh",
                "reports": [compact_report_summary(report) for report in reports],
                "must_send_exactly": True,
                "full_reports_omitted": True,
            }
        alert_titles = []
        alert_diseases = set()
        for report in alert_reports:
            title = ((report.get("report") or {}).get("title") or "Vineyard alert")
            alert_titles.append(title)
            alert_diseases.add((report.get("report") or {}).get("disease") or "")
        message = localize_text(
            risk_alert_summary_message(field, reports, alert_reports, params.get("high_threshold", 70), repo_path),
            language,
        )
    primary_photo = attachments[0]["path"] if attachments else ""
    primary_caption = attachments[0]["caption"] if attachments else short_caption(localize_text("Vineyard risk report", language), message)
    if alert_reports:
        primary_caption = short_caption(localize_text("Vineyard treatment watch", language), message)
    notification = {"status": "skipped", "reason": "notify=false"}
    alert_disease_ids = [
        (report.get("disease") or (report.get("report") or {}).get("disease") or "")
        for report in alert_reports
    ]
    alert_disease_ids = [disease for disease in alert_disease_ids if disease]
    should_notify = (
        str(params.get("notify", "false")).lower() == "true"
        or bool(notify_mode in {"risk_only", "alerts_only"} and alert_reports)
    )
    if should_notify:
        package_caption = short_caption(
            localize_text("Vineyard treatment watch" if alert_reports else "Vineyard risk report", language),
            message,
        )
        notification = call_skill("farmer_notify", {
            "title": localize_text("Vineyard risk report", language),
            "message": message,
            "caption": package_caption,
            "text_after_photo": message if attachments and alert_reports else "",
            "plot_path": primary_photo if attachments else "",
            "image_path": primary_photo if attachments else "",
            "attachments": attachments,
            "media": attachments,
            "delivery_group": params.get("delivery_group") or "",
            "dispatch_role": "field_alert" if alert_reports else "single_report",
            "field": field,
            "has_alert": bool(alert_reports),
            "alert_diseases": alert_disease_ids,
            "notify_mode": notify_mode,
            "language": language,
            "outbox_dir": params.get("outbox_dir") or "/tmp/picoclaw_outbox",
            "channel": params.get("channel") or "picoclaw_telegram",
        }, 30)
        if notification.get("attachments"):
            attachments = notification.get("attachments") or attachments
            primary_photo = notification.get("photo_path") or notification.get("image_path") or primary_photo
            primary_caption = notification.get("caption") or primary_caption
    return {
        "status": "success" if len(ok_reports) == 2 and len(attachments) == 2 else "partial",
        "mode": "both_disease_report",
        "field": field,
        "days": days,
        "notify_mode": notify_mode,
        "notify": bool(notify_mode in {"risk_only", "alerts_only"} and alert_reports),
        "has_alert": bool(alert_reports),
        "alert_diseases": alert_disease_ids,
        "language": language,
        "send_text": message,
        "send_image_path": primary_photo,
        "send_photo_path": primary_photo,
        "attachment_path": primary_photo,
        "attachments": attachments,
        "media": attachments,
        "telegram": {
            "method": "sendMediaGroup" if len(attachments) > 1 else "sendPhoto" if primary_photo else "sendMessage",
            "photo": primary_photo,
            "caption": primary_caption,
            "text_after_photo": message if notify_mode in {"risk_only", "alerts_only"} else "",
            "media": attachments,
        },
        "notification": notification,
        "must_attach_image": bool(attachments),
        "must_send_text": bool(message),
        "must_send_exactly": True,
        "reports": [compact_report_summary(report) for report in reports],
        "full_reports_omitted": True,
        "delivery_contract": (
            "Generic vineyard risk reports must send both disease PNG attachments "
            "immediately. Do not answer with text only and do not ask the user to request plots."
        ),
    }


def daily_briefing(params):
    disease = params.get("disease") or ""
    if disease in {"downy_mildew", "powdery_mildew"}:
        report = standard_report({**params, "notify": params.get("notify", False)})
    else:
        clean_params = {key: value for key, value in params.items() if key != "disease"}
        report = both_disease_report({**clean_params, "notify": params.get("notify", False)})
    report["mode"] = "daily_briefing"
    report["daily_cache_policy"] = {
        "valid_for": "one calendar day",
        "requires_fresh_plot": True,
        "requires_all_model_layers": True,
        "regenerate_when": "missing plot, stale history, stale Rossi, stale powdery UC, stale powdery PMI",
    }
    return report


def main():
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    env_params = {
        "mode": os.environ.get("SKILL_MODE", ""),
        "field": os.environ.get("SKILL_FIELD", ""),
        "disease": os.environ.get("SKILL_DISEASE", ""),
        "days": int(os.environ.get("SKILL_DAYS", "31")),
        "notify": os.environ.get("SKILL_NOTIFY", "false").lower() in {"1", "true", "yes"},
        "notify_mode": os.environ.get("SKILL_NOTIFY_MODE", ""),
        "send_low_summary": os.environ.get("SKILL_SEND_LOW_SUMMARY", "false").lower() in {"1", "true", "yes"},
        "cache_only": os.environ.get("SKILL_CACHE_ONLY", "false").lower() in {"1", "true", "yes"},
        "board_only": os.environ.get("SKILL_BOARD_ONLY", "true").lower() in {"1", "true", "yes"},
        "channel": os.environ.get("SKILL_CHANNEL", "picoclaw_telegram"),
    }
    if raw.strip():
        try:
            params = json.loads(raw)
        except json.JSONDecodeError:
            text = raw.strip()
            lower = text.lower()
            params = {**env_params, "mode": "both_disease_report", "raw_text": text}
            if any(term in lower for term in ("powdery", "oidi", "oïdi", "oidium", "pmi")):
                params["mode"] = "standard_report"
                params["disease"] = "powdery_mildew"
            if any(term in lower for term in ("downy", "mildiu", "goidanich", "rossi")) and not any(term in lower for term in ("powdery", "oidi", "oïdi", "oidium", "pmi")):
                params["mode"] = "standard_report"
                params["disease"] = "downy_mildew"
            if params.get("mode") == "both_disease_report" and params.get("field"):
                repo = params.get("repo_path") or "/root/.picoclaw/workspace/goidanich"
                if not field_is_explicitly_mentioned(repo, text, params.get("field")):
                    params["field"] = ""
    else:
        params = env_params
    mode = params.get("mode") or "intent_required"
    if mode == "intent_required":
        # Defensive default for picoClaw/Telegram mistakes: if the LLM calls the
        # skill without forwarding JSON, stay silent. Do not leak an internal
        # error and do not generate a partial farmer report from missing intent.
        result = {
            "status": "skipped",
            "mode": "intent_required",
            "reason": "empty skill payload; no farmer-facing message sent",
            "notify": False,
            "send_text": "",
            "attachments": [],
            "media": [],
            "telegram": {"method": "sendMessage", "text_after_photo": "", "media": []},
            "must_send_text": False,
            "must_attach_image": False,
            "must_send_exactly": True,
        }
    elif mode == "trigger_daily_update":
        result = {"status": "success", "mode": mode, "daily": trigger_daily_update(params)}
    elif mode == "get_current_risk":
        result = {"status": "success", "mode": mode, "current_status": get_current_risk(params)}
    elif mode in {"run_board_prediction", "board_predict"}:
        result = {"status": "success", "mode": mode, "prediction": run_board_prediction(params)}
    elif mode == "generate_period_plot":
        result = {"mode": mode, **generate_period_plot(params)}
    elif mode == "evaluate_alert_policy":
        result = {"status": "success", "mode": mode, "alert": evaluate_alert_policy(params)}
    elif mode == "optionally_capture_canopy_photo":
        alert = params.get("alert") or {"notify": True}
        result = {"status": "success", "mode": mode, "photo": optionally_capture_canopy_photo(params, alert)}
    elif mode == "package_farmer_alert":
        packaged = package_farmer_alert(params)
        result = {"mode": mode, **packaged}
    elif mode in {"both_disease_report", "generic_report", "risc_report", "risk_report"}:
        result = both_disease_report(params)
    elif mode in {"standard_report", "farmer_report", "vineyard_guard", "send_standard_report", "telegram_report"}:
        result = standard_report(params)
    elif mode in {"daily_briefing", "run_daily_guard"}:
        result = daily_briefing(params)
    else:
        result = {"status": "error", "mode": mode, "message": f"unknown mode: {mode}"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
