#!/usr/bin/env python3
import json
import sys


def load_params():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


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
        "1. Identify target disease: downy, powdery, or both.",
        "2. Read current risk: downy uses Goidanich/Rossi; powdery uses UC risk plus PMI.",
        "3. Check forecast: projections are warning context, not observed infection.",
        "4. Check treatment history: product, date, dose, water volume, area, method.",
        "5. Scout canopy: clean, symptoms, false alarm, or confirmed disease grade.",
        "6. If protected recently and label rain/interval limits are still valid, monitoring may be enough.",
        "7. If PMI/reapplication or high-risk signal remains and protection is not current, ask farmer/agronomist to confirm product choice and label dose.",
        "8. Record confirmed treatment only after product/catalog/code and quantities are confirmed.",
    ]


def main():
    params = load_params()
    disease = str(params.get("disease") or "both").lower()
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
