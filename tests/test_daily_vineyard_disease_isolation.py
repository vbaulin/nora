import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "skills" / "daily_vineyard_briefing" / "run.py"
SPEC = importlib.util.spec_from_file_location("daily_vineyard_briefing_skill", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def report_for(disease):
    latest = {
        "field_id": "field_1",
        "day": "2026-07-14",
        "station": "D9",
        "baseline_risk": 22.0,
        "rossi_risk": 3.0,
        "powdery_risk": 64.0,
        "powdery_pmi": 5.0,
    }
    state = {
        "history": [latest],
        "forecast": [{
            "day": "2026-07-15",
            "goidanich_daily_projection": 25.0,
            "rossi_projection": 2.0,
            "powdery_projection": 72.0,
            "forecast_rain": 0.0,
        }],
    }
    path = f"/tmp/dashboard_latest_{disease}.png"
    media = [{"type": "photo", "path": path, "disease": disease, "exists": True}]
    return {
        "status": "success",
        "mode": "standard_report",
        "field": "field_1",
        "disease": disease,
        "dashboard_state": state,
        "send_text": f"full {disease} report",
        "send_photo_path": path,
        "attachments": media,
        "media": media,
        "telegram": {"method": "sendPhoto", "photo": path},
    }


class DailyVineyardDiseaseIsolationTest(unittest.TestCase):
    def test_catalan_localizer_repairs_legacy_mixed_overview(self):
        legacy = (
            "🍇 Míldiu overview\n"
            "No field has a current or forecast downy mildew alert today.\n"
            "Action: inspecció rutinària only; no forecast-driven treatment preparation from this model.\n"
            "Only powdery mildew plots are attached for the alert field(s)."
        )
        message = MODULE.localize_text(legacy, "ca")
        self.assertIn("🍇 Resum de míldiu", message)
        self.assertIn("Avui cap camp té una alerta actual o prevista de míldiu.", message)
        self.assertIn("Acció: només inspecció rutinària", message)
        self.assertIn("Només s'adjunten els gràfics d'oïdi", message)
        for fragment in ("overview", "No field", "Action:", " only", "Only "):
            self.assertNotIn(fragment, message)

    def test_catalan_fleet_summary_contains_no_english_fragments(self):
        message = MODULE.single_disease_fleet_message(
            "/tmp/repo", "downy_mildew", ["field_1"], [], [report_for("downy_mildew")], [], "ca"
        )
        self.assertIn("🍇 Míldiu", message)
        self.assertIn("Avui cap camp té una alerta actual o prevista de míldiu.", message)
        self.assertNotIn("overview", message)
        self.assertNotIn("No field", message)
        self.assertNotIn("Action:", message)
        self.assertNotIn(" only", message)

    def test_catalan_alert_forecast_contains_no_first_or_only(self):
        report = report_for("powdery_mildew")
        message = MODULE.single_disease_fleet_message(
            "/tmp/repo", "powdery_mildew", ["field_1"], [report], [], [], "ca"
        )
        self.assertIn("Risc moderat avui (64%)", message)
        self.assertIn("les condicions poden ser favorables a partir del 2026-07-15", message)
        self.assertIn("Acció avui: inspeccioneu fulles i raïms", message)
        self.assertIn("Només s'adjunten els gràfics d'oïdi", message)
        self.assertNotIn("UC ", message)
        self.assertNotIn("PMI ", message)
        self.assertNotIn(" first ", message)
        self.assertNotIn("Only ", message)

    def test_explicit_report_keeps_only_requested_disease_media(self):
        for disease in ("downy_mildew", "powdery_mildew"):
            with self.subTest(disease=disease):
                report = report_for(disease)
                other = "powdery_mildew" if disease == "downy_mildew" else "downy_mildew"
                report["media"].append({
                    "type": "photo",
                    "path": f"/tmp/{other}.png",
                    "disease": other,
                    "exists": True,
                })
                with mock.patch.object(MODULE, "standard_report", return_value=report), mock.patch.object(
                    MODULE, "evaluate_single_disease_alert", return_value={"notify": False}
                ), mock.patch.object(MODULE, "preferred_language", return_value="en"):
                    result = MODULE.single_disease_report({
                        "mode": "single_disease_report",
                        "field": "field_1",
                        "disease": disease,
                        "notify": False,
                    })
                self.assertEqual(result["disease"], disease)
                self.assertEqual({item["disease"] for item in result["media"]}, {disease})
                self.assertNotIn(other, result["send_text"])

    def test_risk_only_powdery_does_not_attach_downy_plot(self):
        report = report_for("powdery_mildew")
        report["media"].append({
            "type": "photo",
            "path": "/tmp/dashboard_latest_downy_mildew.png",
            "disease": "downy_mildew",
            "exists": True,
        })
        with tempfile.TemporaryDirectory() as repo, mock.patch.object(
            MODULE, "standard_report", return_value=report
        ), mock.patch.object(
            MODULE, "evaluate_single_disease_alert", return_value={"notify": True, "reason": "watch"}
        ), mock.patch.object(MODULE, "preferred_language", return_value="en"), mock.patch.object(
            MODULE, "configured_field_label", return_value="Field 1"
        ):
            result = MODULE.single_disease_report({
                "mode": "single_disease_report",
                "repo_path": repo,
                "field": "field_1",
                "disease": "powdery_mildew",
                "notify_mode": "risk_only",
                "notify": False,
                "package_notification": False,
            })
        self.assertTrue(result["has_alert"])
        self.assertEqual({item["disease"] for item in result["media"]}, {"powdery_mildew"})
        self.assertNotIn("Downy", result["send_text"])


if __name__ == "__main__":
    unittest.main()
