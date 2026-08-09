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
from unittest import mock


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


class NeighbourReportsTest(ResearchTestCase):
    """What other reporters see is a prior, never a confirmation."""

    def context_with(self, **extra):
        return self.context(**extra)

    def question(self, connection, local_value, latitude=41.315, longitude=1.705,
                 days_ago=3):
        moment = (self.now - dt.timedelta(days=days_ago)).isoformat()
        return ENGINE.open_question(
            connection, "field_1", "neighbours report something", "neighbour_reports",
            {
                "events": {"kind": "inline", "records": [{
                    "timestamp": moment, "peer_id": "peer_a", "signal_type": "contagion",
                    "metadata": json.dumps({"latitude": latitude, "longitude": longitude,
                                            "board_id": "Peer A"}),
                }]},
                "origin": [41.3, 1.7],
                "time_key": "timestamp",
                "label_key": "signal_type",
                "accepted_labels": ["contagion"],
                "metadata_key": "metadata",
                "local_value": local_value,
                "alert_threshold": 85.0,
                "local_radius_km": 5.0,
            },
        )

    def test_a_near_report_the_local_model_misses_is_material(self):
        connection = self.connection()
        finding = ENGINE.run_question(
            connection, self.question(connection, local_value=4.0),
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertLess(finding["metrics"]["nearest_km"], 5.0)
        self.assertFalse(finding["metrics"]["local_in_alert"])
        self.assertIn(
            "targeted_inspection", [item["id"] for item in finding["options"]],
        )
        self.assertTrue(any("neighbour" in item for item in finding["limitations"]))

    def test_a_local_model_that_already_agrees_says_nothing(self):
        connection = self.connection()
        finding = ENGINE.run_question(
            connection, self.question(connection, local_value=120.0),
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_a_distant_report_says_nothing(self):
        connection = self.connection()
        finding = ENGINE.run_question(
            connection,
            self.question(connection, local_value=4.0, latitude=41.9, longitude=2.4),
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_an_old_report_falls_out_of_the_window(self):
        connection = self.connection()
        finding = ENGINE.run_question(
            connection, self.question(connection, local_value=4.0, days_ago=90),
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_INSUFFICIENT)
        self.assertTrue(finding.get("skipped") or finding["sample_size"] == 0)


class SkillBackedEvidenceTest(ResearchTestCase):
    """Research should reuse work the board already knows how to do."""

    def write_seasons(self, values, metric="season.rain_total_mm"):
        results = self.root / "results"
        results.mkdir(exist_ok=True)
        for year, value in values.items():
            payload = {
                "field_id": "field_1", "start": f"{year}-04-01", "end": f"{year}-09-30",
                "season": {"rain_total_mm": value, "days": 183},
                "indices": {"gdd_base10": 1500},
            }
            (results / f"season_climate_field_1_{year}.json").write_text(
                json.dumps(payload), encoding="utf-8",
            )
        return str(results / "season_climate_field_1_*.json")

    def ask(self, connection, pattern, **extra):
        question = ENGINE.open_question(
            connection, "vineyard:field_1", "this season is unlike the others",
            "baseline_deviation",
            {
                "source": {"kind": "glob", "pattern": pattern},
                "key": "season.rain_total_mm",
                "period_key": "end", "period_slice": 4,
                **extra,
            },
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def test_an_ordinary_season_says_nothing(self):
        pattern = self.write_seasons({
            "2021": 372.0, "2022": 344.0, "2023": 401.0, "2024": 358.0, "2025": 370.0,
        })
        finding = self.ask(self.connection(), pattern)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_a_season_unlike_its_predecessors_is_material(self):
        pattern = self.write_seasons({
            "2021": 372.0, "2022": 344.0, "2023": 401.0, "2024": 358.0, "2025": 366.0,
            "2026": 118.0,
        })
        finding = self.ask(self.connection(), pattern)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(finding["metrics"]["current_period"], "2026")
        self.assertEqual(finding["metrics"]["direction"], "below")
        self.assertEqual(finding["metrics"]["baseline_periods"], 5)
        self.assertGreater(finding["metrics"]["distance_from_baseline"], 3.0)

    def test_too_few_previous_seasons_is_not_a_conclusion(self):
        pattern = self.write_seasons({"2025": 366.0, "2026": 118.0})
        finding = self.ask(self.connection(), pattern)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_INSUFFICIENT)

    def fake_skill(self, name="fake_climate", payload=None, exit_code=0):
        root = self.root / "skills" / name
        root.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload if payload is not None else {"reports": [{"v": 1}]})
        script = root / "run.sh"
        script.write_text(
            "#!/bin/sh\n"
            + (f"cat <<'JSON'\n{body}\nJSON\n" if exit_code == 0 else "echo boom >&2\n")
            + f"exit {exit_code}\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return root.parent

    def test_an_installed_skill_can_be_an_evidence_source(self):
        skills_root = self.fake_skill(payload={"reports": [{"v": 1}, {"v": 2}]})
        with mock.patch.object(ANALYSES, "SKILL_ROOTS", (skills_root,)):
            records = ANALYSES.load_records({
                "kind": "skill", "name": "fake_climate", "records_path": "reports",
            })
        self.assertEqual(records, [{"v": 1}, {"v": 2}])

    def test_a_skill_name_may_not_be_a_path(self):
        with self.assertRaises(ValueError):
            ANALYSES.resolve_skill("../../etc/passwd")

    def test_a_failed_refresh_still_leaves_the_baseline_readable(self):
        pattern = self.write_seasons({
            "2021": 372.0, "2022": 344.0, "2023": 401.0, "2024": 358.0, "2025": 366.0,
        })
        skills_root = self.fake_skill(name="broken_skill", exit_code=1)
        with mock.patch.object(ANALYSES, "SKILL_ROOTS", (skills_root,)):
            records = ANALYSES.load_records({
                "kind": "glob", "pattern": pattern,
                "refresh": {"kind": "skill", "name": "broken_skill"},
            })
        self.assertEqual(len(records), 5)

    def test_an_expensive_question_sets_its_own_pace(self):
        connection = self.connection()
        pattern = self.write_seasons({
            "2021": 372.0, "2022": 344.0, "2023": 401.0, "2024": 358.0, "2025": 366.0,
        })
        self.ask(connection, pattern, min_interval_seconds=7 * 24 * 3600)
        # Just answered, and it asked not to be run again this week.
        self.assertEqual(ENGINE.due_questions(connection, limit=3), [])


class LaggedAssociationTest(ResearchTestCase):
    """A hypothesis generator that finds patterns in noise is worse than none."""

    def series(self, values, key, start=dt.date(2026, 4, 1)):
        return [
            {"timestamp": (start + dt.timedelta(days=index)).isoformat(), key: value}
            for index, value in enumerate(values)
        ]

    def ask(self, driver, response, lags=(0, 1, 2, 3, 5, 7), **extra):
        context = self.context()
        context["params"] = {
            "driver": {"source": {"kind": "inline", "records": self.series(driver, "x")},
                       "key": "x", "label": "driver"},
            "response": {"source": {"kind": "inline", "records": self.series(response, "y")},
                         "key": "y", "label": "response"},
            "lags": list(lags),
            **extra,
        }
        context["subject"] = "bench"
        return ANALYSES.lagged_association(context)

    def noise(self, seed, count=140):
        random.seed(seed)
        return [random.gauss(0, 1) for _ in range(count)]

    def test_independent_noise_produces_no_hypothesis(self):
        for seed in range(12):
            finding = self.ask(self.noise(seed), self.noise(seed + 100))
            self.assertEqual(
                finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL,
                f"seed {seed} invented a relationship in noise",
            )

    def test_a_shared_seasonal_trend_is_not_a_relationship(self):
        random.seed(7)
        trend = [index * 0.05 for index in range(140)]
        left = [trend[index] + random.gauss(0, 1) for index in range(140)]
        right = [trend[index] + random.gauss(0, 1) for index in range(140)]
        finding = self.ask(left, right)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_a_real_lead_is_found_at_the_right_lag(self):
        random.seed(3)
        driver = [random.gauss(0, 1) for _ in range(140)]
        response = [
            (driver[index - 3] * 1.2 if index >= 3 else 0.0) + random.gauss(0, 0.5)
            for index in range(140)
        ]
        finding = self.ask(driver, response)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(finding["metrics"]["strongest_lag_days"], 3)
        self.assertIn(3, finding["metrics"]["surviving_lags"])

    def test_it_reports_precedence_and_refuses_causation(self):
        random.seed(3)
        driver = [random.gauss(0, 1) for _ in range(140)]
        response = [
            (driver[index - 3] * 1.2 if index >= 3 else 0.0) + random.gauss(0, 0.5)
            for index in range(140)
        ]
        finding = self.ask(driver, response)
        text = " ".join(finding["limitations"]).lower()
        self.assertIn("not causation", text)
        self.assertIn("or both", finding["open_question"])
        self.assertNotIn("causes", finding["open_question"])

    def test_trying_more_lags_does_not_buy_a_result(self):
        finding = self.ask(self.noise(21), self.noise(22), lags=tuple(range(11)))
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)
        self.assertLess(finding["metrics"]["corrected_alpha"], 0.01)

    def test_too_little_overlap_is_not_a_conclusion(self):
        finding = self.ask(self.noise(1, count=20), self.noise(2, count=20))
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_INSUFFICIENT)

    def test_a_missing_response_series_names_what_it_would_need(self):
        context = self.context()
        context["params"] = {
            "driver": {"source": {"kind": "inline", "records": self.series(self.noise(4), "x")},
                       "key": "x", "label": "night humidity"},
            "response": {"source": {"kind": "inline", "records": []},
                         "key": "count", "label": "insect counts"},
            "missing_question": "whether insect pressure follows humid nights here",
            "missing_options": [{"id": "start_insect_counts", "cost": "low", "params": {}}],
        }
        finding = ANALYSES.lagged_association(context)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_INSUFFICIENT)
        self.assertEqual(finding["metrics"]["missing_measurement"], ["insect counts"])
        self.assertEqual(
            [option["id"] for option in finding["options"]], ["start_insect_counts"],
        )

    def test_night_and_day_windows_are_separated(self):
        base = dt.date(2026, 5, 1)
        records = []
        for day in range(3):
            for hour in range(24):
                moment = dt.datetime.combine(
                    base + dt.timedelta(days=day), dt.time(hour), dt.timezone.utc,
                )
                records.append({
                    "timestamp": moment.isoformat(),
                    "rh": 90.0 if (hour >= 22 or hour <= 6) else 40.0,
                })
        night = ANALYSES.daily_window_series(records, "rh", "timestamp", (22, 6), "mean")
        day_time = ANALYSES.daily_window_series(records, "rh", "timestamp", (10, 18), "mean")
        self.assertTrue(all(value == 90.0 for value in night.values()))
        self.assertTrue(all(value == 40.0 for value in day_time.values()))
        # A window that wraps midnight belongs to the morning it ends on.
        self.assertIn((base + dt.timedelta(days=1)).isoformat(), night)


