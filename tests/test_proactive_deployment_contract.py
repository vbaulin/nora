import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProactiveDeploymentContractTest(unittest.TestCase):
    def test_board_sync_enforces_skill_self_test_and_observe_gates(self):
        script = (ROOT / "scripts" / "sync_vineyard_board.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "proactive-field-agent" /tmp/skills.out', script)
        self.assertIn('"mode":"self_test"', script)
        self.assertIn('payload.get("installed") is not True', script)
        self.assertIn('"mode":"observe"', script)
        self.assertIn('proactive-field-agent evidence-only observe check failed', script)
        self.assertIn('proactive-field-agent:proactive_field_agent', script)

    def test_board_sync_installs_the_domain_neutral_research_engine(self):
        script = (ROOT / "scripts" / "sync_vineyard_board.sh").read_text(encoding="utf-8")
        self.assertIn("research_agent", script)
        self.assertIn("research-agent:research_agent", script)
        self.assertIn('"research_agent": "research-agent"', script)

    def test_autonomous_research_cycle_task_is_generic_and_budgeted(self):
        task = (ROOT / "tasks" / "029_autonomous_research_cycle.yaml").read_text(encoding="utf-8")
        self.assertIn("skill_name: research_agent", task)
        self.assertIn("mode: cycle", task)
        self.assertIn("max_seconds", task)
        self.assertIn("interval_sec", task)
        # The generic cycle must not depend on any single domain.
        for domain_token in ("goidanich", "vineyard", "field_id", "disease"):
            self.assertNotIn(domain_token, task)

    def test_the_vineyard_pack_declares_parameters_not_analyses(self):
        pack = (ROOT / "skills" / "proactive_field_agent" / "pack.py").read_text(encoding="utf-8")
        self.assertIn('"analysis": "threshold_materiality"', pack)
        self.assertIn('"analysis": "ceiling_saturation"', pack)
        # A domain pack that ships its own analysis has broken the layering.
        self.assertNotIn('"analyses"', pack)

    def test_board_sync_installs_season_climate_skill_and_discovery_link(self):
        script = (ROOT / "scripts" / "sync_vineyard_board.sh").read_text(encoding="utf-8")
        self.assertIn("vineyard_season_climate", script)
        self.assertIn("vineyard-season-climate:vineyard_season_climate", script)

    def test_busybox_tick_runs_research_after_daily_alert_and_sends_outbox(self):
        script = (ROOT / "scripts" / "vineyard_guard_tick.sh").read_text(encoding="utf-8")
        alert = script.index("run_once alert")
        proactive = script.index('run_once proactive "$SCRIPT" proactive --research')
        sender = script.index('"$SENDER" --once')
        self.assertLess(alert, proactive)
        self.assertIn("done_stamp alert", script[alert:proactive])
        self.assertGreater(sender, 0)

    def test_board_shell_scripts_parse(self):
        proc = subprocess.run(
            [
                "sh",
                "-n",
                str(ROOT / "scripts" / "sync_vineyard_board.sh"),
                str(ROOT / "scripts" / "vineyard_guard_tick.sh"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
