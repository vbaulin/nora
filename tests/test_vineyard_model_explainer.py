import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "vineyard_model_explainer" / "run.py"


def run_skill(payload):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_ambiguous_catalan_rot_requires_confirmation():
    result = run_skill({
        "disease": "rot_clarification",
        "raw_text": "Quan parles de podridura negra, a què et refereixes?",
    })

    assert result["status"] == "needs_clarification"
    assert result["model_call_allowed"] is False
    assert "Guignardia bidwellii" in result["send_text"]
    assert "Podridures secundàries" in result["send_text"]
    assert "Et refereixes" in result["confirmation_question"]


def test_ambiguous_spanish_rot_uses_spanish():
    result = run_skill({
        "disease": "rot_clarification",
        "raw_text": "¿Podredumbre negra o podredumbres secundarias?",
    })

    assert "¿Te refieres" in result["confirmation_question"]
    assert "Podredumbres secundarias" in result["send_text"]
