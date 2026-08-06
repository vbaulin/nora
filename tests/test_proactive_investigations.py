"""The proactive agent must investigate before it asks.

These tests pin the behaviour that separates a research tool from a sales
pitch: the board analyses the evidence it already holds, reports what it found
with numbers, offers the cheapest way to close what remains open, and accepts
"no" as an answer.
"""

import datetime as dt
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "proactive_field_agent" / "run.py"
SPEC = importlib.util.spec_from_file_location("proactive_field_agent", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
INVESTIGATIONS = MODULE.investigations

SERIES_END = dt.date(2026, 6, 30)
SERIES_DAYS = 60


class InvestigationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "goidanich"
        self.state = self.root / "state"
        self.results = self.repo / "results"
        self.results.mkdir(parents=True)
        config = {
            "board": {"id": "board_test", "preferred_language": "ca"},
            "notifications": {"language": "ca"},
            "fields": [{
                "id": "field_1",
                "name": "Camp Nord",
                "location": "Penedès",
                "variety": "Chardonnay",
                "coordinates": {"latitude": 41.3, "longitude": 1.7},
                "metadata": {
                    "planting_year": 2018,
                    "rootstock": "110R",
                    "management": "organic",
                },
            }],
        }
        (self.repo / "agent_config.yaml").write_text(json.dumps(config), encoding="utf-8")
        self.field_db = sqlite3.connect(self.repo / "goidanich.db")
        self.field_db.execute(
            """
            CREATE TABLE farmer_feedback(
                timestamp TEXT, feedback_type TEXT, grade REAL, severity REAL,
                notes TEXT, metadata TEXT, field_id TEXT, disease_id TEXT
            )
            """
        )
        self.field_db.execute(
            """
            CREATE TABLE black_rot_daily_predictions(
                field_id TEXT, day TEXT, station TEXT,
                infection_index REAL, severity TEXT, infection_event INTEGER,
                wet_hours INTEGER, rain REAL, temp REAL, humi REAL,
                humidity_wet_hours INTEGER, rain_wet_hours INTEGER,
                measured_wet_hours INTEGER, near_saturation_hours INTEGER,
                potential_infection_index REAL, wetness_uncertain_watch INTEGER,
                max_humi REAL, wetness_driver TEXT,
                PRIMARY KEY (field_id, day, station)
            )
            """
        )
        self.field_db.commit()
        self.write_states()

    def tearDown(self):
        self.field_db.close()
        self.temp.cleanup()

    # -- fixtures ---------------------------------------------------------

    def state_payload(self, disease, wetness=False, powdery_risk=20.0, powdery_due=False):
        today = dt.datetime.now().astimezone().date()
        latest = {
            "field_id": "field_1",
            "day": today.isoformat(),
            "trained": 1,
            "baseline_risk": 12.0,
            "rossi_risk": 0.0,
            "powdery_risk": powdery_risk,
            "powdery_pmi": 5.0,
            "powdery_pmi_treatment_due": int(powdery_due),
        }
        if disease == "black_rot":
            latest = {
                "field_id": "field_1",
                "day": today.isoformat(),
                "black_rot_infection_index": 0.0,
                "black_rot_inoculum_status": "unknown",
                "black_rot_wetness_uncertain_watch": int(wetness),
            }
        return {
            "field": "field_1",
            "disease": disease,
            "end": today.isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "latest": latest,
            "plot_path": str(self.results / f"dashboard_latest_{disease}_field_1.png"),
            "model_layer_freshness": {
                "required_end": today.isoformat(),
                "latest_history_day": today.isoformat(),
                "history_current": True,
                "prediction_ok": True,
                "forecast_current": True,
                "forecast_refresh_ok": True,
            },
        }

    def write_states(self, wetness=True):
        for disease in ("downy_mildew", "powdery_mildew", "black_rot"):
            payload = self.state_payload(disease, wetness=wetness)
            path = self.results / f"dashboard_state_{disease}_field_1.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

    def write_series(self, overrides=None, rh95_hours=3, measured_hours=0):
        """A quiet black-rot season, with per-day overrides for the interesting days."""
        overrides = overrides or {}
        rows = []
        for offset in range(SERIES_DAYS):
            day = (SERIES_END - dt.timedelta(days=SERIES_DAYS - 1 - offset)).isoformat()
            row = {
                "day": day,
                "infection_index": 4.0,
                "potential_infection_index": 6.0,
                "near_saturation_hours": 0,
                "humidity_wet_hours": rh95_hours if offset % 20 == 0 else 0,
                "rain_wet_hours": 1,
                "measured_wet_hours": measured_hours,
                "rain": 0.0,
                "max_humi": 84.0,
                "infection_event": 0,
            }
            row.update(overrides.get(day, {}))
            rows.append(row)
        for row in rows:
            self.field_db.execute(
                """
                INSERT INTO black_rot_daily_predictions(
                    field_id, day, station, infection_index, severity, infection_event,
                    wet_hours, rain, temp, humi, humidity_wet_hours, rain_wet_hours,
                    measured_wet_hours, near_saturation_hours, potential_infection_index,
                    wetness_uncertain_watch, max_humi, wetness_driver
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "field_1", row["day"], "XX", row["infection_index"], "none",
                    row["infection_event"], 2, row["rain"], 18.0, 80.0,
                    row["humidity_wet_hours"], row["rain_wet_hours"],
                    row["measured_wet_hours"], row["near_saturation_hours"],
                    row["potential_infection_index"], 0, row["max_humi"], "humidity",
                ),
            )
        self.field_db.commit()

    def day(self, days_before_end):
        return (SERIES_END - dt.timedelta(days=days_before_end)).isoformat()

    def ambiguous(self, potential=120.0, primary=40.0):
        return {
            "infection_index": primary,
            "potential_infection_index": potential,
            "near_saturation_hours": 6,
            "max_humi": 93.0,
        }

    def confirmed_crossing(self):
        return {
            "infection_index": 140.0,
            "potential_infection_index": 160.0,
            "rain": 12.0,
            "rain_wet_hours": 9,
            "infection_event": 1,
        }

    def connection(self):
        return MODULE.connect_db(str(self.state))

    def params(self, **extra):
        return {"repo_path": str(self.repo), "state_dir": str(self.state), **extra}

    def tick(self, connection):
        return MODULE.mode_observe(connection, self.params(), create=True)

    def investigation(self, result, topic):
        for item in result["investigations"]:
            if item["topic"] == topic:
                return item
        return None


class LeafWetnessInvestigationTest(InvestigationTestCase):
    def test_ambiguity_resolved_by_rain_is_closed_without_writing_to_the_farmer(self):
        self.write_series(overrides={
            self.day(20): self.ambiguous(),
            self.day(19): self.confirmed_crossing(),
        })
        connection = self.connection()
        result = self.tick(connection)
        finding = self.investigation(result, "leaf_wetness_proxy")
        self.assertEqual(finding["verdict"], "not_material")
        self.assertEqual(result["proposals"], [])
        self.assertIsNone(result["research_request"])

    def test_unresolved_ambiguity_reports_the_analysis_before_asking_anything(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(potential=118.0, primary=44.0),
            self.day(12): self.ambiguous(potential=96.0, primary=31.0),
        })
        connection = self.connection()
        result = self.tick(connection)
        finding = self.investigation(result, "leaf_wetness_proxy")
        self.assertEqual(finding["verdict"], "material_unresolved")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["kind"], "investigation:leaf_wetness_proxy")
        message = proposal["message"]
        # The message must show the work: sample, ambiguity count, both indices.
        self.assertIn("60 dies", message)
        self.assertIn("2 dies", message)
        self.assertIn("118", message)
        self.assertIn(self.day(30), message)
        # The first thing asked of the farmer is free, not a purchase.
        self.assertIn("1) que un matí d'avís mireu si les fulles són mullades", message)
        self.assertLess(message.index("mullades"), message.index("sensor"))
        self.assertIn("responeu «cap» i ho deixo tancat", message.lower())

    def test_measured_wetness_never_produces_a_sensor_proposal(self):
        self.write_series(measured_hours=4, overrides={
            self.day(30): self.ambiguous(),
        })
        connection = self.connection()
        result = self.tick(connection)
        finding = self.investigation(result, "leaf_wetness_proxy")
        self.assertEqual(finding["verdict"], "resolved_local")
        self.assertEqual(result["proposals"], [])

    def test_unreachable_wetness_threshold_queues_a_scientific_question(self):
        self.write_series(rh95_hours=0, overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        result = self.tick(connection)
        request = result["research_request"]
        self.assertIsNotNone(request)
        self.assertIn("threshold", request["query"])
        self.assertNotIn("buy", request["query"].lower())
        self.assertNotIn("low-power", request["query"].lower())
        message = result["proposals"][0]["message"]
        self.assertIn("no ha registrat ni una hora amb humitat ≥95%", message)
        self.assertIn("apunta al llindar del model en aquesta estació", message)

    def test_a_refusal_closes_the_subject_for_the_season(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        proposal = self.tick(connection)["proposals"][0]
        decision = MODULE.mode_decision(connection, {
            "proposal_id": proposal["id"],
            "decision": "rejected",
            "note": "ara no",
        })
        self.assertFalse(decision["executed_action"])
        reopens = dt.datetime.fromisoformat(decision["reopens_after"])
        self.assertGreater((reopens - MODULE.utcnow()).days, 90)
        self.assertEqual(self.tick(connection)["proposals"], [])
        self.assertFalse(MODULE.hardware_option_allowed(connection, "field_1"))

    def test_hardware_option_is_offered_at_most_once_per_field(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        first = self.tick(connection)["proposals"][0]
        self.assertIn("leaf_wetness_sensor", first["evidence"][0]["options"])
        self.assertFalse(MODULE.hardware_option_allowed(connection, "field_1"))
        profile = MODULE.field_profiles(str(self.repo))[0]
        records = MODULE.run_field_investigations(connection, profile, str(self.repo))
        wetness = [item for item in records if item["topic"] == "leaf_wetness_proxy"][0]
        self.assertNotIn(
            "leaf_wetness_sensor", [option["id"] for option in wetness["options"]],
        )

    def test_a_settled_question_is_reported_back_once(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        opened = self.tick(connection)["proposals"][0]
        MODULE.mark_proposal_notified(connection, opened["id"])
        self.field_db.execute("DELETE FROM black_rot_daily_predictions")
        self.field_db.commit()
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(29): self.confirmed_crossing(),
            self.day(12): self.ambiguous(),
            self.day(11): self.confirmed_crossing(),
        })
        closure = self.tick(connection)["proposals"][0]
        self.assertEqual(closure["kind"], "investigation:leaf_wetness_proxy:closure")
        self.assertIn("no proposo cap sensor", closure["message"])
        self.assertFalse(closure["requires_confirmation"])
        self.assertEqual(
            MODULE.proposal_by_id(connection, opened["id"])["status"], "completed",
        )
        self.assertEqual(self.tick(connection)["proposals"], [])

    def test_investigation_reply_routes_to_the_option_choice_not_to_a_disease_record(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        proposal = self.tick(connection)["proposals"][0]
        context = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: la primera",
        })
        self.assertEqual(context["status"], "success")
        self.assertFalse(context["written"])
        self.assertEqual(context["next_route"], "proactive-field-agent")
        self.assertEqual(context["next_mode"], "record_decision")
        self.assertEqual(context["investigation"]["topic"], "leaf_wetness_proxy")
        self.assertIn("same_day_canopy_check", context["investigation"]["options"])
        # A later tick drops the spent hardware option from the finding, but the
        # reply must still resolve against the options that were actually sent.
        self.tick(connection)
        later = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: la segona",
        })
        self.assertEqual(
            later["investigation"]["options"], context["investigation"]["options"],
        )


class PeerAndCalibrationInvestigationTest(InvestigationTestCase):
    def add_peer_signal(self, days_ago=2, latitude=41.315, longitude=1.705,
                        disease="black_rot"):
        self.field_db.execute(
            """
            CREATE TABLE IF NOT EXISTS peer_signals(
                timestamp TEXT, peer_id TEXT, signal_type TEXT, value REAL,
                metadata TEXT, disease_id TEXT
            )
            """
        )
        moment = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
        self.field_db.execute(
            "INSERT INTO peer_signals(timestamp, peer_id, signal_type, value, metadata, disease_id)"
            " VALUES(?,?,?,?,?,?)",
            (
                moment.isoformat(), "agent_granada_01", "contagion", 3.0,
                json.dumps({
                    "latitude": latitude, "longitude": longitude,
                    "event_type": "disease", "board_id": "La Granada",
                }),
                disease,
            ),
        )
        self.field_db.commit()

    def test_nearby_confirmation_asks_for_an_inspection_not_a_purchase(self):
        self.write_series()
        self.add_peer_signal()
        connection = self.connection()
        result = self.tick(connection)
        finding = self.investigation(result, "peer_signal_divergence")
        self.assertEqual(finding["verdict"], "material_unresolved")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["kind"], "investigation:peer_signal_divergence")
        message = proposal["message"]
        self.assertIn("La Granada", message)
        self.assertIn("km", message)
        self.assertIn("no confirma res aquí", message)
        self.assertIn("inspecció dirigida", message)
        self.assertNotIn("sensor", message.lower())
        self.assertIn("No proposo comprar res", message)

    def test_a_distant_signal_does_not_generate_a_message(self):
        self.write_series()
        self.add_peer_signal(latitude=41.60, longitude=2.10)
        connection = self.connection()
        result = self.tick(connection)
        finding = self.investigation(result, "peer_signal_divergence")
        self.assertEqual(finding["verdict"], "not_material")
        self.assertEqual(result["proposals"], [])

    def test_a_confirmed_inspection_closes_the_peer_alert(self):
        self.write_series()
        self.add_peer_signal()
        connection = self.connection()
        opened = self.tick(connection)["proposals"][0]
        MODULE.mark_proposal_notified(connection, opened["id"])
        occurred = (MODULE.utcnow() - dt.timedelta(hours=1)).isoformat()
        connection.execute(
            """
            INSERT INTO operations(
                event_id, field_id, disease_id, operation_type, occurred_at,
                payload_json, source_ref, created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "op-inspection", "field_1", "black_rot", "clean_inspection",
                occurred, "{}", "test", occurred,
            ),
        )
        connection.commit()
        closure = self.tick(connection)["proposals"][0]
        self.assertEqual(
            closure["kind"], "investigation:peer_signal_divergence:closure",
        )
        self.assertIn("inspecció confirmada posterior", closure["message"])
        self.assertEqual(
            MODULE.proposal_by_id(connection, opened["id"])["status"], "completed",
        )

    def test_clean_inspections_make_the_board_propose_fewer_alerts(self):
        self.write_series()
        connection = self.connection()
        self.tick(connection)
        now = MODULE.utcnow()
        for index in range(5):
            sent = (now - dt.timedelta(days=30 - index * 5)).isoformat()
            connection.execute(
                """
                INSERT INTO proposals(
                    field_id, kind, target, priority, title, message, rationale,
                    evidence_json, confidence, requires_confirmation, status,
                    dedupe_key, cooldown_until, notified_at, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "field_1", "field_check", "farmer", 90, "alert", "alert", "alert",
                    "[]", 0.9, 1, "notified", f"alert-{index}", None, sent, sent, sent,
                ),
            )
            occurred = (now - dt.timedelta(days=29 - index * 5)).isoformat()
            connection.execute(
                """
                INSERT INTO operations(
                    event_id, field_id, disease_id, operation_type, occurred_at,
                    payload_json, source_ref, created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    f"op-{index}", "field_1", "powdery_mildew", "clean_inspection",
                    occurred, "{}", "test", occurred,
                ),
            )
        connection.commit()
        profile = MODULE.field_profiles(str(self.repo))[0]
        records = MODULE.run_field_investigations(connection, profile, str(self.repo))
        finding = [item for item in records if item["topic"] == "alert_calibration"][0]
        self.assertEqual(finding["verdict"], "material_unresolved")
        self.assertEqual(finding["findings"]["clean_inspections"], 5)
        candidates = MODULE.investigation_candidates(connection, profile, records)
        calibration = [
            item for item in candidates
            if item["kind"] == "investigation:alert_calibration"
        ][0]
        self.assertIn("5 inspeccions netes", calibration["message"])
        self.assertIn("pujar el llindar d'avís", calibration["message"])
        self.assertNotIn("sensor", calibration["message"].lower())


class InvestigationModeTest(InvestigationTestCase):
    def test_investigate_mode_reports_method_sample_and_limits_without_notifying(self):
        self.write_series(overrides={
            self.day(30): self.ambiguous(),
            self.day(12): self.ambiguous(),
        })
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=False)
        result = MODULE.mode_investigate(connection, self.params())
        self.assertEqual(result["status"], "success")
        wetness = [
            item for item in result["investigations"]
            if item["topic"] == "leaf_wetness_proxy"
        ][0]
        self.assertEqual(wetness["sample_size"], SERIES_DAYS)
        self.assertIn("Compared the confirmed VitiMeteo infection index", wetness["method"])
        self.assertTrue(wetness["limitations"])
        self.assertEqual(wetness["findings"]["unresolved_days"], 2)
        self.assertNotIn("proposal", result)

    def test_self_test_reports_which_investigation_sources_exist(self):
        self.write_series()
        connection = self.connection()
        result = MODULE.mode_self_test(connection, self.params())
        sources = result["checks"]["investigation_sources"]
        self.assertTrue(sources["black_rot_daily_predictions"])
        self.assertTrue(sources["upper_bound_index"])
        self.assertFalse(sources["peer_signals"])
        self.assertIn("leaf_wetness_proxy", result["checks"]["investigation_topics"])


if __name__ == "__main__":
    unittest.main()
