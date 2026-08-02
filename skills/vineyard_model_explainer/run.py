#!/usr/bin/env python3
import json
import sys


def load_params():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def language_from(params):
    explicit = str(params.get("language") or params.get("lang") or "").lower()
    if explicit.startswith("ca"):
        return "ca"
    if explicit.startswith("es"):
        return "es"
    if explicit.startswith("en"):
        return "en"

    text = str(params.get("raw_text") or "").lower()
    if any(marker in text for marker in (
        "podridura", "podridures", "vinya", "raïm", "refereixes",
        "secundàries", "causades", "quin", "quina", "gràfic",
    )):
        return "ca"
    if any(marker in text for marker in (
        "podredumbre", "podredumbres", "viña", "uva", "secundarias",
        "causadas", "cuál", "gráfico",
    )):
        return "es"
    return "en"


def rot_clarification(language):
    copy = {
        "ca": {
            "title": "Cal concretar quin tipus de podridura és",
            "message": (
                "El terme «podridura negra» és ambigu al context vitícola local. "
                "Pot indicar dues patologies diferents i no s'ha d'executar cap "
                "model fins que les distingim."
            ),
            "choices": [
                "Black rot de la vinya (Guignardia bidwellii / Phyllosticta ampelicida)",
                "Podridures secundàries del raïm, principalment Aspergillus spp., Penicillium spp. o altres fongs oportunistes",
            ],
            "question": (
                "Et refereixes al Black rot de la vinya per Guignardia bidwellii, "
                "o a les podridures secundàries del raïm?"
            ),
        },
        "es": {
            "title": "Hay que concretar el tipo de podredumbre",
            "message": (
                "El término «podredumbre negra» es ambiguo en el contexto vitícola "
                "local. Puede designar dos patologías distintas y no debe ejecutarse "
                "ningún modelo hasta diferenciarlas."
            ),
            "choices": [
                "Black rot de la vid (Guignardia bidwellii / Phyllosticta ampelicida)",
                "Podredumbres secundarias de la uva, principalmente Aspergillus spp., Penicillium spp. u otros hongos oportunistas",
            ],
            "question": (
                "¿Te refieres al black rot de la vid por Guignardia bidwellii o a "
                "las podredumbres secundarias de la uva?"
            ),
        },
        "en": {
            "title": "The rot type needs clarification",
            "message": (
                "The phrase 'black rot' can be ambiguous in local vineyard usage. "
                "These are two different disease complexes, so no model should run "
                "until the intended one is identified."
            ),
            "choices": [
                "Grapevine black rot (Guignardia bidwellii / Phyllosticta ampelicida)",
                "Secondary grape bunch rots, mainly Aspergillus spp., Penicillium spp., or other opportunistic fungi",
            ],
            "question": (
                "Do you mean grapevine black rot caused by Guignardia bidwellii, or "
                "secondary grape bunch rots?"
            ),
        },
    }[language]
    send_text = "\n".join([
        copy["message"],
        "",
        f"1. {copy['choices'][0]}",
        f"2. {copy['choices'][1]}",
        "",
        copy["question"],
    ])
    return {
        "status": "needs_clarification",
        "mode": "rot_clarification",
        "title": copy["title"],
        "message": copy["message"],
        "send_text": send_text,
        "choices": copy["choices"],
        "confirmation_question": copy["question"],
        "model_call_allowed": False,
    }


def treatment_line(history):
    if not history:
        return "No recent treatment record was provided; ask the farmer for product, date, dose, water volume, area, and method."
    latest = history[0]
    bits = [
        f"{latest.get('product') or 'product'} on {latest.get('date') or latest.get('timestamp') or 'unknown date'}"
    ]
    for key, label in (
        ("dose", "dose"),
        ("water_volume", "water"),
        ("area", "area"),
        ("method", "method"),
        ("product_number", "code"),
    ):
        if latest.get(key):
            bits.append(f"{label} {latest[key]}")
    return "Last treatment: " + "; ".join(bits) + "."


