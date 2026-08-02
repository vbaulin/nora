import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "skills" / "black_rot_risk" / "run.py"
SPEC = importlib.util.spec_from_file_location("black_rot_risk_skill", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BlackRotRiskSkillTest(unittest.TestCase):
    def test_model_scope_is_grapevine_black_rot_not_secondary_bunch_rot(self):
        self.assertEqual(MODULE.MODEL_INFO["pathogen"], "Guignardia bidwellii")
        self.assertIn("secondary grape bunch rots", MODULE.MODEL_INFO["scope_excludes"])
        self.assertIn("Aspergillus spp.", MODULE.MODEL_INFO["scope_excludes"])

    def test_catalan_farmer_summary_uses_pathogen_qualified_name(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Avgvstvs Forum",
            "latest": {
                "day": "2026-07-29",
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "not_reported",
            },
            "forecast_prediction": {
                "max_infection_index": 0.0,
                "max_day": "2026-07-30",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("Black rot de la vinya (Guignardia bidwellii)", text)
        self.assertIn("no inclou les podridures secundàries", text)
        self.assertNotIn("🍇 Podridura negra", text)

    def test_full_catalan_report_states_secondary_rot_exclusion(self):
        field = {"id": "field_1", "location": "Avgvstvs Forum"}
        state = {
            "latest": {
                "day": "2026-07-29",
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "not_reported",
            },
            "forecast_prediction": {
                "max_infection_index": 0.0,
                "max_day": "2026-07-30",
            },
        }
        text = MODULE.message_for(field, state, "ca")
        self.assertTrue(text.startswith("🍇 Black rot de la vinya (Guignardia bidwellii)"))
        self.assertIn("no avalua les podridures secundàries", text)

    def test_unverified_guignardia_keeps_weather_signal_and_requests_feedback(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Avgvstvs Forum",
            "latest": {
                "day": "2026-08-01",
                "black_rot_infection_index": 105.0,
                "black_rot_inoculum_status": "unknown",
                "black_rot_wetness_driver": "humidity",
            },
            "forecast_prediction": {
                "first_infection_day": "2026-08-02",
                "max_infection_index": 150.0,
                "max_day": "2026-08-02",
                "wetness_driver": "humidity",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("possible finestra d'infecció avui", text)
        self.assertIn("Senyal meteorològic no confirmat", text)
        self.assertIn("fals avís", text)

    def test_multifield_labels_use_unique_field_names(self):
        field = {
            "id": "agent_la_granada_n1_chardonnay_01",
            "name": "N1 Chardonnay",
            "location": "La Granada",
        }
        self.assertEqual(MODULE.field_label(field, multi_field=True), "N1 Chardonnay")
        self.assertEqual(MODULE.field_label(field, multi_field=False), "La Granada")

    def test_catalan_wetness_evidence_distinguishes_humidity_from_rain(self):
        text = MODULE.wetness_evidence(
            {
                "wetness_driver": "humidity",
                "wet_hours": 8,
                "humidity_wet_hours": 8,
                "rain_wet_hours": 0,
                "max_humidity": 100.0,
            },
            "ca",
            forecast=True,
        )
        self.assertIn("8 h amb HR >=95%", text)
        self.assertIn("0 h amb pluja", text)
        self.assertIn("origen: humitat alta", text)

    def test_catalan_summary_warns_when_near_saturation_crosses_upper_bound(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Camp 1",
            "latest": {
                "day": "2026-07-14",
                "black_rot_infection_index": 0.0,
                "black_rot_potential_infection_index": 90.0,
                "black_rot_wetness_uncertain_watch": 1,
                "black_rot_near_saturation_hours": 6,
                "black_rot_max_humi": 94.0,
                "black_rot_inoculum_status": "present",
            },
            "forecast_prediction": {"max_infection_index": 0.0, "max_day": "2026-07-15"},
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("pot haver-hi rosada o fulla mullada", text)
        self.assertIn("Inspeccioneu les zones més humides avui", text)
        self.assertNotIn("graus-hora", text)
        self.assertNotIn("no current", text)

    def test_catalan_subthreshold_wet_period_is_yellow_not_green(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Avgvstvs Forum",
            "latest": {
                "day": "2026-07-14",
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "present",
            },
            "forecast_prediction": {
                "max_infection_index": 30.0,
                "max_day": "2026-07-15",
                "wet_hours": 2,
                "humidity_wet_hours": 2,
                "rain_wet_hours": 0,
                "max_humidity": 96.0,
                "wetness_driver": "humidity",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("🟡 Avgvstvs Forum", text)
        self.assertIn("període humit", text)
        self.assertIn("no indica una nova infecció", text)
        self.assertNotIn("graus-hora", text)
        self.assertNotIn("🟢 Avgvstvs Forum", text)

    def test_catalan_known_inoculum_without_new_event_is_not_green(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Avgvstvs Forum",
            "latest": {
                "day": "2026-07-14",
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "present",
            },
            "forecast_prediction": {
                "max_infection_index": 0.0,
                "max_day": "2026-07-15",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("🟡 Avgvstvs Forum", text)
        self.assertIn("no es preveu una nova infecció meteorològica", text)
        self.assertIn("Reviseu les zones amb símptomes coneguts", text)
        self.assertNotIn("🟢 Avgvstvs Forum", text)

    def test_catalan_current_subthreshold_period_is_not_replaced_by_dry_forecast(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "Avgvstvs Forum",
            "latest": {
                "day": "2026-07-14",
                "black_rot_infection_index": 30.0,
                "black_rot_wet_hours": 2,
                "black_rot_humidity_wet_hours": 2,
                "black_rot_rain_wet_hours": 0,
                "black_rot_wetness_driver": "humidity",
                "black_rot_max_humi": 96.0,
                "black_rot_inoculum_status": "present",
            },
            "forecast_prediction": {
                "max_infection_index": 0.0,
                "max_day": "2026-07-15",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("període humit", text)
        self.assertIn("Manteniu la inspecció rutinària", text)
        self.assertNotIn("HR >=95%", text)
        self.assertNotIn("🟢 Avgvstvs Forum", text)

    def test_catalan_humidity_only_threshold_crossing_is_a_proxy_watch(self):
        reports = [{
            "status": "success",
            "field": "field_1",
            "field_label": "N1 Chardonnay",
            "latest": {
                "day": "2026-07-14",
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "present",
            },
            "forecast_prediction": {
                "max_infection_index": 105.0,
                "max_day": "2026-07-15",
                "first_infection_day": "2026-07-15",
                "wet_hours": 7,
                "humidity_wet_hours": 7,
                "rain_wet_hours": 0,
                "max_humidity": 99.0,
                "wetness_driver": "humidity",
            },
        }]
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("risc elevat el 2026-07-15 per humitat nocturna molt alta", text)
        self.assertIn("Comproveu la humectació real del dosser", text)
        self.assertIn("alerta meteorològica, no una infecció confirmada", text)
        self.assertNotIn("graus-hora", text)
        self.assertNotIn("primer episodi previst", text)

    def test_identical_multifield_forecasts_are_collapsed_into_one_line(self):
        reports = []
        for number in range(1, 6):
            reports.append({
                "status": "success",
                "field": f"field_{number}",
                "field_label": f"N{number} Chardonnay",
                "latest": {
                    "day": "2026-07-14",
                    "black_rot_infection_index": 0.0,
                    "black_rot_inoculum_status": "present",
                },
                "forecast_prediction": {
                    "max_infection_index": 105.0,
                    "max_day": "2026-07-15",
                    "first_infection_day": "2026-07-15",
                    "wet_hours": 7,
                    "humidity_wet_hours": 7,
                    "rain_wet_hours": 0,
                    "max_humidity": 99.0,
                    "wetness_driver": "humidity",
                },
            })
        text = MODULE.daily_summary_for(reports, "ca")
        self.assertIn("N1 Chardonnay, N2 Chardonnay, N3 Chardonnay, N4 Chardonnay, N5 Chardonnay", text)
        self.assertEqual(text.count("risc elevat el 2026-07-15"), 1)
        self.assertIn("Decisió de tractament", text)


if __name__ == "__main__":
    unittest.main()
