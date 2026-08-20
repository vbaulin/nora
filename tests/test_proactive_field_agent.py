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

PACK_PATH = Path(__file__).resolve().parents[1] / "skills" / "proactive_field_agent" / "pack.py"
PACK_SPEC = importlib.util.spec_from_file_location("proactive_field_agent_pack", PACK_PATH)
PACK_MODULE = importlib.util.module_from_spec(PACK_SPEC)
PACK_SPEC.loader.exec_module(PACK_MODULE)


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

    def test_climate_channels_are_expanded_without_prescribing_direction(self):
        with sqlite3.connect(self.repo / "goidanich.db") as db:
            db.execute(
                "CREATE TABLE season_climate_metrics("
                "field_id TEXT, observed_at TEXT, metric TEXT, value REAL)"
            )
            db.executemany(
                "INSERT INTO season_climate_metrics VALUES(?,?,?,?)",
                [
                    ("field_1", "2026-08-01", "weather.rain_mm", 2.0),
                    ("field_1", "2026-08-01", "weather.solar_energy_mj_m2", 19.0),
                ],
            )
        series = PACK_MODULE.climate_series({
            "params_in": {"repo_path": str(self.repo)},
        })
        self.assertEqual(len(series), 2)
        self.assertTrue(all(item["role"] == "driver" for item in series))
        self.assertEqual(
            {tuple(item["source"]["where_values"]) for item in series},
            {
                ("field_1", "weather.rain_mm"),
                ("field_1", "weather.solar_energy_mj_m2"),
            },
        )

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

    def test_external_research_is_internal_evidence_not_farmer_homework(self):
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
        self.assertIsNone(result["proposal"])
        self.assertFalse(result["synthesis"]["farmer_action_required"])
        self.assertFalse(result["synthesis"]["operational_change"])
        self.assertEqual(result["synthesis"]["source_count"], 1)
        self.assertEqual(MODULE.next_proposal(connection), None)
        fact = connection.execute(
            "SELECT value_json FROM facts WHERE predicate='external_source_synthesis'"
        ).fetchone()
        self.assertIsNotNone(fact)
        self.assertIn("https://extension.psu.edu/grape-disease", fact["value_json"])

    def test_one_variety_search_covers_all_fields_and_stays_internal(self):
        connection = self.connection()
        profiles = MODULE.field_profiles(str(self.repo))
        second = dict(profiles[0])
        second["field_id"] = "field_2"
        second["name"] = "Camp Sud"
        second["profile"] = dict(second["profile"], id="field_2", name="Camp Sud")
        profiles.append(second)
        MODULE.save_profiles(connection, profiles)

        queued = MODULE.ensure_variety_research_requests(connection, profiles)
        self.assertEqual(queued, [{
            "variety": "Chardonnay",
            "fields": ["field_1", "field_2"],
        }])
        self.assertEqual(MODULE.ensure_variety_research_requests(connection, profiles), [])
        request = MODULE.pending_research(connection)
        self.assertEqual(request["evidence"][0]["variety"], "Chardonnay")

        result = MODULE.mode_ingest_research(connection, {
            "request_id": request["id"],
            "sources": [{
                "title": "Cultivar phenology study",
                "url": "https://example.org/chardonnay-phenology",
                "snippet": "Candidate cultivar-specific evidence.",
            }],
        })
        self.assertEqual(result["synthesis"]["evidence_class"], "cultivar_literature_prior")
        self.assertEqual(
            result["synthesis"]["applicable_fields"], ["field_1", "field_2"]
        )
        self.assertFalse(result["synthesis"]["farmer_action_required"])
        rows = connection.execute(
            "SELECT field_id FROM facts WHERE predicate='variety_evidence_profile' "
            "ORDER BY field_id"
        ).fetchall()
        self.assertEqual([row["field_id"] for row in rows], ["field_1", "field_2"])
        self.assertIsNone(MODULE.next_proposal(connection))

        supplemental = MODULE.ensure_variety_research_requests(connection, profiles)
        self.assertEqual(supplemental, [{
            "variety": "Chardonnay",
            "fields": ["field_1", "field_2"],
        }])
        follow_up = MODULE.pending_research(connection)
        self.assertEqual(follow_up["evidence"][0]["research_pass"], "supplemental")
        self.assertEqual(follow_up["evidence"][0]["existing_source_count"], 1)

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

    def test_failed_nano_experiment_is_quarantined_and_researched_internally(self):
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
        self.assertIsNone(research["proposal"])
        self.assertFalse(research["synthesis"]["farmer_action_required"])
        self.assertEqual(
            MODULE.proposal_by_id(connection, internal["id"])["status"],
            "completed",
        )
        self.assertEqual(MODULE.next_proposal(connection), None)

    def test_material_research_finding_is_eligible_for_notification(self):
        connection = self.connection()
        profile = MODULE.field_profiles(str(self.repo))[0]
        finding = {
            "id": 17,
            "subject": "vineyard:field_1",
            "analysis": "source_disagreement",
            "verdict": "material_unresolved",
            "method": "Compared two current measurement sources.",
            "sample_size": 48,
            "confidence": 0.8,
            "limitations": ["The comparison does not identify ground truth."],
            "options": [
                {"id": "targeted_inspection", "cost": "none"},
                {"id": "deeper_analysis", "cost": "none"},
            ],
        }
        rendered = {
            "title": "Anomalia detectada al Camp Nord",
            "message": "Dues fonts actuals divergeixen de manera material.",
        }
        with mock.patch.object(MODULE, "research_findings", return_value=[finding]), \
                mock.patch.object(
                    MODULE.investigations, "render_anomaly", return_value=rendered,
                ):
            candidates = MODULE.research_candidates(connection, profile, self.params())
        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(
            candidates[0]["priority"], MODULE.DEFAULT_NOTIFICATION_THRESHOLD,
        )
        self.assertEqual(
            candidates[0]["evidence"][0]["options"], ["targeted_inspection"],
        )

    def test_local_computation_is_not_offered_to_the_farmer(self):
        connection = self.connection()
        profile = MODULE.field_profiles(str(self.repo))[0]
        finding = {
            "id": 21,
            "subject": "vineyard:field_1",
            "analysis": "source_disagreement",
            "verdict": "material_unresolved",
            "sample_size": 65,
            "confidence": 0.8,
            "options": [{"id": "deeper_analysis", "cost": "none"}],
        }
        with mock.patch.object(MODULE, "research_findings", return_value=[finding]), \
                mock.patch.object(MODULE.investigations, "render_anomaly") as render:
            candidates = MODULE.research_candidates(connection, profile, self.params())
        self.assertEqual(candidates, [])
        render.assert_not_called()

    def test_completed_research_is_rendered_as_a_bounded_result_not_a_question(self):
        findings = [
            {
                "id": 31,
                "question_id": 101,
                "subject": "vineyard:field_1",
                "analysis": "source_disagreement",
                "verdict": "material_unresolved",
                "created_at": "2026-08-18T08:00:00+00:00",
                "metrics": {
                    "shared_periods": 65,
                    "periods_beyond_tolerance": 61,
                    "median_difference": 3.4,
                    "median_absolute_difference": 3.4,
                    "tolerance": 2.0,
                    "unit": "°C",
                },
                "options": [{"id": "deeper_analysis", "cost": "none"}],
            },
            {
                "id": 32,
                "question_id": 102,
                "subject": "vineyard:field_2",
                "analysis": "source_disagreement",
                "verdict": "material_unresolved",
                "created_at": "2026-08-18T08:01:00+00:00",
                "metrics": {
                    "shared_periods": 65,
                    "periods_beyond_tolerance": 63,
                    "median_difference": 4.2,
                    "median_absolute_difference": 4.2,
                    "tolerance": 2.0,
                    "unit": "°C",
                },
                "options": [{"id": "deeper_analysis", "cost": "none"}],
            },
            {
                "id": 33,
                "question_id": 103,
                "subject": "vineyard:field_1",
                "analysis": "lagged_association",
                "verdict": "not_material",
                "created_at": "2026-08-19T08:00:00+00:00",
            },
            {
                "id": 34,
                "question_id": 104,
                "subject": "vineyard:field_1",
                "analysis": "baseline_deviation",
                "verdict": "insufficient_data",
                "created_at": "2026-08-19T08:01:00+00:00",
            },
            {
                "id": 35,
                "question_id": 105,
                "subject": "vineyard:field_1",
                "analysis": "threshold_materiality",
                "verdict": "material_unresolved",
                "created_at": "2026-08-19T08:02:00+00:00",
                "options": [{"id": "deeper_analysis", "cost": "none"}],
            },
        ]
        rendered = MODULE.render_research_result("ca", findings)
        self.assertEqual(rendered["title"], "Resultats de recerca autònoma")
        self.assertIn("5 preguntes noves", rendered["message"])
        self.assertIn("3.4-4.2 °C", rendered["message"])
        self.assertIn("61-63 de 65 dies", rendered["message"])
        self.assertIn("cap predictor nou", rendered["message"])
        self.assertIn("sense prou historial", rendered["message"])
        self.assertIn("continua automàticament", rendered["message"])
        self.assertNotIn("Voleu", rendered["message"])
        self.assertNotIn("Ref:", rendered["message"])

    def test_research_result_notification_is_informational_and_closes_itself(self):
        connection = self.connection()
        proposal = MODULE.create_proposal(connection, {
            "field_id": "field_1",
            "kind": "research_result",
            "target": "farmer",
            "priority": MODULE.RESEARCH_RESULT_PRIORITY,
            "title": "Resultats de recerca autònoma",
            "message": "Cap de les relacions provades ha superat el criteri de consistència.",
            "rationale": "A completed local result should be visible.",
            "evidence": [{"research_finding_ids": [31, 32]}],
            "confidence": 1.0,
            "requires_confirmation": False,
            "cooldown_days": 0,
        })
        outbox = self.root / "research-outbox"
        with mock.patch.dict(os.environ, {"PICOCLAW_OUTBOX": str(outbox)}):
            result = MODULE.notify_proposal(connection, proposal, str(self.state))
        self.assertEqual(result["status"], "success")
        package = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(package["dispatch_role"], "proactive_research_result")
        self.assertNotIn("Ref:", package["message"])
        stored = MODULE.proposal_by_id(connection, proposal["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertIsNone(MODULE.next_proposal(connection, only_unnotified=True))

    def test_research_result_bulletin_has_a_bounded_delivery_interval(self):
        connection = self.connection()
        profiles = MODULE.field_profiles(str(self.repo))
        finding = {
            "id": 41,
            "question_id": 201,
            "subject": "vineyard:field_1",
            "analysis": "lagged_association",
            "verdict": "not_material",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        with mock.patch.object(MODULE, "research_result_findings", return_value=[finding]):
            candidate = MODULE.research_result_candidate(
                connection, profiles, self.params(),
            )
            self.assertIsNotNone(candidate)
            self.assertFalse(candidate["requires_confirmation"])
            self.assertIsNotNone(MODULE.create_proposal(connection, candidate))
            repeated = MODULE.research_result_candidate(
                connection, profiles, self.params(),
            )
        self.assertIsNone(repeated)

    def test_source_comparison_names_values_and_units(self):
        rendered = MODULE.investigations.render_anomaly("ca", "N2 Chardonnay", {
            "subject": "vineyard:field_2",
            "analysis": "source_disagreement",
            "sample_size": 65,
            "metrics": {
                "primary_source": "forecast temperature",
                "reference_source": "observed station temperature",
                "shared_periods": 65,
                "periods_beyond_tolerance": 61,
                "median_absolute_difference": 3.4,
                "max_absolute_difference": 7.1,
                "unit": "°C",
            },
            "options": [{"id": "targeted_inspection", "cost": "none"}],
        })
        message = rendered["message"]
        self.assertIn("temperatura prevista", message)
        self.assertIn("temperatura observada a l'estació", message)
        self.assertIn("61 de 65", message)
        self.assertIn("3.4 °C", message)
        self.assertNotIn("black_rot_daily_predictions", message)

    def test_field_research_finding_is_not_attributed_to_the_first_field(self):
        connection = self.connection()
        profile = MODULE.field_profiles(str(self.repo))[0]
        findings = [{
            "id": 18,
            "subject": "vineyard:field_2",
            "analysis": "source_disagreement",
            "verdict": "material_unresolved",
            "sample_size": 30,
            "confidence": 0.7,
            "options": [{"id": "check_source", "cost": "none"}],
        }]
        with mock.patch.object(MODULE, "research_findings", return_value=findings), \
                mock.patch.object(MODULE.investigations, "render_anomaly") as render:
            candidates = MODULE.research_candidates(
                connection, profile, self.params(), include_board_wide=True,
            )
        self.assertEqual(candidates, [])
        render.assert_not_called()

    def test_board_research_finding_is_attached_only_when_requested(self):
        connection = self.connection()
        profile = MODULE.field_profiles(str(self.repo))[0]
        finding = {
            "id": 19,
            "subject": "board",
            "analysis": "data_gap",
            "verdict": "material_unresolved",
            "sample_size": 12,
            "confidence": 0.8,
            "options": [{"id": "check_source", "cost": "none"}],
        }
        rendered = {"title": "Board finding", "message": "A source stopped."}
        with mock.patch.object(MODULE, "research_findings", return_value=[finding]), \
                mock.patch.object(
                    MODULE.investigations, "render_anomaly", return_value=rendered,
                ):
            excluded = MODULE.research_candidates(
                connection, profile, self.params(), include_board_wide=False,
            )
            included = MODULE.research_candidates(
                connection, profile, self.params(), include_board_wide=True,
            )
        self.assertEqual(excluded, [])
        self.assertEqual(len(included), 1)

    def test_old_permission_prompt_for_local_analysis_is_retired(self):
        connection = self.connection()
        proposal = MODULE.create_proposal(connection, {
            "field_id": "field_1",
            "kind": "research:source_disagreement",
            "target": "farmer",
            "priority": MODULE.RESEARCH_NOTIFICATION_PRIORITY,
            "title": "Research finding",
            "message": "Should I analyse a longer window?",
            "rationale": "A narrow comparison differed.",
            "evidence": [{
                "research_finding_id": 17,
                "options": ["deeper_analysis"],
            }],
            "confidence": 0.8,
            "requires_confirmation": True,
            "cooldown_days": 14,
        })
        retired = MODULE.retire_autonomous_research_proposals(connection)
        self.assertEqual(retired, [proposal["id"]])
        self.assertEqual(
            MODULE.proposal_by_id(connection, proposal["id"])["status"], "completed",
        )

    def test_schema_upgrade_repairs_pending_silent_research_proposals(self):
        connection = self.connection()
        MODULE.save_profiles(connection, MODULE.field_profiles(str(self.repo)))
        proposal = MODULE.create_proposal(connection, {
            "field_id": "field_1",
            "kind": "research:source_disagreement",
            "target": "farmer",
            "priority": 68,
            "title": "Research finding",
            "message": "Two sources disagree.",
            "rationale": "Material local evidence.",
            "evidence": [{"research_finding_id": 17}],
            "confidence": 0.8,
            "requires_confirmation": True,
            "cooldown_days": 14,
        })
        self.assertEqual(proposal["priority"], 68)
        connection.close()

        upgraded = self.connection()
        repaired = MODULE.proposal_by_id(upgraded, proposal["id"])
        self.assertEqual(
            repaired["priority"], MODULE.RESEARCH_NOTIFICATION_PRIORITY,
        )

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