def decision_tree():
    return [
        "1. Identify target disease: downy, powdery, grapevine black rot, secondary bunch rot, or a combined report.",
        "2. Never map secondary bunch rots caused by Aspergillus/Penicillium to the Guignardia black-rot model.",
        "3. Read current risk: downy uses Goidanich/Rossi; powdery uses UC risk plus PMI.",
        "4. Check forecast: projections are warning context, not observed infection.",
        "5. Check treatment history: product, date, dose, water volume, area, method.",
        "6. Scout canopy: clean, symptoms, false alarm, or confirmed disease grade.",
        "7. If protected recently and label rain/interval limits are still valid, monitoring may be enough.",
        "8. If PMI/reapplication or high-risk signal remains and protection is not current, ask farmer/agronomist to confirm product choice and label dose.",
        "9. Record confirmed treatment only after product/catalog/code and quantities are confirmed.",
    ]


def main():
    params = load_params()
    disease = str(params.get("disease") or "both").lower()
    if disease in {
        "rot_clarification", "ambiguous_rot", "podridura negra",
        "podredumbre negra",
    }:
        print(json.dumps(rot_clarification(language_from(params)), ensure_ascii=False))
        return
    history = params.get("treatment_history") or []
    lines = ["🍇 Vineyard model explanation"]
    if disease in {"both", "downy_mildew", "downy", "mildiu"}:
        lines.extend([
            "",
            "Downy mildew",
            "- Goidanich daily risk is weather suitability for infection today.",
            "- Goidanich accumulated lines track infection-line development after rain events.",
            "- Rossi is a separate primary-infection comparison model.",
            "- A high accumulated/projection line is a warning context; it is not the same number as current daily risk.",
        ])
    if disease in {"both", "powdery_mildew", "powdery", "oidium", "oidi", "oïdi"}:
        lines.extend([
            "",
            "Powdery mildew",
            "- Powdery UC/Gubler-Thomas risk is the farmer-facing disease-pressure signal.",
            "- PMI is a treatment-timing index: first protection/reapplication support, not disease probability.",
            "- Forecast powdery projection can rise before current observed risk rises; use it as a watch signal.",
        ])
    if disease in {"black_rot", "black rot", "guignardia", "guignardia bidwellii"}:
        lines.extend([
            "",
            "Grapevine black rot (Guignardia bidwellii)",
            "- The infection index is degree-hours accumulated during leaf wetness; it is not disease probability.",
            "- Infection-event classes begin at 85 degree-hours (light), 150 (moderate), and above 300 (severe).",
            "- Leaf symptoms are projected after 175 bounded degree-days from an infection event.",
            "- A weather event is conditional on viable local inoculum; verify black-rot history and scout the field.",
            "- If leaf wetness is inferred from rain/RH rather than measured, retain that uncertainty in the decision.",
            "- This model does not assess secondary bunch rots caused by Aspergillus, Penicillium, or other opportunistic fungi.",
        ])
    if disease in {
        "secondary_rot", "secondary bunch rot", "secondary bunch rots",
        "aspergillus", "aspergillus niger", "penicillium",
    }:
        lines.extend([
            "",
            "Secondary grape bunch rots",
            "- These are distinct from grapevine black rot caused by Guignardia bidwellii.",
            "- The current Vineyard Guard deployment has no validated deterministic secondary-bunch-rot model.",
            "- Record organism/symptoms, berry damage, ripening stage, humidity, temperature, and treatment history before selecting or validating a dedicated model.",
        ])
    lines.extend([
        "",
        "Treatment logic",
        treatment_line(history),
        "Do not apply automatically from a model number. Confirm canopy, recent protection, label dose, water volume, treated area, and product code.",
    ])
    print(json.dumps({
        "status": "success",
        "title": "Vineyard model and treatment explainer",
        "message": "\n".join(lines),
        "decision_tree": decision_tree(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
