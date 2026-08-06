"""The research engine must be useful, quiet, and domain-neutral.

Useful: it finds the shapes worth a second look in ordinary monitor journals.
Quiet: a constant channel, an ordinary maximum and a settled question produce
nothing. Domain-neutral: a vineyard question is expressed as parameters for the
same analyses that read a camera or a microphone journal.
"""

import datetime as dt
import importlib.util
import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "research_agent"
sys.path.insert(0, str(SKILL))

ENGINE_SPEC = importlib.util.spec_from_file_location("engine", SKILL / "engine.py")
ENGINE = importlib.util.module_from_spec(ENGINE_SPEC)
sys.modules["engine"] = ENGINE
ENGINE_SPEC.loader.exec_module(ENGINE)

ANALYSES_SPEC = importlib.util.spec_from_file_location("analyses", SKILL / "analyses.py")
ANALYSES = importlib.util.module_from_spec(ANALYSES_SPEC)
sys.modules["analyses"] = ANALYSES
ANALYSES_SPEC.loader.exec_module(ANALYSES)


class ResearchTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.journals = self.root / "monitors"
        self.journals.mkdir()
        self.now = dt.datetime.now(dt.timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def write_journal(self, name, records):
        path = self.journals / name
        path.write_text(
            "\n".join(json.dumps(record) for record in records), encoding="utf-8",
        )
        return path

    def steady(self, name="steady.jsonl", samples=40, value=0.5, interval_minutes=30):
        return self.write_journal(name, [
            {
                "timestamp": (self.now - dt.timedelta(minutes=(samples - index) * interval_minutes)).isoformat(),
                "value": round(value + (index % 3) * 0.01, 3),
            }
            for index in range(samples)
        ])

    def connection(self):
        return ENGINE.connect(str(self.root / "state"))

    def context(self, **extra):
        base = {
            "journal_dirs": [str(self.journals)],
            "calibration_sources": {},
            "now": self.now,
            "limits": {"max_lines": 400},
            "params_in": {},
        }
        base.update(extra)
        return base

    def run_skill(self, payload):
        proc = subprocess.run(
            [str(SKILL / "run.sh")],
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))


class SignalScanTest(ResearchTestCase):
    def test_a_steady_journal_raises_no_questions(self):
        self.steady()
        connection = self.connection()
        raised = ANALYSES.scan_journals(connection, self.context())
        self.assertEqual(raised, [])

    def test_a_constant_channel_is_not_a_discovery(self):
        self.write_journal("constant.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(minutes=(30 - index) * 10)).isoformat(),
                "battery": 100, "mode": 3,
            }
            for index in range(30)
        ])
        connection = self.connection()
        self.assertEqual(ANALYSES.scan_journals(connection, self.context()), [])

    def test_an_ordinary_counter_maximum_is_not_a_range_limit(self):
        self.write_journal("counter.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(minutes=(40 - index) * 10)).isoformat(),
                "events": index % 5,
            }
            for index in range(40)
        ])
        connection = self.connection()
        raised = ANALYSES.scan_journals(connection, self.context())
        self.assertEqual([item["analysis"] for item in raised], [])

    def test_a_clipped_sensor_is_found(self):
        random.seed(11)
        self.write_journal("light.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(minutes=(60 - index) * 10)).isoformat(),
                "lux": min(100.0, round(random.gauss(88, 14), 1)),
            }
            for index in range(60)
        ])
        connection = self.connection()
        raised = ANALYSES.scan_journals(connection, self.context())
        self.assertIn("ceiling_saturation", [item["analysis"] for item in raised])

    def test_a_level_shift_is_not_hidden_by_its_own_size(self):
        self.write_journal("ripeness.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(hours=(40 - index) * 3)).isoformat(),
                "purple_ratio": round(0.10 + (0.35 if index >= 20 else 0.0), 3),
            }
            for index in range(40)
        ])
        connection = self.connection()
        raised = ANALYSES.scan_journals(connection, self.context())
        self.assertIn("level_shift", [item["analysis"] for item in raised])

    def test_a_stopped_source_is_found(self):
        self.write_journal("audio.jsonl", [
            {
                "timestamp": (
                    self.now - dt.timedelta(days=2)
                    - dt.timedelta(minutes=(30 - index) * 30)
                ).isoformat(),
                "rms": 0.2 + (index % 7) * 0.01,
            }
            for index in range(30)
        ])
        connection = self.connection()
        raised = ANALYSES.scan_journals(connection, self.context())
        self.assertIn("data_gap", [item["analysis"] for item in raised])