class DiscoveryTest(ResearchTestCase):
    """The board may pair series nobody paired for it, within a budget."""

    def catalogue(self):
        return [
            {"name": "a", "role": "driver", "subject": "weather",
             "source": {"kind": "inline", "records": []}, "key": "x", "label": "driver a"},
            {"name": "b", "role": "driver", "subject": "weather",
             "source": {"kind": "inline", "records": []}, "key": "y", "label": "driver b"},
            {"name": "c", "role": "response", "subject": "field",
             "source": {"kind": "inline", "records": []}, "key": "z", "label": "response c"},
        ]

    def test_pairs_are_proposed_within_a_budget(self):
        connection = self.connection()
        context = self.context(series=self.catalogue(), max_new_pairs=1)
        first = ANALYSES.scan_series_pairs(connection, context)
        self.assertEqual(len(first), 1)
        second = ANALYSES.scan_series_pairs(connection, context)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(len(ANALYSES.scan_series_pairs(connection, context)), 0)

    def test_a_refuted_pair_is_not_proposed_again(self):
        connection = self.connection()
        context = self.context(series=self.catalogue(), max_new_pairs=5)
        raised = ANALYSES.scan_series_pairs(connection, context)
        self.assertEqual(len(raised), 2)
        for question in raised:
            ENGINE.mark_question(connection, question["id"], status=ENGINE.QUESTION_ANSWERED)
        self.assertEqual(ANALYSES.scan_series_pairs(connection, context), [])
        self.assertEqual(
            ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN), [],
        )

    def test_a_series_is_never_paired_with_itself(self):
        connection = self.connection()
        both = [{
            "name": "solo", "role": "both", "subject": "s",
            "source": {"kind": "inline", "records": []}, "key": "v", "label": "solo",
        }]
        self.assertEqual(
            ANALYSES.scan_series_pairs(connection, self.context(series=both)), [],
        )


