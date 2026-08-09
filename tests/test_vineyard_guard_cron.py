import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "vineyard_guard_cron.py"
SPEC = importlib.util.spec_from_file_location("vineyard_guard_cron", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VineyardGuardCronTest(unittest.TestCase):
    def test_daily_refresh_trains_downy_and_powdery_after_cache_refresh(self):
        args = types.SimpleNamespace(
            days=31,
            high_threshold=70,
            watch_threshold=50,
            delta_threshold=15,
        )
        success = {"ok": True, "stdout": {"status": "success"}}
        with mock.patch.object(MODULE, "refresh_forecast_once", return_value={"ok": True}), mock.patch.object(
            MODULE, "configured_fields", return_value=["field_1"]
        ), mock.patch.object(
            MODULE, "call_daily", return_value=success
        ) as daily, mock.patch.object(
            MODULE, "call_black_rot", return_value=success
        ), mock.patch.object(
            MODULE,
            "train_personalized_models",
            return_value={
                "ok": True,
                "models": [
                    {"field": "field_1", "disease": "downy_mildew", "trained": False},
                    {"field": "field_1", "disease": "powdery_mildew", "trained": False},
                ],
                "failures": [],
            },
        ) as train:
            status = MODULE.mode_refresh(args)

        self.assertEqual(status, 0)
        self.assertEqual(daily.call_count, 2)
        train.assert_called_once()
        self.assertEqual(train.call_args.args[0], ["field_1"])

    def test_supabase_cycle_syncs_three_diseases_then_validates_released_models(self):
        sync = {"ok": True, "stdout": {"status": "success"}}
        with mock.patch.object(MODULE, "call_vineyard_risk", return_value=sync) as call, mock.patch.object(
            MODULE, "configured_fields", return_value=["field_1"]
        ), mock.patch.object(
            MODULE,
            "validate_shared_models",
            return_value={
                "ok": True,
                "results": [
                    {"field": "field_1", "disease": "downy_mildew", "status": "success"}
                ],
                "failures": [],
            },
        ) as validate:
            status = MODULE.mode_supabase(types.SimpleNamespace())

        self.assertEqual(status, 0)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(
            [item.args[0]["SKILL_DISEASE"] for item in call.call_args_list],
            ["downy_mildew", "powdery_mildew", "black_rot"],
        )
        validate.assert_called_once_with(["field_1"])

    def test_black_rot_near_saturation_watch_is_an_alert(self):
        skill_result = {
            "ok": True,
            "stdout": {
                "status": "success",
                "language": "ca",
                "daily_summary": "vigilància d'humectació",
                "media": [{"path": "/tmp/black.png", "field": "field_1", "disease": "black_rot"}],
                "field_reports": [{
                    "status": "success",
                    "field": "field_1",
                    "send_text": "possible humectació",
                    "latest": {
                        "black_rot_infection_index": 0.0,
                        "black_rot_wetness_uncertain_watch": 1,
                        "black_rot_inoculum_status": "present",
                    },
                    "forecast_prediction": {},
                }],
            },
        }
        args = types.SimpleNamespace(days=31)
        with mock.patch.object(MODULE, "call_black_rot", return_value=skill_result):
            payload = MODULE.black_rot_alert_payload(args)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["has_alert"])
        self.assertEqual(payload["send_text"], "vigilància d'humectació")
        self.assertEqual(payload["alert_fields"], ["field_1"])
        self.assertEqual(len(payload["media"]), 1)

    def test_black_rot_multifield_alert_uses_one_board_summary(self):
        skill_result = {
            "ok": True,
            "stdout": {
                "status": "success",
                "language": "ca",
                "daily_summary": "resum únic de cinc camps",
                "media": [],
                "field_reports": [
                    {
                        "status": "success",
                        "field": f"field_{number}",
                        "send_text": "bloc duplicat La Granada",
                        "latest": {
                            "black_rot_infection_index": 0.0,
                            "black_rot_inoculum_status": "present",
                        },
                        "forecast_prediction": {"first_infection_day": "2026-07-15"},
                    }
                    for number in range(1, 6)
                ],
            },
        }
        args = types.SimpleNamespace(days=31)
        with mock.patch.object(MODULE, "call_black_rot", return_value=skill_result):
            payload = MODULE.black_rot_alert_payload(args)
        self.assertTrue(payload["has_alert"])
        self.assertEqual(payload["send_text"], "resum únic de cinc camps")
        self.assertNotIn("bloc duplicat", payload["send_text"])
        self.assertEqual(len(payload["alert_fields"]), 5)

    def test_black_rot_weather_signal_is_alert_without_documented_inoculum(self):
        skill_result = {
            "ok": True,
            "stdout": {
                "status": "success",
                "language": "ca",
                "daily_summary": "vigilància científica, sense presència documentada",
                "media": [{"path": "/tmp/black.png", "field": "field_1", "disease": "black_rot"}],
                "field_reports": [{
                    "status": "success",
                    "field": "field_1",
                    "latest": {
                        "black_rot_infection_index": 105.0,
                        "black_rot_inoculum_status": "not_reported",
                    },
                    "forecast_prediction": {"first_infection_day": "2026-08-02"},
                }],
            },
        }
        args = types.SimpleNamespace(days=31)
        with mock.patch.object(MODULE, "call_black_rot", return_value=skill_result):
            payload = MODULE.black_rot_alert_payload(args)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["has_alert"])
        self.assertEqual(payload["alert_fields"], ["field_1"])
        self.assertEqual(len(payload["media"]), 1)
        self.assertTrue(payload["include_daily_summary"])

    def test_daily_alert_evaluates_three_diseases_and_packages_once(self):
        def daily(params):
            disease = params["disease"]
            return {
                "ok": True,
                "stdout": {
                    "status": "success",
                    "disease": disease,
                    "send_text": disease,
                    "has_alert": disease == "powdery_mildew",
                    "language": "ca",
                    "media": ([{
                        "type": "photo",
                        "path": "/tmp/powdery.png",
                        "disease": disease,
                    }] if disease == "powdery_mildew" else []),
                },
            }

        black = {
            "ok": True,
            "send_text": "black_rot",
            "has_alert": False,
            "include_daily_summary": False,
            "language": "ca",
            "media": [],
        }
        args = types.SimpleNamespace(
            days=31,
            high_threshold=70,
            watch_threshold=50,
            delta_threshold=15,
            outbox="/tmp/test-outbox",
        )
        with mock.patch.object(MODULE, "call_daily", side_effect=daily) as call_daily, mock.patch.object(
            MODULE, "black_rot_alert_payload", return_value=black
        ) as call_black, mock.patch.object(
            MODULE, "call_farmer_notify", return_value={"ok": True, "stdout": {}}
        ) as notify:
            status = MODULE.mode_alert(args)

        self.assertEqual(status, 0)
        self.assertEqual(call_daily.call_count, 2)
        self.assertEqual(
            {call.args[0]["disease"] for call in call_daily.call_args_list},
            {"downy_mildew", "powdery_mildew"},
        )
        self.assertTrue(all(call.args[0]["mode"] == "single_disease_report" for call in call_daily.call_args_list))
        self.assertTrue(all(call.args[0]["notify_mode"] == "risk_only" for call in call_daily.call_args_list))
        call_black.assert_called_once()
        notify.assert_called_once()
        package = notify.call_args.args[0]
        self.assertEqual(package["alert_diseases"], ["powdery_mildew"])
        self.assertEqual({item["disease"] for item in package["media"]}, {"powdery_mildew"})
        self.assertIn("downy_mildew", package["message"])
        self.assertIn("powdery_mildew", package["message"])
        self.assertNotIn("black_rot", package["message"])

    def test_proactive_cycle_uses_deterministic_skill_and_threshold(self):
        args = types.SimpleNamespace(
            proactive_notify_threshold=75,
            research=True,
        )
        skill_result = {
            "ok": True,
            "stdout": {
                "status": "success",
                "fields": ["field_1"],
                "observations": {"seen": 3, "inserted": 3},
                "operations": {"available": True, "inserted": 1},
                "proposals": [{"id": 7, "field_id": "field_1", "kind": "field_check"}],
                "notification": {"status": "success"},
                "research": {"status": "success"},
            },
        }
        with mock.patch.object(MODULE, "call_proactive", return_value=skill_result) as call:
            status = MODULE.mode_proactive(args)
        self.assertEqual(status, 0)
        params = call.call_args.args[0]
        self.assertEqual(params["mode"], "tick")
        self.assertTrue(params["notify"])
        self.assertTrue(params["research"])
        self.assertEqual(params["notify_threshold"], 75)


if __name__ == "__main__":
    unittest.main()
