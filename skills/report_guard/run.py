#!/usr/bin/env python3
import json
import re
import sys


REQUIRED_SECTIONS = [
    "risk today",
    "general situation",
    "weather",
    "fungal pressure",
    "treatment",
    "evidence",
]


BAD_HIGH_WORDS = re.compile(r"\b(high|critical|urgent|immediate|treatment planning|treat(?:ment)?-?worthy)\b", re.I)
PLOT_PATH = re.compile(r"(/\S+\.(?:svg|png)|\S+\.(?:svg|png))", re.I)
BAD_POWDERY_GENERIC = re.compile(
    r"(powdery|oidi|oïdi|oidium)[\s\S]{0,240}"
    r"(general personalized risk|generic personalized risk|personalized risk is low|"
    r"personalized risk[:\s]+15(?:\.0)?%|15(?:\.0)?%[^.\n]{0,120}(low|general))",
    re.I,
)
BAD_POWDERY_HISTORICAL = re.compile(
    r"(powdery|oidi|oïdi|oidium)[\s\S]{0,260}"
    r"(historically|previous cycles|refer to|check the most recent specific powdery report)",
    re.I,
)


def rows_from_standard(report):
    alert = report.get("alert") or {}
    alerts = alert.get("alerts") or []
    return alerts


def risk_from_report(report):
    composed = report.get("report") or {}
    if isinstance(composed.get("risk"), (int, float)):
        return float(composed["risk"])
    for item in rows_from_standard(report):
        try:
            return float(item.get("risk"))
        except Exception:
            pass
    return None


def main():
    params = json.load(sys.stdin)
    report = params.get("report") or {}
    text = params.get("text") or (report.get("report") or {}).get("message") or ""
    lower = text.lower()
    failures = []

    risk = risk_from_report(report)
    if risk is not None and risk < 50 and BAD_HIGH_WORDS.search(text):
        failures.append(f"risk {risk:.1f}% is below 50%; report must not describe it as high/critical/urgent/treatment-worthy")

    if BAD_POWDERY_GENERIC.search(text):
        failures.append(
            "powdery mildew must not be reported from generic/personalized 15% risk; use powdery_risk, UC/Gubler-Thomas, PMI, and treatment_due from the current skill output"
        )
    if BAD_POWDERY_HISTORICAL.search(text):
        failures.append(
            "powdery mildew answer is relying on historical/session-memory wording instead of the current daily-vineyard-briefing payload"
        )
    if ("powdery" in lower or "oidi" in lower or "oïdi" in lower or "oidium" in lower) and not re.search(r"\b(pmi|uc|gubler|powdery uc|powdery_risk)\b", lower):
        failures.append("powdery mildew report must include current UC/powdery risk and PMI fields")

    missing = [section for section in REQUIRED_SECTIONS if section not in lower]
    if missing:
        failures.append("missing standardized sections: " + ", ".join(missing))

    plot_path = params.get("plot_path") or report.get("plot_path") or (report.get("plot") or {}).get("plot_path")
    if plot_path and plot_path not in text:
        failures.append("real plot path from standard_report is missing from text")
    if not plot_path and not PLOT_PATH.search(text):
        failures.append("report must include a real .svg or .png plot path, not a generic database reference")
    if "plot generated from" in lower and not PLOT_PATH.search(text):
        failures.append("generic plot evidence is not enough; include the actual plot file path")

    print(json.dumps({
        "status": "success" if not failures else "error",
        "valid": not failures,
        "risk": risk,
        "failures": failures,
        "message": "report is valid" if not failures else "report failed guard",
    }))


if __name__ == "__main__":
    main()
