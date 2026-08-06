import datetime as dt
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "skills" / "proactive_field_agent" / "run.py"
SPEC = importlib.util.spec_from_file_location("proactive_field_agent", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProactiveFieldAgentTest(unittest.TestCase):
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
        db = sqlite3.connect(self.repo / "goidanich.db")
        db.execute(
            """
            CREATE TABLE farmer_feedback(
                timestamp TEXT, feedback_type TEXT, grade REAL, severity REAL,
                notes TEXT, metadata TEXT, field_id TEXT, disease_id TEXT
            )
            """
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def state_payload(self, disease="powdery_mildew", stale=False, wetness=False,
                      powdery_risk=75.0, powdery_due=True, black_index=0.0,
                      black_inoculum="not_reported", black_forecast_index=0.0,
                      black_forecast_day=""):
        today = dt.datetime.now().astimezone().date()
        day = today - dt.timedelta(days=5 if stale else 0)
        latest = {
            "field_id": "field_1",
            "day": day.isoformat(),
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
                "day": day.isoformat(),
                "black_rot_infection_index": black_index,
                "black_rot_inoculum_status": black_inoculum,
                "black_rot_wetness_uncertain_watch": int(wetness),
            }
        state = {
            "field": "field_1",
            "disease": disease,
            "end": day.isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "latest": latest,
            "plot_path": str(self.results / f"dashboard_latest_{disease}_field_1.png"),
            "model_layer_freshness": {
                "required_end": day.isoformat(),
                "latest_history_day": day.isoformat(),
                "history_current": not stale,
                "prediction_ok": not stale,
                "forecast_current": not stale,
                "forecast_refresh_ok": not stale,
            },
        }
        if disease == "black_rot" and black_forecast_index:
            state["forecast_prediction"] = {
                "available": True,
                "max_infection_index": black_forecast_index,
                "max_day": black_forecast_day,
                "first_infection_day": black_forecast_day,
            }
        return state

    def write_state(self, payload):
        disease = payload["disease"]
        path = self.results / f"dashboard_state_{disease}_field_1.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_complete_states(self, wetness=False, powdery_risk=75.0, powdery_due=True):
        self.write_state(self.state_payload(disease="downy_mildew"))
        self.write_state(self.state_payload(
            disease="powdery_mildew",
            powdery_risk=powdery_risk,
            powdery_due=powdery_due,
        ))
        self.write_state(self.state_payload(disease="black_rot", wetness=wetness))

    def connection(self):
        return MODULE.connect_db(str(self.state))

    def params(self, **extra):
        return {
            "repo_path": str(self.repo),
            "state_dir": str(self.state),
            **extra,
        }

    def run_entrypoint(self, payload, **env_updates):
        env = os.environ.copy()
        env.update({key: str(value) for key, value in env_updates.items()})
        proc = subprocess.run(
            [str(MODULE_PATH.parent / "run.sh")],
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def test_stale_dashboard_creates_internal_refresh_not_farmer_advice(self):
        self.write_state(self.state_payload(stale=True))
        connection = self.connection()
        result = MODULE.mode_observe(connection, self.params(), create=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["proposals"][0]["kind"], "refresh_required")
        self.assertEqual(result["proposals"][0]["target"], "system")
        self.assertIsNone(result["pending_proposal"])

    def test_current_model_signal_creates_one_confirmable_field_check(self):
        self.write_complete_states()
        connection = self.connection()
        first = MODULE.mode_observe(connection, self.params(), create=True)
        second = MODULE.mode_observe(connection, self.params(), create=True)
        self.assertEqual(len(first["proposals"]), 1)
        proposal = first["proposals"][0]
        self.assertEqual(proposal["kind"], "field_check")
        self.assertTrue(proposal["requires_confirmation"])
        self.assertIn("Camp Nord", proposal["message"])
        self.assertEqual(second["proposals"], [])

    def test_farmer_decision_is_recorded_without_executing_treatment(self):
        self.write_complete_states()
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        result = MODULE.mode_decision(connection, {
            "proposal_id": proposal["id"],
            "decision": "accepted",
            "note": "Faré una inspecció, no un tractament",
        })
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["executed_action"])
        stored = MODULE.proposal_by_id(connection, proposal["id"])
        self.assertEqual(stored["status"], "accepted")

    def test_uncertain_wetness_without_model_history_asks_the_farmer_for_nothing(self):
        """An unverifiable watch flag is an internal gap, not a hardware pitch."""
        self.write_complete_states(wetness=True, powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        result = MODULE.mode_observe(connection, self.params(), create=True)
        self.assertEqual(result["proposals"], [])
        self.assertIsNone(result["research_request"])
        wetness = [
            item for item in result["investigations"]
            if item["topic"] == "leaf_wetness_proxy"
        ]
        self.assertEqual(len(wetness), 1)
        self.assertEqual(wetness[0]["verdict"], "insufficient_data")

    def test_unverified_black_rot_forecast_is_sent_for_farmer_confirmation(self):
        self.write_state(self.state_payload(disease="downy_mildew"))
        self.write_state(self.state_payload(
            disease="powdery_mildew", powdery_risk=20.0, powdery_due=False,
        ))
        self.write_state(self.state_payload(
            disease="black_rot",
            black_inoculum="unknown",
            black_forecast_index=105.0,
            black_forecast_day=(dt.date.today() + dt.timedelta(days=1)).isoformat(),
        ))
        connection = self.connection()
        result = MODULE.mode_observe(connection, self.params(), create=True)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["kind"], "field_check")
        self.assertIn("Black rot de la vinya", proposal["message"])
        self.assertIn("pendent de confirmar al camp", proposal["message"])
        self.assertIn("fals avís", proposal["message"])
        self.assertEqual(MODULE.proposal_alert_diseases(proposal), ["black_rot"])

    def test_proposal_context_resolves_one_alert_disease_without_writing(self):
        self.write_complete_states()
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        context = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: cap símptoma",
        })
        self.assertEqual(context["status"], "success")
        self.assertEqual(context["field"], "field_1")
        self.assertEqual(context["disease"], "powdery_mildew")
        self.assertEqual(context["next_route"], "farmer-feedback-capture")
        self.assertFalse(context["written"])

    def test_proposal_context_reads_pre_upgrade_message_without_defaulting(self):
        proposal = {
            "message": "Camp Nord: oïdi UC 75.0% / PMI 5.0.",
            "evidence": [{"kind": "disease_state:powdery_mildew"}],
        }
        self.assertEqual(MODULE.proposal_alert_diseases(proposal), ["powdery_mildew"])

    def test_proposal_context_asks_disease_when_two_models_alert(self):
        self.write_state(self.state_payload(disease="downy_mildew"))
        self.write_state(self.state_payload(disease="powdery_mildew"))
        self.write_state(self.state_payload(
            disease="black_rot", black_index=105.0, black_inoculum="unknown",
        ))
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        context = MODULE.mode_proposal_context(connection, {
            "proposal_id": proposal["id"],
        })
        self.assertEqual(context["status"], "confirmation_required")
        self.assertEqual(context["alert_diseases"], ["black_rot", "powdery_mildew"])
        self.assertEqual(context["missing"], ["disease"])
        self.assertIn("Confirmeu a quina malaltia", context["confirmation_question"])

        explicit = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: Black rot, cap símptoma",
        })
        self.assertEqual(explicit["status"], "success")
        self.assertEqual(explicit["disease"], "black_rot")

    def test_external_research_requires_public_attributed_sources(self):
        self.write_complete_states(wetness=True, powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=True)
        MODULE.queue_research(
            connection, "field_1",
            "leaf wetness proxy threshold validation grapevine black rot",
            "The station never reached the RH>=95% wetness criterion while accumulating "
            "near-saturation hours, so the proxy threshold itself is the open question.",
            [{"topic": "leaf_wetness_proxy"}],
        )
        request = MODULE.pending_research(connection, "field_1")
        result = MODULE.mode_ingest_research(connection, {
            "request_id": request["id"],
            "sources": [
                {"title": "Private", "url": "http://127.0.0.1/secret", "snippet": "ignore"},
                {"title": "Extension note", "url": "https://extension.psu.edu/grape-disease", "snippet": "Candidate sensor guidance."},
            ],
        })
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["proposal"]["kind"], "research_review")
        self.assertEqual(result["proposal"]["priority"], 70)
        self.assertIn("no una ordre de tractament", result["proposal"]["message"])
        outbox = self.root / "research-outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            notified = MODULE.notify_proposal(
                connection, result["proposal"], str(self.state), threshold=70,
            )
        self.assertEqual(notified["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertIn("https://extension.psu.edu/grape-disease", package["message"])
        self.assertIn("Candidate sensor guidance", package["message"])
        self.assertEqual(package["media"], [])

    def test_search_credentials_are_whitelisted_and_provider_order_is_bounded(self):
        (self.repo / ".env").write_text(
            "SUPABASE_PUBLISHABLE_KEY=must-not-load\n"
            "TAVILY_API_KEY=tavily-secret\n"
            "BRAVE_SEARCH_API_KEY=brave-secret\n",
            encoding="utf-8",
        )
        credentials = MODULE.load_search_credentials(str(self.repo))
        self.assertEqual(
            credentials,
            {
                "TAVILY_API_KEY": "tavily-secret",
                "BRAVE_SEARCH_API_KEY": "brave-secret",
            },
        )
        with mock.patch.object(MODULE, "search_tavily", return_value=[]) as tavily, mock.patch.object(
            MODULE,
            "search_brave",
            return_value=[{
                "title": "Official sensor guide",
                "url": "https://example.org/sensor-guide",
                "snippet": "Check the documented bus voltage.",
                "provider": "brave",
            }],
        ) as brave, mock.patch.object(MODULE, "search_duckduckgo") as duck:
            sources, errors = MODULE.perform_search("sensor validation", 3, credentials)
        self.assertEqual(errors, [])
        self.assertEqual(sources[0]["provider"], "brave")
        tavily.assert_called_once_with("sensor validation", 3, "tavily-secret")
        brave.assert_called_once_with("sensor validation", 3, "brave-secret")
        duck.assert_not_called()

    def test_duckduckgo_search_falls_back_to_lite_results(self):
        class Response:
            def __init__(self, body):
                self.body = body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return self.body

        challenged = "<html><title>DuckDuckGo</title></html>"
        lite = """
        <a href='//duckduckgo.com/l/?uddg=https%3A%2F%2Fextension.example.edu%2Fgrape' class='result-link'>
          Extension grape guide
        </a>
        <td class='result-snippet'>Independent candidate guidance about leaf wetness.</td>
        """
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[Response(challenged), Response(lite)],
        ) as urlopen:
            results = MODULE.search_duckduckgo("grape leaf wetness", 3)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "duckduckgo_lite")
        self.assertEqual(results[0]["url"], "https://extension.example.edu/grape")
        self.assertIn("leaf wetness", results[0]["snippet"])

    def test_confirmed_operation_creates_localized_follow_up_and_context(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=False)
        occurred = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        recorded = MODULE.mode_operation(connection, {
            "field": "field_1",
            "operation_type": "pruning",
            "occurred_at": occurred,
            "details": {"method": "manual"},
            "confirmed": True,
        })
        self.assertEqual(recorded["status"], "success")

        tick = MODULE.mode_observe(connection, self.params(), create=True)
        proposal = tick["proposals"][0]
        self.assertEqual(proposal["kind"], "operation_follow_up")
        self.assertEqual(proposal["priority"], 75)
        self.assertIn("poda", proposal["message"])
        self.assertIn("sense confondre seqüència amb causa", proposal["message"])

        context = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: el vigor sembla equilibrat",
        })
        self.assertEqual(context["status"], "success")
        self.assertEqual(context["next_route"], "proactive-field-agent")
        self.assertEqual(context["next_mode"], "draft_operation")
        self.assertEqual(context["operation_type"], "follow_up_observation")
        self.assertFalse(context["written"])

    def test_existing_alert_does_not_block_new_operation_follow_up(self):
        self.write_complete_states()
        connection = self.connection()
        first = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        self.assertEqual(first["kind"], "field_check")
        MODULE.mode_operation(connection, {
            "field": "field_1",
            "operation_type": "pruning",
            "occurred_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat(),
            "confirmed": True,
        })

        second = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        self.assertEqual(second["kind"], "operation_follow_up")
        self.assertNotEqual(second["id"], first["id"])

    def test_confirmed_follow_up_closes_proposal_and_learns_noncausal_sequence(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=False)
        occurred = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        MODULE.mode_operation(connection, {
            "field": "field_1",
            "operation_type": "pruning",
            "occurred_at": occurred,
            "confirmed": True,
        })
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        outcome_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat()
        MODULE.mode_operation(connection, {
            "field": "field_1",
            "operation_type": "follow_up_observation",
            "occurred_at": outcome_at,
            "details": {"observation": "balanced vigor"},
            "confirmed": True,
        })

        observed = MODULE.mode_observe(connection, self.params(), create=False)
        self.assertEqual(observed["operations"]["reconciled_proposals"], [proposal["id"]])
        self.assertEqual(MODULE.proposal_by_id(connection, proposal["id"])["status"], "completed")
        fact = connection.execute(
            "SELECT value_json, status FROM facts WHERE predicate='observed_outcome_after_pruning'"
        ).fetchone()
        self.assertIsNotNone(fact)
        self.assertEqual(fact["status"], "observed_association")
        self.assertFalse(json.loads(fact["value_json"])["causal_claim"])

    def test_treatment_follow_up_keeps_exact_disease_feedback_route(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=False)
        occurred = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4)).isoformat()
        connection.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)",
            (
                "treatment-1", "field_1", "powdery_mildew", "treatment", occurred,
                json.dumps({"metadata": {"treatment": {"product": "sulfur", "dose": "2 kg/ha"}}}),
                "test", dt.datetime.now(dt.timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        self.assertEqual(proposal["kind"], "operation_follow_up")
        self.assertIn("sulfur", proposal["message"])

        context = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: cap símptoma",
        })
        self.assertEqual(context["next_route"], "farmer-feedback-capture")
        self.assertEqual(context["disease"], "powdery_mildew")
        self.assertEqual(context["source_operation"]["event_id"], "treatment-1")
        self.assertFalse(context["written"])

    def test_end_to_end_operation_follow_up_reaches_outbox_and_closes_after_confirmation(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        connection = self.connection()
        MODULE.mode_observe(connection, self.params(), create=False)
        MODULE.mode_operation(connection, {
            "field": "field_1",
            "operation_type": "pruning",
            "occurred_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat(),
            "confirmed": True,
        })
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        outbox = self.root / "outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            notification = MODULE.notify_proposal(connection, proposal, str(self.state), threshold=70)
        self.assertEqual(notification["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertIn(f"PF-{proposal['id']}", package["message"])
        self.assertEqual(package["media"], [])

        context = MODULE.mode_proposal_context(connection, {
            "raw_text": f"PF-{proposal['id']}: el vigor sembla equilibrat",
        })
        draft = MODULE.mode_operation(connection, {
            "field": context["field"],
            "operation_type": context["operation_type"],
            "raw_text": "el vigor sembla equilibrat",
            "occurred_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat(),
            "details": {"observation": "balanced vigor"},
            "confirmed": False,
        }, force_draft=True)
        self.assertEqual(draft["status"], "confirmation_required")
        self.assertFalse(draft["written"])
        confirmed = MODULE.mode_operation(connection, {
            **draft["draft"],
            "field": context["field"],
            "confirmed": True,
        })
        self.assertEqual(confirmed["status"], "success")

        observed = MODULE.mode_observe(connection, self.params(), create=False)
        self.assertEqual(observed["operations"]["reconciled_proposals"], [proposal["id"]])
        status = MODULE.compact_status(connection, "field_1")
        self.assertEqual(len(status["derived_insights"]["field_1"]), 1)
        self.assertFalse(status["derived_insights"]["field_1"][0]["value"]["causal_claim"])

    def test_shell_entrypoint_runs_proactive_telegram_cycle(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        self.run_entrypoint(self.params(mode="observe"))
        recorded = self.run_entrypoint(self.params(
            mode="record_operation",
            field="field_1",
            operation_type="pruning",
            occurred_at=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat(),
            confirmed=True,
        ))
        self.assertEqual(recorded["status"], "success")

        outbox = self.root / "entrypoint-outbox"
        tick = self.run_entrypoint(
            self.params(mode="tick", notify=True, research=False),
            PICOCLAW_OUTBOX=outbox,
        )
        self.assertEqual(tick["status"], "success")
        self.assertEqual(tick["notification"]["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertIn("poda", package["message"])
        self.assertRegex(package["message"], r"Ref: PF-\d+")
        self.assertEqual(package["dispatch_role"], "proactive_field_proposal")

    def test_notification_uses_existing_outbox_and_marks_proposal_once(self):
        self.write_complete_states()
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        outbox = self.root / "outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            first = MODULE.notify_proposal(connection, proposal, str(self.state), threshold=70)
            updated = MODULE.proposal_by_id(connection, proposal["id"])
            second = MODULE.notify_proposal(connection, updated, str(self.state), threshold=70)
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(len(list(outbox.glob("*.json"))), 1)

    def test_notification_attaches_only_alert_disease_plot(self):
        self.write_complete_states()
        powdery_plot = self.results / "dashboard_latest_powdery_mildew_field_1.png"
        powdery_plot.write_bytes(b"test-png")
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        outbox = self.root / "outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            result = MODULE.notify_proposal(connection, proposal, str(self.state), threshold=70)
        self.assertEqual(result["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(len(package["media"]), 1)
        self.assertEqual(package["media"][0]["disease"], "powdery_mildew")

    def test_daily_alert_package_suppresses_duplicate_proactive_message(self):
        self.write_complete_states()
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        outbox = self.root / "outbox"
        outbox.mkdir()
        daily = outbox / "daily.json"
        daily.write_text(json.dumps({
            "status": "pending",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "dispatch_role": "three_disease_daily_overview",
            "alert_diseases": ["powdery_mildew"],
            "alert_fields": ["field_1"],
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            result = MODULE.notify_proposal(connection, proposal, str(self.state), threshold=70)
        self.assertEqual(result["status"], "skipped_covered")
        self.assertEqual(result["covered_by"], str(daily))
        self.assertIsNotNone(MODULE.proposal_by_id(connection, proposal["id"])["notified_at"])
        self.assertEqual(len(list(outbox.glob("*.json"))), 1)

    def test_status_exposes_confirmed_operations_facts_and_decisions(self):
        db = sqlite3.connect(self.repo / "goidanich.db")
        db.execute(
            "INSERT INTO farmer_feedback VALUES(?,?,?,?,?,?,?,?)",
            (
                dt.datetime.now(dt.timezone.utc).isoformat(), "treatment", None, None,
                "confirmed application", json.dumps({"treatment": {"product": "sulfur", "dose": "2 kg/ha"}}),
                "field_1", "powdery_mildew",
            ),
        )
        db.commit()
        db.close()
        self.write_complete_states()
        connection = self.connection()
        proposal = MODULE.mode_observe(connection, self.params(), create=True)["proposals"][0]
        MODULE.mode_decision(connection, {"proposal_id": proposal["id"], "decision": "deferred", "note": "inspect tomorrow"})
        status = MODULE.compact_status(connection, "field_1")
        self.assertEqual(status["operations"]["field_1"][0]["operation_type"], "treatment")
        self.assertTrue(any(item["predicate"] == "variety" for item in status["facts"]["field_1"]))
        self.assertEqual(status["decisions"][0]["decision"], "deferred")

    def test_field_related_nano_experiment_is_ingested_with_provenance(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        nano_root = self.root / "nano-os-agent"
        nano_root.mkdir()
        experiment = {
            "id": 4,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "task_id": "canopy_observation",
            "task_name": "Vineyard canopy observation",
            "metrics_after": {"leaf_color_ratio": "0.82"},
            "steps_run": 2,
            "steps_passed": 2,
            "verdict": "keep",
            "summary": "2/2 steps passed",
        }
        (nano_root / "experiments.jsonl").write_text(json.dumps(experiment) + "\n", encoding="utf-8")
        connection = self.connection()
        result = MODULE.mode_observe(
            connection,
            self.params(nano_root=str(nano_root)),
            create=False,
        )
        self.assertEqual(result["observations"]["nano_experiments"], 1)
        self.assertEqual(result["observations"]["nano_insights"], 1)
        status = MODULE.compact_status(connection, "field_1")
        kinds = {item["kind"] for item in status["observations"]["field_1"]}
        self.assertIn("nano_experiment:canopy_observation", kinds)
        fact = connection.execute(
            "SELECT status, value_json FROM facts WHERE predicate='validated_canopy_observation'"
        ).fetchone()
        self.assertEqual(fact["status"], "observed_success")
        self.assertFalse(json.loads(fact["value_json"])["causal_claim"])

    def test_failed_nano_experiment_is_quarantined_researched_and_notified_with_sources(self):
        self.write_complete_states(powdery_risk=20.0, powdery_due=False)
        nano_root = self.root / "nano-os-agent"
        nano_root.mkdir()
        experiment = {
            "id": 9,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "task_id": "leaf_wetness_probe",
            "task_name": "Vineyard leaf wetness sensor validation",
            "metrics_after": {"field_id": "field_1", "sensor_bound": False},
            "steps_run": 3,
            "steps_passed": 1,
            "verdict": "partial",
            "summary": "I2C read failed after sensor discovery",
        }
        (nano_root / "experiments.jsonl").write_text(
            json.dumps(experiment) + "\n", encoding="utf-8"
        )
        connection = self.connection()
        tick = MODULE.mode_observe(
            connection,
            self.params(nano_root=str(nano_root)),
            create=True,
        )
        internal = tick["proposals"][0]
        self.assertEqual(internal["kind"], "experiment_investigation")
        self.assertEqual(internal["target"], "system")
        self.assertIn("excluded from farmer advice", internal["message"])
        self.assertIsNotNone(tick["research_request"])
        self.assertIsNone(tick["pending_proposal"])

        sources = [{
            "title": "Sensor vendor integration guide",
            "url": "https://example.org/leaf-wetness-integration",
            "snippet": "Verify pull-up voltage and the documented bus address.",
            "provider": "test_search",
        }]
        with mock.patch.object(MODULE, "perform_search", return_value=(sources, [])):
            research = MODULE.mode_research(connection, {})
        self.assertEqual(research["status"], "success")
        self.assertEqual(research["proposal"]["kind"], "research_review")
        self.assertEqual(
            MODULE.proposal_by_id(connection, internal["id"])["status"],
            "completed",
        )

        outbox = self.root / "nano-research-outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            notified = MODULE.notify_proposal(
                connection, research["proposal"], str(self.state), threshold=70,
            )
        self.assertEqual(notified["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertIn("https://example.org/leaf-wetness-integration", package["message"])
        self.assertIn("Verify pull-up voltage", package["message"])
        self.assertIn("la validació d'un experiment de camp o sensor", package["message"])
        self.assertIn("extracte original de la font", package["message"])
        self.assertNotIn("troubleshooting official documentation", package["message"])
        self.assertNotIn("I2C read failed", package["message"])
        self.assertEqual(package["media"], [])

    def test_general_operation_requires_confirmation_then_enters_memory(self):
        connection = self.connection()
        profiles = MODULE.field_profiles(str(self.repo))
        MODULE.save_profiles(connection, profiles)
        draft = MODULE.mode_operation(connection, {
            "field": "field_1",
            "raw_text": "Hem fet la poda del Camp Nord",
            "occurred_at": dt.date.today().isoformat(),
            "details": {"method": "manual"},
        })
        self.assertEqual(draft["status"], "confirmation_required")
        self.assertEqual(draft["draft"]["operation_type"], "pruning")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)
        confirmed = MODULE.mode_operation(connection, {
            **draft["draft"],
            "field": "field_1",
            "confirmed": True,
        })
        self.assertEqual(confirmed["status"], "success")
        self.assertTrue(confirmed["written"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 1)

    def test_treatment_operation_is_redirected_to_catalog_aware_feedback_skill(self):
        connection = self.connection()
        MODULE.save_profiles(connection, MODULE.field_profiles(str(self.repo)))
        result = MODULE.mode_operation(connection, {
            "field": "field_1",
            "raw_text": "He aplicat sofre 2 kg/ha",
            "occurred_at": dt.date.today().isoformat(),
            "confirmed": True,
        })
        self.assertEqual(result["status"], "redirect")
        self.assertEqual(result["route"], "farmer-feedback-capture")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)

    def test_self_test_distinguishes_installation_from_fresh_cache_readiness(self):
        (self.repo / ".env").write_text(
            "TAVILY_API_KEY=never-return-this-value\n",
            encoding="utf-8",
        )
        connection = self.connection()
        result = MODULE.mode_self_test(connection, self.params(nano_root=str(self.root / "nano")))
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["installed"])
        self.assertFalse(result["operational_ready"])
        self.assertEqual(
            result["checks"]["missing_disease_states"]["field_1"],
            ["black_rot", "downy_mildew", "powdery_mildew"],
        )
        self.assertIn("tavily", result["checks"]["search_providers"])
        self.assertNotIn("never-return-this-value", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