class CycleTest(ResearchTestCase):
    def test_a_cycle_stays_inside_its_budget(self):
        for index in range(6):
            self.write_journal(f"probe_{index}.jsonl", [
                {
                    "timestamp": (self.now - dt.timedelta(hours=(30 - step) * 2)).isoformat(),
                    "value": round(1.0 + (2.0 if step >= 15 else 0.0), 3),
                }
                for step in range(30)
            ])
        connection = self.connection()
        result = ENGINE.cycle(
            connection, ANALYSES.BUILTIN_ANALYSES, self.context(),
            budget={"max_questions": 2, "max_seconds": 10},
            scanners=ANALYSES.BUILTIN_SCANNERS,
        )
        self.assertLessEqual(len(result["investigated"]), 2)
        self.assertGreater(len(result["raised"]), 2)

    def test_questions_with_different_scopes_keep_separate_findings(self):
        self.write_journal("two_channels.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(hours=(30 - index) * 2)).isoformat(),
                "left": round(1.0 + (2.0 if index >= 15 else 0.0), 3),
                "right": round(5.0 + (9.0 if index >= 15 else 0.0), 3),
            }
            for index in range(30)
        ])
        connection = self.connection()
        result = ENGINE.cycle(
            connection, ANALYSES.BUILTIN_ANALYSES, self.context(),
            budget={"max_questions": 4}, scanners=ANALYSES.BUILTIN_SCANNERS,
        )
        identifiers = {item["id"] for item in result["investigated"] if item.get("id")}
        self.assertEqual(len(identifiers), len(result["investigated"]))

    def test_an_answered_question_is_not_asked_again(self):
        self.steady()
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "steady", "the level of value changed", "level_shift",
            {"source": {"kind": "journal", "path": str(self.journals / "steady.jsonl")},
             "key": "value"},
        )
        finding = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)
        self.assertEqual(
            ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN), [],
        )

    def test_findings_reach_the_nano_evidence_journal(self):
        self.steady()
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "steady", "did the source stop", "data_gap",
            {"source": {"kind": "journal", "path": str(self.journals / "steady.jsonl")}},
        )
        finding = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        journal = self.root / "experiments.jsonl"
        self.assertTrue(ENGINE.journal_finding(str(journal), finding))
        entry = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["task_id"], "autonomous_research")
        self.assertIn("verdict", entry)
        self.assertIn("metrics_after", entry)