class MeasurementDraftTest(ResearchTestCase):
    """Confirming a hypothesis drafts a study. It never starts one."""

    def hypothesis(self, connection):
        random.seed(3)
        driver = [random.gauss(0, 1) for _ in range(140)]
        response = [
            (driver[index - 3] * 1.2 if index >= 3 else 0.0) + random.gauss(0, 0.5)
            for index in range(140)
        ]
        base = dt.date(2026, 4, 1)
        records = lambda values, key: [
            {"timestamp": (base + dt.timedelta(days=index)).isoformat(), key: value}
            for index, value in enumerate(values)
        ]
        question = ENGINE.open_question(
            connection, "vineyard:field_1",
            "night humidity precedes powdery mildew risk", "lagged_association",
            {
                "driver": {"source": {"kind": "inline", "records": records(driver, "x")},
                           "key": "x", "label": "night humidity"},
                "response": {"source": {"kind": "inline", "records": records(response, "y")},
                             "key": "y", "label": "powdery risk"},
            },
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def test_a_hypothesis_offers_to_be_measured(self):
        finding = self.hypothesis(self.connection())
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(
            [option["id"] for option in finding["options"]][0],
            ENGINE.MEASUREMENT_TASK_OPTION,
        )

    def test_confirming_drafts_a_task_that_cannot_run(self):
        connection = self.connection()
        finding = self.hypothesis(connection)
        drafts = self.root / "drafts"
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.MEASUREMENT_TASK_OPTION, drafts_dir=str(drafts),
        )
        drafted = stored["drafted_task"]
        self.assertTrue(drafted["drafted"])
        path = Path(drafted["path"])
        self.assertEqual(path.parent, drafts)
        content = path.read_text(encoding="utf-8")
        self.assertIn("status: template", content)
        self.assertNotIn("status: pending", content)
        self.assertIn("skill_name: research_agent", content)
        self.assertIn(f"from finding {finding['id']}", content)

    def test_the_draft_is_a_prospective_test_of_the_same_question(self):
        connection = self.connection()
        finding = self.hypothesis(connection)
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.MEASUREMENT_TASK_OPTION,
            drafts_dir=str(self.root / "drafts"),
        )
        content = Path(stored["drafted_task"]["path"]).read_text(encoding="utf-8")
        self.assertIn(f"question_id: {finding['question_id']}", content)
        self.assertIn("interval_sec: 604800", content)
        self.assertIn("max_iterations: 8", content)

    def test_declining_drafts_nothing(self):
        connection = self.connection()
        finding = self.hypothesis(connection)
        drafts = self.root / "drafts"
        stored = ENGINE.record_decision(
            connection, finding["id"], "rejected",
            option_id=ENGINE.MEASUREMENT_TASK_OPTION, drafts_dir=str(drafts),
        )
        self.assertIsNone(stored.get("drafted_task"))
        self.assertFalse(drafts.exists())

    def test_a_draft_may_not_name_an_arbitrary_command(self):
        with self.assertRaises(ValueError):
            ENGINE.measurement_task_yaml(
                {"id": 1, "analysis": "x", "claim": "c"},
                {"skill": "rm -rf /; echo"},
            )

    def test_repeat_bounds_are_clamped(self):
        content = ENGINE.measurement_task_yaml(
            {"id": 2, "analysis": "x", "claim": "c"},
            {"skill": "research_agent", "interval_sec": 1, "max_iterations": 100000},
        )
        self.assertIn(f"interval_sec: {ENGINE.MIN_TASK_INTERVAL_SECONDS}", content)
        self.assertIn(f"max_iterations: {ENGINE.MAX_TASK_ITERATIONS}", content)


