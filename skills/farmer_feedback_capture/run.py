#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata

try:
    import yaml
except Exception:
    yaml = None


AREA_RE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>ha|hect(?:a|à)?rees?|hectareas?|m2|m²)\b", re.I)
QTY_RE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|l|L|ml|cc)\b(?:\s*(?:/|per|por|per\s+a|par)\s*ha\b)?", re.I)
PRODUCT_SPLIT_RE = re.compile(r"\s*(?:,|\+|\band\b|\bi\b|\by\b|\bamb\b|\bcon\b)\s*", re.I)

PRODUCT_SYNONYMS = {
    "sulfur": ["sulfur", "sulphur", "sofre", "azufre"],
    "sulphur": ["sulfur", "sulphur", "sofre", "azufre"],
    "sofre": ["sulfur", "sulphur", "sofre", "azufre"],
    "azufre": ["sulfur", "sulphur", "sofre", "azufre"],
    "copper": ["copper", "coure", "cobre"],
    "coure": ["copper", "coure", "cobre"],
    "cobre": ["copper", "coure", "cobre"],
    "bicarbonate": ["bicarbonate", "bicarbonat", "bicarbonato"],
    "bicarbonat": ["bicarbonate", "bicarbonat", "bicarbonato"],
    "bicarbonato": ["bicarbonate", "bicarbonat", "bicarbonato"],
}

FIELD_WORDS_RE = re.compile(r"\b(field|camp|campo|parcel(?:·|l)?a|plot|block|bloc|bloque)\b", re.I)


def env(name, default=""):
    return os.environ.get(f"SKILL_{name}", os.environ.get(name, default)).strip()


def as_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalize_catalog_text(value):
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^A-Za-z0-9]+", " ", raw.lower())
    return " ".join(raw.split())


def repo_path():
    return env("REPO_PATH", "/root/.picoclaw/workspace/goidanich")


def load_configured_fields():
    config_path = os.path.join(repo_path(), "agent_config.yaml")
    if not yaml or not os.path.exists(config_path):
        return []
    try:
        config = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
    except Exception:
        return []
    return config.get("fields") or []


def field_aliases(field):
    aliases = {
        field.get("id", ""),
        field.get("name", ""),
        field.get("location", ""),
        (field.get("metadata") or {}).get("block", ""),
    }
    name = str(field.get("name") or "")
    if name:
        aliases.add(name.replace("_", " "))
        aliases.add(name.split()[0])
    field_id = str(field.get("id") or "")
    if field_id:
        aliases.add(field_id.replace("_", " "))
    return [alias for alias in aliases if str(alias or "").strip()]


def infer_field(text):
    explicit = env("FIELD")
    fields = load_configured_fields()
    if explicit:
        return explicit, fields
    text_norm = normalize_catalog_text(text)
    matches = []
    for field in fields:
        best = 0
        for alias in field_aliases(field):
            alias_norm = normalize_catalog_text(alias)
            if not alias_norm:
                continue
            if re.search(rf"\b{re.escape(alias_norm)}\b", text_norm):
                best = max(best, len(alias_norm))
        if best:
            matches.append((best, field))
    matches.sort(key=lambda item: item[0], reverse=True)
    if matches:
        return matches[0][1].get("id", ""), fields
    if len(fields) == 1:
        return fields[0].get("id", ""), fields
    return "", fields


def strip_field_terms(text, fields):
    cleaned = text
    for field in fields:
        for alias in sorted(field_aliases(field), key=len, reverse=True):
            if not alias:
                continue
            cleaned = re.sub(rf"\b{re.escape(alias)}\b", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split())


def compact_code(value):
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "").upper())


def unit_to_base(value, unit):
    unit = unit.lower().replace("²", "2")
    if unit == "g":
        return value / 1000.0, "kg"
    if unit in {"ml", "cc"}:
        return value / 1000.0, "L"
    if unit == "l":
        return value, "L"
    return value, unit