class DecisionAndWatchTest(ResearchTestCase):
    def open_finding(self, connection):
        random.seed(3)
        self.write_journal("light.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(minutes=(60 - index) * 10)).isoformat(),
                "lux": min(100.0, round(random.gauss(88, 14), 1)),
            }
            for index in range(60)
        ])
        question = ENGINE.open_question(
            connection, "light", "lux piles up against its maximum", "ceiling_saturation",
            {"source": {"kind": "journal", "path": str(self.journals / "light.jsonl")},
             "key": "lux"},
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def test_a_refusal_closes_the_question_instead_of_rescheduling_it(self):
        connection = self.connection()
        finding = self.open_finding(connection)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        ENGINE.record_decision(connection, finding["id"], "rejected", note="not now")
        self.assertEqual(
            ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN), [],
        )
        stored = ENGINE.finding_by_id(connection, finding["id"])
        self.assertEqual(stored["status"], "declined")

    def test_an_accepted_watch_fires_once_when_the_pattern_returns(self):
        connection = self.connection()
        finding = self.open_finding(connection)
        ENGINE.record_decision(connection, finding["id"], "accepted", option_id="observe")
        ENGINE.arm_watch(connection, finding["subject"], finding["analysis"])
        repeat = ENGINE.store_finding(connection, {
            "subject": finding["subject"], "analysis": finding["analysis"],
            "scope": "later", "claim": finding["claim"], "method": finding["method"],
            "verdict": ENGINE.VERDICT_MATERIAL, "headline": {"round": 2},
        })
        triggered = ENGINE.trigger_watches(connection, repeat)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(ENGINE.trigger_watches(connection, repeat), [])

    def test_repeated_refusals_raise_a_question_about_the_threshold(self):
        connection = self.connection()
        finding = self.open_finding(connection)
        for _ in range(2):
            ENGINE.record_decision(connection, finding["id"], "rejected")
        alerts = self.write_journal("alerts.jsonl", [
            {"timestamp": (self.now - dt.timedelta(days=day)).isoformat()}
            for day in (30, 25, 20, 15, 10)
        ])
        outcomes = self.write_journal("outcomes.jsonl", [
            {"timestamp": (self.now - dt.timedelta(days=day - 1)).isoformat(),
             "outcome": "clean"}
            for day in (30, 25, 20, 15, 10)
        ])
        context = self.context(calibration_sources={
            finding["subject"]: {
                "alerts": {"kind": "journal", "path": str(alerts)},
                "outcomes": {"kind": "journal", "path": str(outcomes)},
                "positive_labels": ["confirmed"],
                "negative_labels": ["clean"],
            },
        })
        raised = ANALYSES.scan_feedback(connection, context)
        self.assertEqual([item["analysis"] for item in raised], ["outcome_calibration"])
        calibration = ENGINE.run_question(
            connection, raised[0], ANALYSES.BUILTIN_ANALYSES, context,
        )
        self.assertEqual(calibration["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(calibration["metrics"]["confirmed"], 0)
        self.assertEqual(calibration["metrics"]["negative"], 5)


class AdapterFeedbackTest(ResearchTestCase):
    """An answer given over Telegram must reach the engine that asked."""

    def test_an_echoed_refusal_counts_as_feedback(self):
        connection = self.connection()
        for _ in range(2):
            ENGINE.record_external_decision(
                connection, "vineyard:field_1", "leaf_wetness_proxy", "rejected",
                note="not now", source="proactive-field-agent",
            )
        alerts = self.write_journal("alerts.jsonl", [
            {"timestamp": (self.now - dt.timedelta(days=day)).isoformat()}
            for day in (20, 15, 10, 5)
        ])
        outcomes = self.write_journal("outcomes.jsonl", [
            {"timestamp": (self.now - dt.timedelta(days=day - 1)).isoformat(),
             "outcome": "clean"}
            for day in (20, 15, 10, 5)
        ])
        context = self.context(calibration_sources={
            "vineyard:field_1": {
                "alerts": {"kind": "journal", "path": str(alerts)},
                "outcomes": {"kind": "journal", "path": str(outcomes)},
                "positive_labels": ["confirmed"], "negative_labels": ["clean"],
            },
        })
        raised = ANALYSES.scan_feedback(connection, context)
        self.assertEqual(
            [(item["subject"], item["analysis"]) for item in raised],
            [("vineyard:field_1", "outcome_calibration")],
        )
        finding = ENGINE.run_question(
            connection, raised[0], ANALYSES.BUILTIN_ANALYSES, context,
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(finding["metrics"]["negative"], 4)

    def test_one_refusal_is_not_yet_a_pattern(self):
        connection = self.connection()
        ENGINE.record_external_decision(
            connection, "vineyard:field_1", "leaf_wetness_proxy", "rejected",
        )
        context = self.context(calibration_sources={
            "vineyard:field_1": {"alerts": {"kind": "inline", "records": []},
                                 "outcomes": {"kind": "inline", "records": []}},
        })
        self.assertEqual(ANALYSES.scan_feedback(connection, context), [])


class QuietBoardTest(ResearchTestCase):
    """Flash is the scarcest thing on the board. A quiet hour must cost nothing."""

    def payload(self, **extra):
        return {
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(self.root / "no-packs"),
            **extra,
        }

    def footprint(self):
        database = self.root / "state" / "research.db"
        journal = self.root / "experiments.jsonl"
        return (
            database.stat().st_mtime_ns if database.exists() else 0,
            journal.stat().st_size if journal.exists() else 0,
        )

    def stale_journal(self):
        self.write_journal("audio.jsonl", [
            {
                "timestamp": (
                    self.now - dt.timedelta(days=2)
                    - dt.timedelta(minutes=(30 - index) * 30)
                ).isoformat(),
                "rms": 0.2 + (index % 7) * 0.01,
            }
            for index in range(30)
        ])

    def test_a_cycle_with_no_new_evidence_writes_nothing(self):
        self.stale_journal()
        self.run_skill(self.payload())
        before = self.footprint()
        for _ in range(3):
            result = self.run_skill(self.payload())
            self.assertEqual(result["status"], "skipped")
            self.assertFalse(result["wrote"])
        self.assertEqual(self.footprint(), before)

    def test_new_evidence_wakes_it_up(self):
        self.stale_journal()
        self.run_skill(self.payload())
        self.assertEqual(self.run_skill(self.payload())["status"], "skipped")
        with open(self.journals / "audio.jsonl", "a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps({"timestamp": self.now.isoformat(), "rms": 0.9}))
        self.assertEqual(self.run_skill(self.payload())["status"], "success")

    def test_the_clock_alone_reopens_the_question_eventually(self):
        self.stale_journal()
        self.run_skill(self.payload())
        self.assertEqual(self.run_skill(self.payload())["status"], "skipped")
        # Some conclusions age even when no file changes.
        self.assertEqual(
            self.run_skill(self.payload(idle_recheck_seconds=0))["status"], "success",
        )

    def test_an_unchanged_conclusion_is_not_journalled_again(self):
        self.stale_journal()
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "audio", "did the source stop", "data_gap",
            {"source": {"kind": "journal", "path": str(self.journals / "audio.jsonl")}},
        )
        journal = self.root / "experiments.jsonl"
        first = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertTrue(ENGINE.journal_finding(str(journal), first))
        again = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertFalse(again["changed"])
        self.assertFalse(ENGINE.journal_finding(str(journal), again))
        self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 1)

    def test_a_clock_only_metric_is_not_a_change(self):
        stored = {
            "metrics_json": json.dumps({"records": 30, "seconds_since_last_record": 100}),
            "window_start": "a", "window_end": "b", "sample_size": 30,
            "open_question": None, "options_json": "[]", "limitations_json": "[]",
        }
        unchanged = {
            "metrics": {"records": 30, "seconds_since_last_record": 999999},
            "window_start": "a", "window_end": "b", "sample_size": 30,
            "open_question": None, "options": [], "limitations": [],
        }
        self.assertFalse(ENGINE.finding_changed(stored, unchanged))
        real = dict(unchanged, metrics={"records": 31, "seconds_since_last_record": 100})
        self.assertTrue(ENGINE.finding_changed(stored, real))


class AutonomousFollowUpTest(ResearchTestCase):
    """The board may offer to keep digging on its own time."""

    def shifted_finding(self, connection):
        self.write_journal("probe.jsonl", [
            {
                "timestamp": (self.now - dt.timedelta(hours=(40 - index) * 2)).isoformat(),
                "value": round(1.0 + (3.0 if index >= 20 else 0.0), 3),
            }
            for index in range(40)
        ])
        question = ENGINE.open_question(
            connection, "probe", "the level of value changed", "level_shift",
            {"source": {"kind": "journal", "path": str(self.journals / "probe.jsonl")},
             "key": "value"},
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def test_a_material_finding_offers_to_investigate_further(self):
        connection = self.connection()
        finding = self.shifted_finding(connection)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertIn(
            ENGINE.DEEPER_ANALYSIS_OPTION,
            [option["id"] for option in finding["options"]],
        )

    def test_accepting_it_opens_a_wider_question_the_board_runs_itself(self):
        connection = self.connection()
        finding = self.shifted_finding(connection)
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.DEEPER_ANALYSIS_OPTION,
        )
        follow_up = stored["follow_up_question"]
        self.assertEqual(follow_up["analysis"], "level_shift")
        opened = [
            item for item in ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN)
            if item["id"] == follow_up["id"]
        ][0]
        self.assertEqual(opened["params"]["depth"], "extended")
        self.assertEqual(
            opened["params"]["source"]["max_lines"],
            400 * ENGINE.DEEPER_ANALYSIS_FACTOR,
        )

    def test_declining_opens_nothing(self):
        connection = self.connection()
        finding = self.shifted_finding(connection)
        stored = ENGINE.record_decision(
            connection, finding["id"], "rejected",
            option_id=ENGINE.DEEPER_ANALYSIS_OPTION,
        )
        self.assertIsNone(stored.get("follow_up_question"))
        self.assertEqual(ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN), [])


