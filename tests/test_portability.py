"""nora must run where the experiment is, not only on one board.

The executor is a static Go binary and the research engine is standard-library
Python, so the same tree belongs on a board, a laptop, and a cloud VM. These
tests pin the contract that makes that true: hardware skills declare
themselves, off-board hosts skip them with a reason, and the deployment files
describe what actually exists.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
DEPLOY = ROOT / "deploy"

HARDWARE_MARKERS = (
    "/dev/video", "/dev/i2c", "/dev/gpiochip", "maix", "cvitek",
    "arecord", "v4l2", "smbus", "i2cdetect", "gpioset",
)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


class SkillHardwareDeclarationTest(unittest.TestCase):
    def test_every_skill_touching_a_device_declares_it(self):
        undeclared = []
        for skill in sorted(SKILLS.iterdir()):
            manifest = skill / "SKILL.md"
            if not skill.is_dir() or not manifest.is_file():
                continue
            if "requires_hardware: true" in frontmatter(manifest):
                continue
            for source in skill.glob("run.*"):
                try:
                    body = source.read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    continue
                if any(marker in body for marker in HARDWARE_MARKERS):
                    undeclared.append(f"{skill.name} ({source.name})")
                    break
        self.assertEqual(
            undeclared, [],
            "these skills reach for a device but do not declare requires_hardware",
        )

    def test_the_research_engine_declares_no_hardware(self):
        manifest = SKILLS / "research_agent" / "SKILL.md"
        self.assertNotIn("requires_hardware", frontmatter(manifest))

    def test_the_hardware_flag_is_readable_by_the_executor(self):
        source = (ROOT / "main.go").read_text(encoding="utf-8")
        self.assertIn('RequiresHardware bool `yaml:"requires_hardware"`', source)
        self.assertIn("func hasBoardHardware() bool", source)
        self.assertIn("NORA_HARDWARE", source)


class ResearchEngineRunsAnywhereTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "monitors").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_skill(self, payload, env=None):
        environment = os.environ.copy()
        environment.update(env or {})
        proc = subprocess.run(
            [str(SKILLS / "research_agent" / "run.sh")],
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, timeout=60, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def test_it_runs_with_no_board_paths_present(self):
        result = self.run_skill({
            "mode": "self_test",
            "state_dir": str(self.root / "state"),
            "journal_dirs": str(self.root / "monitors"),
            "pack_dirs": str(self.root / "no-packs"),
        })
        self.assertTrue(result["installed"])
        self.assertIn("level_shift", result["checks"]["analyses"])

    def test_host_environment_supplies_the_defaults(self):
        result = self.run_skill({"mode": "self_test", "pack_dirs": str(self.root / "none")}, env={
            "NORA_STATE_DIR": str(self.root / "env-state"),
            "NORA_JOURNAL_DIRS": str(self.root / "monitors"),
            "NORA_EVIDENCE_JOURNAL": str(self.root / "experiments.jsonl"),
        })
        self.assertTrue(result["installed"])
        self.assertEqual(result["checks"]["journal_dirs"], [str(self.root / "monitors")])
        self.assertTrue((self.root / "env-state" / "research.db").exists())

    def test_an_explicit_parameter_beats_the_environment(self):
        result = self.run_skill({
            "mode": "self_test",
            "state_dir": str(self.root / "explicit"),
            "journal_dirs": str(self.root / "monitors"),
            "pack_dirs": str(self.root / "none"),
        }, env={"NORA_STATE_DIR": str(self.root / "from-env")})
        self.assertTrue(result["installed"])
        self.assertTrue((self.root / "explicit" / "research.db").exists())
        self.assertFalse((self.root / "from-env").exists())


class DeploymentFilesTest(unittest.TestCase):
    def test_the_deployment_set_is_present(self):
        for name in ("README.md", "nora.service", "Containerfile", "cloud.env.example"):
            self.assertTrue((DEPLOY / name).is_file(), f"deploy/{name} is missing")

    def test_the_systemd_unit_runs_unprivileged(self):
        unit = (DEPLOY / "nora.service").read_text(encoding="utf-8")
        self.assertIn("User=nora", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("User=root", unit)

    def test_the_container_carries_an_interpreter_for_the_skills(self):
        containerfile = (DEPLOY / "Containerfile").read_text(encoding="utf-8")
        # The executor is static, but the skills it runs are Python: a scratch
        # image would build and then fail on the first skill.
        self.assertNotIn("FROM scratch", containerfile)
        self.assertIn("python", containerfile.lower())
        self.assertIn("skills/research_agent", containerfile)

    def test_documented_environment_variables_are_implemented(self):
        example = (DEPLOY / "cloud.env.example").read_text(encoding="utf-8")
        runner = (SKILLS / "research_agent" / "run.py").read_text(encoding="utf-8")
        executor = (ROOT / "main.go").read_text(encoding="utf-8")
        documented = {
            line.split("=", 1)[0].strip()
            for line in example.splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        }
        self.assertTrue(documented)
        for variable in documented:
            self.assertTrue(
                variable in runner or variable in executor,
                f"{variable} is documented in deploy/cloud.env.example but read nowhere",
            )


@unittest.skipUnless(shutil.which("go"), "go toolchain not available")
class ExecutorBuildsForEveryHostTest(unittest.TestCase):
    def test_it_cross_builds_for_board_cloud_and_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            for arch in ("riscv64", "amd64", "arm64"):
                proc = subprocess.run(
                    ["go", "build", "-o", str(Path(temp) / f"nora-{arch}"), "main.go"],
                    cwd=str(ROOT),
                    env={**os.environ, "GOOS": "linux", "GOARCH": arch, "CGO_ENABLED": "0"},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, check=False,
                )
                self.assertEqual(
                    proc.returncode, 0,
                    f"linux/{arch} build failed: {proc.stderr.decode('utf-8', 'replace')}",
                )


if __name__ == "__main__":
    unittest.main()