def area_to_ha(value, unit):
    unit = unit.lower().replace("²", "2")
    if unit == "m2":
        return value / 10000.0
    return value


def product_family(name):
    lower = name.lower()
    if any(w in lower for w in ("sulfur", "sulphur", "sofre", "azufre")):
        return "sulfur"
    if any(w in lower for w in ("copper", "coure", "cobre")):
        return "copper"
    if any(w in lower for w in ("bicarbonate", "bicarbonat")):
        return "bicarbonate"
    if any(w in lower for w in ("bio", "bacillus", "trichoderma")):
        return "biocontrol"
    return "fungicide"


def ensure_product_catalog(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_catalog (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            product TEXT,
            lot TEXT,
            description TEXT,
            search_text TEXT,
            source TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT
        )
        """
    )


def product_match_score(query, row):
    query_norm = normalize_catalog_text(query)
    haystack = normalize_catalog_text(" ".join(str(row.get(k) or "") for k in ("id", "name", "product", "lot", "description")))
    if not query_norm or not haystack:
        return 0.0
    query_code = compact_code(query_norm)
    codes = {compact_code(row.get("id")), compact_code(row.get("name")), compact_code(row.get("lot"))}
    if query_code and query_code in codes:
        return 1.0
    if query_norm in haystack:
        return 0.95
    q_words = set(query_norm.split())
    h_words = set(haystack.split())
    overlap = len(q_words & h_words) / max(1, len(q_words))
    name_words = set(normalize_catalog_text(row.get("name")).split())
    name_overlap = len(q_words & name_words) / max(1, len(q_words))
    return max(overlap * 0.9, name_overlap * 0.95)


def search_product_catalog(product_name, limit=5):
    repo = repo_path()
    db_path = env("DB_PATH", os.path.join(repo, "goidanich.db"))
    if not os.path.exists(db_path):
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_product_catalog(conn)
        rows = [dict(row) for row in conn.execute(
            """
            SELECT id, name, product, lot, description
            FROM product_catalog
            WHERE active = 1
            """
        )]
    queries = [product_name]
    normalized = normalize_catalog_text(product_name)
    for word in normalized.split():
        queries.extend(PRODUCT_SYNONYMS.get(word, []))
    seen_queries = []
    for query in queries:
        if query and query not in seen_queries:
            seen_queries.append(query)
    matches_by_id = {}
    for row in rows:
        best_score = 0.0
        for query in seen_queries:
            best_score = max(best_score, product_match_score(query, row))
        if best_score >= 0.35:
            candidate = dict(row)
            candidate["match_score"] = round(best_score, 4)
            candidate["confirmed_match"] = best_score >= 0.98
            existing = matches_by_id.get(candidate["id"])
            if not existing or candidate["match_score"] > existing["match_score"]:
                matches_by_id[candidate["id"]] = candidate
    matches = list(matches_by_id.values())
    matches.sort(key=lambda item: (-item["match_score"], item["name"], item["id"]))
    return matches[:limit]


def normalize_product_name(raw):
    name = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|L|ml|cc|ha|m2|m²)\b", "", raw, flags=re.I)
    name = re.sub(r"\b(reg|n[úu]m(?:ero)?|num(?:ber)?|lot|lote)[:#\s-]*[A-Za-z0-9_.-]+\b", "", name, flags=re.I)
    name = re.sub(r"\b(i|we|she|they|sprayed|spray|applied|apply|treated|treat|pulveritzat|sulfat|aplicat|aplicado|apliqué|aplique|tractat|tratado|traté|trate|yesterday|today|ahir|avui|ayer|hoy|with|amb|con|de|del|en|para|per|por|for|oidio|oidi|oïdi|mildiu|míldiu|mildew|hectares?|hect[aà]rees?|ha)\b", " ", name, flags=re.I)
    name = re.sub(r"\bhe\b", " ", name, flags=re.I)
    return " ".join(name.strip(" .;:-").split())


def product_hint_from_text(text):
    lower = normalize_catalog_text(text)
    for canonical, terms in PRODUCT_SYNONYMS.items():
        if any(re.search(rf"\b{re.escape(normalize_catalog_text(term))}\b", lower) for term in terms):
            return canonical
    return ""


def is_water_volume(part, qty):
    unit = qty.group("unit").lower()
    if unit not in {"l", "ml", "cc"}:
        return False
    lower = part.lower()
    value = as_float(qty.group("value")) or 0
    if re.search(r"\b(water|aigua|agua|caldo|volume|volum)\b", lower):
        return True
    return value >= 50 and re.search(r"\b(?:/|per|por)\s*ha\b", lower)


def quantity_is_per_ha(part, qty):
    lower = part.lower()
    explicit_total = re.search(
        r"\b(total|overall|whole\s+field|for\s+the\s+field|tota\s+la\s+parcel|toda\s+la\s+parcela|en\s+total)\b",
        lower,
    )
    if explicit_total:
        return False
    explicit_per_ha = re.search(r"\b(?:/|per|por|per\s+a|par)\s*ha\b", qty.group(0), re.I)
    if explicit_per_ha:
        return True
    default_per_ha = env("APPLICATIONS_PER_HA", "true").lower()
    return default_per_ha not in {"0", "false", "no", "off"}


def parse_products(text, area_ha):
    products = []
    water_volume = env("WATER_VOLUME")
    pending_product = product_hint_from_text(text)
    for part in PRODUCT_SPLIT_RE.split(text):
        if not part.strip():
            continue
        qty = QTY_RE.search(part)
        name = normalize_product_name(part)
        if not qty:
            hint = product_hint_from_text(part)
            if hint:
                pending_product = hint
            continue
        if is_water_volume(part, qty):
            water_volume = f"{qty.group('value').replace(',', '.')} {unit_to_base(as_float(qty.group('value')), qty.group('unit'))[1]}/ha"
            continue
        if not name:
            name = pending_product
        hint = product_hint_from_text(part)
        if hint and (not name or FIELD_WORDS_RE.search(name)):
            name = hint
        if not name:
            continue
        value = as_float(qty.group("value"))
        unit = qty.group("unit")
        base_value, base_unit = unit_to_base(value, unit)
        per_ha = quantity_is_per_ha(part, qty)
        item = {
            "product": name,
            "quantity": value,
            "unit": unit,
            "quantity_base": round(base_value, 6),
            "unit_base": base_unit,
            "dose_is_per_ha": bool(per_ha),
            "original": part.strip(),
        }
        matches = search_product_catalog(name)
        if matches:
            item["catalog_matches"] = matches
            if matches[0].get("confirmed_match"):
                item["catalog_confirmed"] = True
                item["catalog_id"] = matches[0]["id"]
                item["product_number"] = matches[0]["id"]
                item["product"] = matches[0]["name"]
                item["product_composition"] = matches[0].get("product")
                item["lot"] = item.get("lot") or matches[0].get("lot")
                item["target_from_catalog"] = matches[0].get("description")
        if per_ha:
            item["quantity_per_ha"] = round(base_value, 6)
            item["unit_per_ha"] = f"{base_unit}/ha"
            item["dose"] = f"{base_value:g} {base_unit}/ha"
        elif area_ha:
            item["quantity_per_ha"] = round(base_value / area_ha, 6)
            item["unit_per_ha"] = f"{base_unit}/ha"
            item["dose"] = f"{item['quantity_per_ha']:g} {base_unit}/ha"
        products.append(item)
        pending_product = ""
    return products, water_volume


def infer_feedback_type(text):
    lower = text.lower()
    if any(w in lower for w in ("treated", "sprayed", "applied", "tractat", "tractament", "aplicat", "aplicado", "sulfat", "pulveritzat", "traté", "tratado", "apliqué", "aplique", "tratamiento")):
        return "treatment"
    if any(w in lower for w in (
        "clean", "net", "no mildew", "sense míldiu", "sin mildiu", "no oidi", "no oïdi",
        "cap símptoma", "cap simptoma", "sense símptomes", "sense simptomes",
        "sin síntomas", "sin sintomas", "no symptoms", "no symptom", "no signs",
    )):
        return "clean_inspection"
    if any(w in lower for w in (
        "false alarm", "false positive", "falsa alarma", "falso positivo",
        "fals avís", "fals avis", "falsa alerta", "fals positiu",
    )):
        return "false_alarm"
    if any(w in lower for w in ("not inspected", "no inspeccionat", "no inspeccionado")):
        return "not_inspected"
    grade = re.search(r"\b(?:grade|grau|grado)\s*([0-4])\b", lower)
    if grade:
        return "grade", int(grade.group(1))
    if any(w in lower for w in (
        "black rot", "black-rot", "blackrot", "guignardia", "bidwellii",
        "phyllosticta ampelicida",
    )):
        return "detected_black_rot"
    if any(w in lower for w in (
        "compatible symptoms", "símptomes compatibles", "simptomes compatibles",
        "síntomas compatibles", "sintomas compatibles", "lesions compatibles",
        "mildew", "míldiu", "mildiu", "oidi", "oïdi", "oidio",
        "black rot", "guignardia", "bidwellii",
    )):
        return "detected_mildew"
    return ""


def infer_disease(text):
    lower = text.lower()
    if any(w in lower for w in (
        "black rot", "black-rot", "blackrot", "guignardia", "bidwellii",
        "phyllosticta ampelicida",
    )):
        return "black_rot"
    if any(w in lower for w in ("powdery", "oidi", "oïdi", "oidio")):
        return "powdery_mildew"
    if any(w in lower for w in ("downy", "mildiu", "míldiu", "mildio")):
        return "downy_mildew"
    return env("DISEASE")


def feedback_language(text):
    lower = text.lower()
    if any(word in lower for word in (
        "símptoma", "simptoma", "míldiu", "oïdi", "fals avís", "cap ",
        "sense ", "camp", "tractament", "aplicat", "confirmeu",
    )):
        return "ca"
    if any(word in lower for word in (
        "síntoma", "sintoma", "mildiu", "oidio", "falsa alarma", "sin ",
        "campo", "tratamiento", "aplicado", "confirme",
    )):
        return "es"
    return "en"


def parse_raw_feedback(text):
    language = feedback_language(text)
    inferred_field, configured_fields = infer_field(text)
    product_text = strip_field_terms(text, configured_fields)
    area_match = AREA_RE.search(text)
    area_ha = None
    area_text = ""
    if area_match:
        area_ha = area_to_ha(as_float(area_match.group("value")), area_match.group("unit"))
        area_text = f"{area_ha:g} ha"

    feedback = infer_feedback_type(text)
    grade = None
    if isinstance(feedback, tuple):
        feedback, grade = feedback

    disease = infer_disease(text)
    if disease == "black_rot" and feedback == "detected_mildew":
        feedback = "detected_black_rot"
    products, water_volume = parse_products(product_text, area_ha)
    treatment_type = product_family(" ".join(p["product"] for p in products)) if products else ""
    all_product_doses_per_ha = bool(products) and all(p.get("dose_is_per_ha") for p in products)
    area_display = area_text or ("not required; doses are per ha" if all_product_doses_per_ha else "")
    product_summary = ", ".join(
        f"{p['product']} {p.get('dose') or str(p['quantity']) + ' ' + p['unit']}" for p in products
    )

    missing = []
    if not inferred_field:
        missing.append("field")
    if not feedback:
        missing.append("feedback_type")
    if not disease:
        missing.append("disease")
    if feedback == "treatment":
        if not products:
            missing.append("products_and_quantities")
        unresolved = [p for p in products if not p.get("catalog_confirmed")]
        if unresolved:
            missing.append("product_catalog_confirmation")
        if not area_ha and not all_product_doses_per_ha:
            missing.append("treated_area")

    draft = {
        "field": inferred_field,
        "disease": disease,
        "feedback_type": feedback,
        "grade": grade,
        "area": area_text,
        "area_ha": area_ha,
        "method": "spray" if re.search(r"\b(spray|sprayed|pulver|sulfat)\b", text, re.I) else env("METHOD"),
        "water_volume": water_volume,
        "target": disease,
        "treatment_type": treatment_type,
        "products": products,
        "products_json": json.dumps(products, ensure_ascii=False),
        "notes": text.strip(),
    }

    copy = {
        "ca": {
            "missing_product": "No trobo '{product}' al catàleg de productes.",
            "candidate": "Per a '{product}', volíeu dir: {choices}?",
            "field": " Quin camp s'ha tractat? Trieu-ne un: {choices}.",
            "treatment": "Confirmeu abans de desar aquest tractament",
            "feedback": "Confirmeu abans de desar aquesta observació",
            "reply": "Responeu amb el nom/codi exacte del producte i «confirmo» si és correcte, o corregiu les dades que falten.",
        },
        "es": {
            "missing_product": "No encuentro '{product}' en el catálogo de productos.",
            "candidate": "Para '{product}', ¿quería decir: {choices}?",
            "field": " ¿Qué campo se trató? Elija uno: {choices}.",
            "treatment": "Confirme antes de guardar este tratamiento",
            "feedback": "Confirme antes de guardar esta observación",
            "reply": "Responda con el nombre/código exacto del producto y «confirmo» si es correcto, o corrija los datos que faltan.",
        },
        "en": {
            "missing_product": "I cannot find '{product}' in the product catalogue.",
            "candidate": "For '{product}', did you mean: {choices}?",
            "field": " Which field was treated? Choose one: {choices}.",
            "treatment": "Please confirm before I save this treatment",
            "feedback": "Please confirm before I save this feedback",
            "reply": "Reply with the exact product name/code and 'confirm' if correct, or correct the missing/wrong parts.",
        },
    }[language]

    if feedback == "treatment":
        candidate_text = ""
        unresolved = [p for p in products if not p.get("catalog_confirmed")]
        if unresolved:
            parts = []
            for product in unresolved:
                candidates = product.get("catalog_matches") or []
                if candidates:
                    choices = "; ".join(
                        f"{c['name']} (code {c['id']}, {c.get('description') or 'no target'})"
                        for c in candidates[:3]
                    )
                    parts.append(copy["candidate"].format(product=product["product"], choices=choices))
                else:
                    parts.append(copy["missing_product"].format(product=product["product"]))
            candidate_text = " " + " ".join(parts)
        field_text = ""
        if "field" in missing and configured_fields:
            choices = "; ".join(f"{field.get('name')} ({field.get('id')})" for field in configured_fields)
            field_text = copy["field"].format(choices=choices)
        confirm = (
            f"{copy['treatment']}: "
            f"field={draft['field'] or '<missing>'}; disease={disease}; "
            f"area={area_display or '<missing>'}; products={product_summary or '<missing>'}; "
            f"water={water_volume or '<missing>'}; method={draft['method'] or '<missing>'}."
            f"{field_text}{candidate_text} "
            f"{copy['reply']}"
        )
    else:
        confirm = (
            f"{copy['feedback']}: "
            f"field={draft['field'] or '<missing>'}; disease={disease}; "
            f"type={feedback or '<missing>'}; grade={grade if grade is not None else '-'}."
        )
    return draft, missing, confirm


def run_vineyard_risk(extra_env):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    skills_dir = os.path.dirname(base_dir)
    cmd = [os.path.join(skills_dir, "vineyard_disease_risk", "run.sh")]
    merged = os.environ.copy()
    merged.update(extra_env)
    proc = subprocess.run(cmd, env=merged, text=True, capture_output=True, timeout=900)
    try:
        stdout = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        stdout = proc.stdout
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": proc.stderr,
    }


def direct_env_from_existing():
    return {k: v for k, v in os.environ.items() if k.startswith("SKILL_")}


def main():
    raw = env("RAW_TEXT") or env("MESSAGE") or env("TEXT")
    confirmed = env("CONFIRMED", "false").lower() in {"1", "true", "yes", "confirm", "confirmed", "sí", "si"}

    if raw:
        draft, missing, confirmation = parse_raw_feedback(raw)
        result = {
            "status": "needs_confirmation" if missing or not confirmed else "ready_to_record",
            "mode": "parse_farmer_feedback",
            "draft": draft,
            "missing": missing,
            "confirmation_question": confirmation,
            "write_blocked_until_confirmed": not confirmed,
        }
        if missing or not confirmed:
            print(json.dumps(result, ensure_ascii=False))
            return
        unresolved = [p for p in draft.get("products", []) if not p.get("catalog_confirmed")]
        if unresolved:
            for product in unresolved:
                candidates = product.get("catalog_matches") or []
                if candidates and candidates[0].get("match_score", 0) >= 0.75:
                    chosen = candidates[0]
                    product["catalog_confirmed"] = True
                    product["catalog_id"] = chosen["id"]
                    product["product_number"] = chosen["id"]
                    product["product"] = chosen["name"]
                    product["product_composition"] = chosen.get("product")
                    product["lot"] = product.get("lot") or chosen.get("lot")
                    product["target_from_catalog"] = chosen.get("description")
                else:
                    result["status"] = "needs_confirmation"
                    result["missing"] = sorted(set(result.get("missing", []) + ["product_catalog_confirmation"]))
                    result["write_blocked_until_confirmed"] = True
                    print(json.dumps(result, ensure_ascii=False))
                    return
            draft["products_json"] = json.dumps(draft["products"], ensure_ascii=False)

        extra = {
            "SKILL_MODE": "record_feedback",
            "SKILL_REPO_PATH": env("REPO_PATH", "/root/.picoclaw/workspace/goidanich"),
            "SKILL_FIELD": draft["field"],
            "SKILL_DISEASE": draft["disease"],
            "SKILL_FEEDBACK_TYPE": draft["feedback_type"],
            "SKILL_NOTES": draft["notes"],
            "SKILL_AREA": draft["area"],
            "SKILL_METHOD": draft["method"],
            "SKILL_WATER_VOLUME": draft.get("water_volume", ""),
            "SKILL_TARGET": draft["target"],
            "SKILL_TREATMENT_TYPE": draft["treatment_type"],
            "SKILL_PRODUCTS_JSON": draft["products_json"],
        }
        for passthrough in ("SKIP_SUPABASE", "SKIP_DASHBOARD_UPDATE", "DB_PATH", "DAYS"):
            if env(passthrough):
                extra[f"SKILL_{passthrough}"] = env(passthrough)
        if draft["grade"] is not None:
            extra["SKILL_GRADE"] = str(draft["grade"])
        written = run_vineyard_risk(extra)
        result.update({"status": "success" if written["ok"] else "error", "recorded": written})
        print(json.dumps(result, ensure_ascii=False))
        return

    if not env("FEEDBACK_TYPE"):
        print(json.dumps({"status": "error", "message": "feedback_type or raw_text is required"}))
        sys.exit(1)
    extra = direct_env_from_existing()
    extra["SKILL_MODE"] = "record_feedback"
    result = run_vineyard_risk(extra)
    print(json.dumps({
        "status": "success" if result["ok"] else "error",
        "mode": "record_feedback",
        "result": result.get("stdout"),
        "stderr": result.get("stderr"),
    }, ensure_ascii=False))
    if not result["ok"]:
        sys.exit(result["returncode"] or 1)


if __name__ == "__main__":
    main()