class CoverageRegisterTest(ResearchTestCase):
    """The board attends to the shape of what it cannot measure."""

    def blocked(self, connection, measurement, claim, scope):
        return ENGINE.store_finding(connection, {
            "subject": "vineyard:field_1", "analysis": "lagged_association",
            "scope": scope, "claim": claim, "method": "m",
            "verdict": ENGINE.VERDICT_INSUFFICIENT,
            "metrics": {"missing_measurement": [measurement]},
            "headline": {"missing": [measurement]},
        })

    def ask(self, connection):
        question = ENGINE.open_question(
            connection, "board", "questions I cannot measure", "coverage_gaps", {},
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def test_a_board_with_no_gaps_says_nothing(self):
        self.assertEqual(self.ask(self.connection())["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_gaps_are_ranked_by_how_many_questions_they_unlock(self):
        connection = self.connection()
        self.blocked(connection, "insect counts", "humid nights precede insects", "a")
        self.blocked(connection, "insect counts", "rain precedes insects", "b")
        self.blocked(connection, "leaf wetness", "wetness precedes black rot", "c")
        finding = self.ask(connection)
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_MATERIAL)
        self.assertEqual(finding["metrics"]["best_single_addition"], "insect counts")
        self.assertEqual(finding["metrics"]["questions_unlocked_by_it"], 2)
        self.assertEqual(len(finding["metrics"]["missing_measurements"]), 2)

    def test_it_reports_once_rather_than_per_blocked_question(self):
        connection = self.connection()
        for index in range(5):
            self.blocked(connection, "insect counts", f"claim {index}", f"s{index}")
        finding = self.ask(connection)
        self.assertEqual(len(finding["metrics"]["missing_measurements"]), 1)
        self.assertEqual(finding["metrics"]["missing_measurements"][0]["questions_unlocked"], 5)

    def test_a_gap_describes_the_instruments_not_the_field(self):
        connection = self.connection()
        self.blocked(connection, "insect counts", "humid nights precede insects", "a")
        finding = self.ask(connection)
        text = " ".join(finding["limitations"]).lower()
        self.assertIn("not of the field", text)
        self.assertIn("does not make the answer positive", text)


class SkillCandidateTest(ResearchTestCase):
    """A published model may be written down. It is never installed."""

    def finding(self, connection, spec=None):
        return ENGINE.store_finding(connection, {
            "subject": "vineyard:field_1", "analysis": "research_review",
            "scope": "candidate", "claim": "a published model for a new disease",
            "method": "m", "verdict": ENGINE.VERDICT_MATERIAL,
            "headline": {"candidate": True},
            "metrics": {"skill_candidate": spec} if spec else {},
        })

    def spec(self, **extra):
        return {
            "name": "grape_anthracnose_risk",
            "title": "Grapevine anthracnose risk",
            "sources": [
                {"title": "Elsinoe ampelina infection model", "url": "https://example.org/a"},
            ],
            **extra,
        }

    def test_a_model_with_sources_is_drafted_unvalidated(self):
        connection = self.connection()
        finding = self.finding(connection, self.spec())
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.SKILL_CANDIDATE_OPTION, drafts_dir=str(self.root / "drafts"),
        )
        drafted = stored["drafted_task"]
        self.assertTrue(drafted["drafted"])
        content = Path(drafted["path"]).read_text(encoding="utf-8")
        self.assertIn("status: draft", content)
        self.assertIn("requires_validation: true", content)
        self.assertIn("requires_human_promotion: true", content)
        self.assertIn("https://example.org/a", content)
        self.assertIn("not validated, not installed", content)
        # It must not land anywhere the runtime would discover it as a skill.
        self.assertIn("skill_candidates", drafted["path"])

    def test_a_model_without_a_published_source_is_refused(self):
        connection = self.connection()
        finding = self.finding(connection, self.spec(sources=[]))
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.SKILL_CANDIDATE_OPTION, drafts_dir=str(self.root / "drafts"),
        )
        self.assertFalse(stored["drafted_task"]["drafted"])
        self.assertIn("literature", stored["drafted_task"]["reason"])

    def test_the_draft_states_what_it_may_not_be_used_for(self):
        connection = self.connection()
        finding = self.finding(connection, self.spec())
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted",
            option_id=ENGINE.SKILL_CANDIDATE_OPTION, drafts_dir=str(self.root / "drafts"),
        )
        content = Path(stored["drafted_task"]["path"]).read_text(encoding="utf-8")
        self.assertIn("must not be used for advice until it is", content)
        self.assertIn("product selection stays on the two-step confirmation route", content)
        self.assertIn("validate-skill", content)

    def test_an_unsafe_skill_name_is_refused(self):
        with self.assertRaises(ValueError):
            ENGINE.skill_candidate_manifest(
                {"id": 1, "analysis": "a", "claim": "c", "verdict": "v"},
                {"name": "../../etc/passwd"},
                [{"title": "t", "url": "https://example.org"}],
            )

    def test_declining_writes_nothing(self):
        connection = self.connection()
        finding = self.finding(connection, self.spec())
        drafts = self.root / "drafts"
        stored = ENGINE.record_decision(
            connection, finding["id"], "rejected",
            option_id=ENGINE.SKILL_CANDIDATE_OPTION, drafts_dir=str(drafts),
        )
        self.assertIsNone(stored.get("drafted_task"))
        self.assertFalse(drafts.exists())