class SafetyTest(ResearchTestCase):
    def test_a_broken_pack_does_not_stop_the_others(self):
        good = self.root / "packs" / "good"
        bad = self.root / "packs" / "bad"
        good.mkdir(parents=True)
        bad.mkdir(parents=True)
        (good / "pack.py").write_text(
            "PACK = {'name': 'good', 'analyses': {}}\n", encoding="utf-8",
        )
        (bad / "pack.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        errors = []
        packs = ENGINE.load_packs([str(self.root / "packs")], errors)
        self.assertEqual([pack["name"] for pack in packs], ["good"])
        self.assertEqual(len(errors), 1)
        self.assertIn("boom", errors[0]["error"])

    def test_sqlite_sources_reject_unsafe_identifiers(self):
        database = self.root / "app.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE readings(day TEXT, value REAL)")
        connection.commit()
        connection.close()
        with self.assertRaises(ValueError):
            ANALYSES.read_sqlite(str(database), "readings; DROP TABLE readings", ["value"])
        with self.assertRaises(ValueError):
            ANALYSES.read_sqlite(
                str(database), "readings", ["value"], where="1=1 OR value > 0",
            )

    def test_an_analysis_that_cannot_run_never_becomes_a_report(self):
        self.write_journal("short.jsonl", [
            {"timestamp": self.now.isoformat(), "value": 1.0},
        ])
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "short", "the level changed", "level_shift",
            {"source": {"kind": "journal", "path": str(self.journals / "short.jsonl")},
             "key": "value"},
        )
        finding = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_INSUFFICIENT)
        self.assertNotIn(finding["verdict"], ENGINE.REPORTABLE_VERDICTS)