class ForwardWarningTest(ResearchTestCase):
    """A confirmed relationship becomes a warning that carries its own reason."""

    def relationship(self, connection, high_recently=True):
        random.seed(5)
        today = dt.date.today()
        count = 150
        driver = [random.gauss(70, 6) for _ in range(count)]
        if high_recently:
            driver[-2] = 130.0
        else:
            # Deterministically ordinary in the days a warning would look at.
            for index in range(1, 5):
                driver[-index] = 60.0
        response = [
            (driver[index - 3] - 70) * 2.0 + random.gauss(0, 4) + 30 if index >= 3 else 30.0
            for index in range(count)
        ]
        series = lambda values, key: [
            {"timestamp": (today - dt.timedelta(days=count - 1 - index)).isoformat(), key: value}
            for index, value in enumerate(values)
        ]
        question = ENGINE.open_question(
            connection, "vineyard:field_1",
            "night humidity precedes powdery mildew risk", "lagged_association",
            {
                "driver": {"source": {"kind": "inline", "records": series(driver, "x")},
                           "key": "x", "label": "night humidity"},
                "response": {"source": {"kind": "inline", "records": series(response, "y")},
                             "key": "y", "label": "powdery mildew risk"},
            },
        )
        return ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )

    def forecast_question(self, connection):
        return [
            item for item in ENGINE.list_questions(connection, status=ENGINE.QUESTION_OPEN)
            if item["analysis"] == "relationship_forecast"
        ]

    def test_a_confirmed_relationship_may_be_pointed_forwards(self):
        connection = self.connection()
        finding = self.relationship(connection)
        self.assertIn(
            ENGINE.FORECAST_OPTION, [option["id"] for option in finding["options"]],
        )
        stored = ENGINE.record_decision(
            connection, finding["id"], "accepted", option_id=ENGINE.FORECAST_OPTION,
        )
        self.assertEqual(stored["follow_up_question"]["analysis"], "relationship_forecast")
        self.assertEqual(len(self.forecast_question(connection)), 1)

    def test_the_warning_states_the_day_and_the_reason(self):
        connection = self.connection()
        finding = self.relationship(connection)
        ENGINE.record_decision(
            connection, finding["id"], "accepted", option_id=ENGINE.FORECAST_OPTION,
        )
        forecast = ENGINE.run_question(
            connection, self.forecast_question(connection)[0],
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(forecast["verdict"], ENGINE.VERDICT_MATERIAL)
        metrics = forecast["metrics"]
        self.assertEqual(metrics["lag_days"], 3)
        self.assertIsNotNone(metrics["predicted_day"])
        self.assertGreater(metrics["driver_value"], metrics["high_threshold"])
        # The reason travels with the warning.
        self.assertIsNotNone(metrics["relationship_rho"])
        self.assertEqual(metrics["confirmed_by_finding"], finding["id"])

    def test_a_quiet_driver_produces_no_warning(self):
        connection = self.connection()
        finding = self.relationship(connection, high_recently=False)
        ENGINE.record_decision(
            connection, finding["id"], "accepted", option_id=ENGINE.FORECAST_OPTION,
        )
        forecast = ENGINE.run_question(
            connection, self.forecast_question(connection)[0],
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(forecast["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_the_same_crossing_is_not_warned_about_twice(self):
        connection = self.connection()
        finding = self.relationship(connection)
        ENGINE.record_decision(
            connection, finding["id"], "accepted", option_id=ENGINE.FORECAST_OPTION,
        )
        question = self.forecast_question(connection)[0]
        first = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        again = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(first["id"], again["id"])
        self.assertFalse(again["changed"])

    def test_a_weak_relationship_stays_an_association(self):
        """Understanding is a legitimate place to stop."""
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "vineyard:field_1", "weak lead", "relationship_forecast",
            {
                "driver": {"source": {"kind": "inline", "records": [
                    {"timestamp": (dt.date.today() - dt.timedelta(days=index)).isoformat(),
                     "x": 90.0 if index == 1 else 50.0}
                    for index in range(60)
                ]}, "key": "x", "label": "night humidity"},
                "lag_days": 3,
                "relationship": {"response": "powdery risk", "rho": 0.2, "samples": 140},
            },
        )
        finding = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)
        self.assertIn("not strong enough", finding["metrics"]["reason"])

    def test_a_relationship_seen_on_too_few_days_does_not_forecast(self):
        connection = self.connection()
        question = ENGINE.open_question(
            connection, "vineyard:field_1", "thin lead", "relationship_forecast",
            {
                "driver": {"source": {"kind": "inline", "records": [
                    {"timestamp": (dt.date.today() - dt.timedelta(days=index)).isoformat(),
                     "x": 90.0 if index == 1 else 50.0}
                    for index in range(60)
                ]}, "key": "x", "label": "night humidity"},
                "lag_days": 3,
                "relationship": {"response": "powdery risk", "rho": 0.9, "samples": 20},
            },
        )
        finding = ENGINE.run_question(
            connection, question, ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        self.assertEqual(finding["verdict"], ENGINE.VERDICT_NOT_MATERIAL)

    def test_a_forecast_never_claims_to_have_measured_the_thing(self):
        connection = self.connection()
        finding = self.relationship(connection)
        ENGINE.record_decision(
            connection, finding["id"], "accepted", option_id=ENGINE.FORECAST_OPTION,
        )
        forecast = ENGINE.run_question(
            connection, self.forecast_question(connection)[0],
            ANALYSES.BUILTIN_ANALYSES, self.context(),
        )
        text = " ".join(forecast["limitations"]).lower()
        self.assertIn("not a measurement", text)
        self.assertIn("not causation", text)
        self.assertIn("only a look at the field", forecast["open_question"])


class PolicyTest(ResearchTestCase):
    """The board reallocates its own idle time toward what has paid off here."""

    def store(self, connection, analysis, verdict, count, declined=0):
        for index in range(count):
            record = ENGINE.store_finding(connection, {
                "subject": "bench", "analysis": analysis, "scope": f"{analysis}-{index}",
                "claim": "c", "method": "m", "verdict": verdict,
                "headline": {"n": index},
            })
            if index < declined:
                ENGINE.record_decision(connection, record["id"], "rejected")

    def test_an_analysis_that_never_finds_anything_is_demoted(self):
        connection = self.connection()
        self.store(connection, "data_gap", ENGINE.VERDICT_NOT_MATERIAL, 8)
        policy = ENGINE.refresh_policy(connection)
        self.assertEqual(policy["data_gap"]["delta"], ENGINE.POLICY_MAX_PENALTY)
        question = ENGINE.open_question(
            connection, "bench", "did it stop", "data_gap", {"k": 1}, priority=50,
        )
        self.assertEqual(question["priority"], 50 + ENGINE.POLICY_MAX_PENALTY)

    def test_a_productive_analysis_gains_a_little(self):
        connection = self.connection()
        self.store(connection, "level_shift", ENGINE.VERDICT_MATERIAL, 8)
        policy = ENGINE.refresh_policy(connection)
        self.assertEqual(policy["level_shift"]["delta"], ENGINE.POLICY_MAX_BONUS)

    def test_findings_the_human_keeps_declining_are_demoted_too(self):
        connection = self.connection()
        self.store(connection, "ceiling_saturation", ENGINE.VERDICT_MATERIAL, 8, declined=8)
        policy = ENGINE.refresh_policy(connection)
        self.assertLess(policy["ceiling_saturation"]["delta"], 0)

    def test_a_demoted_analysis_is_never_silenced(self):
        connection = self.connection()
        self.store(connection, "data_gap", ENGINE.VERDICT_NOT_MATERIAL, 20)
        ENGINE.refresh_policy(connection)
        question = ENGINE.open_question(
            connection, "bench", "did it stop", "data_gap", {"k": 2}, priority=10,
        )
        # Still runnable: an analysis that stops running can never redeem itself.
        self.assertGreaterEqual(question["priority"], 1)
        self.assertEqual(question["status"], ENGINE.QUESTION_OPEN)

    def test_too_little_history_changes_nothing(self):
        connection = self.connection()
        self.store(connection, "level_shift", ENGINE.VERDICT_NOT_MATERIAL, 3)
        self.assertEqual(ENGINE.refresh_policy(connection), {})


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
        # A steady board investigates only its own coverage, and finds nothing
        # to report: no series question fires and no gap is registered.
        self.assertEqual(
            [item["analysis"] for item in result["investigated"]], ["coverage_gaps"],
        )
        self.assertEqual(result["investigated"][0]["verdict"], "not_material")
        self.assertEqual(result["reportable"], [])
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
            "fields": [{
                "id": "field_1", "name": "Camp Nord",
                "coordinates": {"latitude": 41.3, "longitude": 1.7},
            }],
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

    def test_the_pack_asks_about_neighbours_and_the_weather_forecast(self):
        """Both arrive as parameters for generic analyses, not as new code."""
        repo = self.build_repo()
        database = sqlite3.connect(repo / "goidanich.db")
        database.execute(
            "CREATE TABLE weather_forecast_daily(field_id TEXT, day TEXT,"
            " horizon_days INT, source TEXT, temp REAL)"
        )
        database.execute(
            "CREATE TABLE peer_signals(timestamp TEXT, peer_id TEXT, signal_type TEXT,"
            " value REAL, metadata TEXT, disease_id TEXT)"
        )
        database.execute(
            "ALTER TABLE black_rot_daily_predictions ADD COLUMN temp REAL"
        )
        end = dt.date(2026, 6, 30)
        for index in range(40):
            day = (end - dt.timedelta(days=39 - index)).isoformat()
            observed = 20.0 + (index % 5) * 0.3
            database.execute(
                "UPDATE black_rot_daily_predictions SET temp=? WHERE field_id=? AND day=?",
                (observed, "field_1", day),
            )
            # A forecast running four degrees warm for the whole window.
            database.execute(
                "INSERT INTO weather_forecast_daily VALUES(?,?,?,?,?)",
                ("field_1", day, 1, "open-meteo", observed + 4.0),
            )
        database.execute(
            "INSERT INTO peer_signals VALUES(?,?,?,?,?,?)",
            (
                (self.now - dt.timedelta(days=3)).isoformat(), "agent_granada_01",
                "contagion", 3.0,
                json.dumps({"latitude": 41.315, "longitude": 1.705, "board_id": "La Granada"}),
                "black_rot",
            ),
        )
        database.commit()
        database.close()
        result = self.run_skill({
            "mode": "cycle", "state_dir": str(self.root / "state"),
            "repo_path": str(repo), "journal_dirs": str(self.journals),
            "evidence_journal": str(self.root / "experiments.jsonl"),
            "pack_dirs": str(ROOT / "skills"), "max_questions": 8,
        })
        by_analysis = {
            item["analysis"]: item for item in result["investigated"] if item.get("analysis")
        }
        self.assertEqual(
            by_analysis["neighbour_reports"]["verdict"], "material_unresolved",
        )
        self.assertEqual(
            by_analysis["source_disagreement"]["verdict"], "material_unresolved",
        )
        self.assertIn("forecast", by_analysis["source_disagreement"]["open_question"])

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
        self.assertEqual(result["pack_errors"], [])
        self.assertEqual(result["packs"], ["vineyard_guard"])
        # The engine still asks its own coverage question; the domain adds none.
        vineyard = [
            item for item in result["investigated"]
            if str(item.get("subject") or "").startswith("vineyard:")
        ]
        self.assertEqual(vineyard, [])


if __name__ == "__main__":
    unittest.main()