class EntrypointTest(ResearchTestCase):
    def test_the_shell_entrypoint_runs_a_cycle_and_self_test(self):
        self.steady()
        payload = {
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(self.root / "empty"),
        }
        result = self.run_skill(payload)
        self.assertEqual(result["status"], "success")
        self.assertIn("safety", result)
        self.assertEqual(result["investigated"], [])
        check = self.run_skill(dict(payload, mode="self_test"))
        self.assertTrue(check["installed"])
        self.assertIn("threshold_materiality", check["checks"]["analyses"])
        self.assertIn("level_shift", check["checks"]["analyses"])


class VineyardPackTest(ResearchTestCase):
    """The vineyard is a pack of parameters, not a second research engine."""

    def build_repo(self, rh_max=97.0, ambiguous_days=(30, 12)):
        repo = self.root / "goidanich"
        repo.mkdir()
        (repo / "agent_config.yaml").write_text(json.dumps({
            "board": {"id": "board_test"},
            "fields": [{"id": "field_1", "name": "Camp Nord"}],
        }), encoding="utf-8")
        database = sqlite3.connect(repo / "goidanich.db")
        database.execute(
            "CREATE TABLE black_rot_daily_predictions(field_id TEXT, day TEXT,"
            " infection_index REAL, potential_infection_index REAL,"
            " measured_wet_hours INTEGER, max_humi REAL)"
        )
        end = dt.date(2026, 6, 30)
        for offset in range(60):
            back = 59 - offset
            day = (end - dt.timedelta(days=back)).isoformat()
            if back in ambiguous_days:
                row = (40.0, 118.0, 0, 93.0)
            else:
                # A healthy station reaches saturation now and then; a station
                # whose ceiling sits below the criterion never does.
                humidity = rh_max if offset % 10 == 0 else min(rh_max, 88.0)
                row = (4.0, 6.0, 0, humidity)
            database.execute(
                "INSERT INTO black_rot_daily_predictions VALUES(?,?,?,?,?,?)",
                ("field_1", day) + row,
            )
        database.commit()
        database.close()
        return repo

    def test_the_pack_reproduces_the_domain_findings_with_generic_analyses(self):
        repo = self.build_repo()
        result = self.run_skill({
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "repo_path": str(repo), "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(ROOT / "skills"), "max_questions": 6,
        })
        self.assertIn("vineyard_guard", result["packs"])
        self.assertEqual(result["pack_errors"], [])
        by_analysis = {
            item["analysis"]: item for item in result["investigated"] if item.get("analysis")
        }
        self.assertEqual(
            by_analysis["threshold_materiality"]["verdict"], "material_unresolved",
        )
        self.assertEqual(
            by_analysis["threshold_materiality"]["subject"], "vineyard:field_1",
        )
        self.assertEqual(
            by_analysis["ceiling_saturation"]["verdict"], "not_material",
        )

    def test_an_unreachable_station_criterion_is_material(self):
        repo = self.build_repo(rh_max=91.0)
        result = self.run_skill({
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "repo_path": str(repo), "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(ROOT / "skills"), "max_questions": 6,
        })
        ceiling = [
            item for item in result["investigated"]
            if item.get("analysis") == "ceiling_saturation"
        ][0]
        self.assertEqual(ceiling["verdict"], "material_unresolved")
        self.assertIn("reachable", ceiling["open_question"])

    def test_alerts_and_outcomes_may_use_different_timestamp_columns(self):
        """The two tables of a calibration rarely share a column name."""
        repo = self.build_repo()
        state = self.root / "proactive"
        state.mkdir()
        database = sqlite3.connect(state / "proactive_field.db")
        database.execute("CREATE TABLE proposals(field_id TEXT, kind TEXT, notified_at TEXT)")
        database.execute(
            "CREATE TABLE operations(field_id TEXT, operation_type TEXT, occurred_at TEXT)"
        )
        for index in range(5):
            database.execute(
                "INSERT INTO proposals VALUES(?,?,?)",
                ("field_1", "field_check",
                 (self.now - dt.timedelta(days=30 - index * 5)).isoformat()),
            )
            database.execute(
                "INSERT INTO operations VALUES(?,?,?)",
                ("field_1", "clean_inspection",
                 (self.now - dt.timedelta(days=29 - index * 5)).isoformat()),
            )
        database.commit()
        database.close()
        pack = ENGINE.load_module(
            ROOT / "skills" / "proactive_field_agent" / "pack.py", "vineyard_pack_under_test",
        )
        sources = pack.calibration_sources({
            "params_in": {"repo_path": str(repo), "state_dir": str(state)},
        })
        result = self.run_skill({
            "mode": "investigate", "state_dir": str(self.root / "state"),
            "repo_path": str(repo), "journal_dirs": str(self.journals),
            "pack_dirs": str(ROOT / "skills"),
            "analysis": "outcome_calibration", "subject": "vineyard:field_1",
            "params": sources["vineyard:field_1"],
        })
        finding = result["findings"][0]
        self.assertEqual(finding["metrics"]["alerts_sent"], 5)
        self.assertEqual(finding["metrics"]["alerts_answered"], 5)
        self.assertEqual(finding["metrics"]["negative"], 5)
        self.assertEqual(finding["verdict"], "material_unresolved")
        self.assertIn("raise_alert_threshold", [item["id"] for item in finding["options"]])

    def test_no_vineyard_checkout_means_no_vineyard_questions(self):
        result = self.run_skill({
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "repo_path": str(self.root / "absent"),
            "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(ROOT / "skills"),
        })
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["declared_questions"], 0)
        self.assertEqual(result["pack_errors"], [])


if __name__ == "__main__":
    unittest.main()
