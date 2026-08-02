import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "farmer_feedback_capture"
    / "run.py"
)
SPEC = importlib.util.spec_from_file_location("farmer_feedback_capture", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_config(tmp_path, field_count=1):
    repo = tmp_path / "goidanich"
    repo.mkdir()
    fields = [
        {
            "id": f"field_{number}",
            "name": f"Camp {number}",
            "location": "Penedès",
        }
        for number in range(1, field_count + 1)
    ]
    (repo / "agent_config.yaml").write_text(
        json.dumps({"fields": fields}), encoding="utf-8"
    )
    return repo


def test_catalan_black_rot_false_alarm_uses_single_field_context(tmp_path):
    repo = write_config(tmp_path)
    with mock.patch.dict(os.environ, {"SKILL_REPO_PATH": str(repo)}, clear=False):
        draft, missing, question = MODULE.parse_raw_feedback(
            "Black rot: fals avís"
        )
    assert missing == []
    assert draft["field"] == "field_1"
    assert draft["disease"] == "black_rot"
    assert draft["feedback_type"] == "false_alarm"
    assert question.startswith("Confirmeu")


def test_black_rot_compatible_symptoms_use_disease_specific_feedback(tmp_path):
    repo = write_config(tmp_path)
    with mock.patch.dict(os.environ, {"SKILL_REPO_PATH": str(repo)}, clear=False):
        draft, missing, _ = MODULE.parse_raw_feedback(
            "Black rot: símptomes compatibles"
        )
    assert missing == []
    assert draft["disease"] == "black_rot"
    assert draft["feedback_type"] == "detected_black_rot"


def test_sloppy_multifield_reply_does_not_default_to_downy(tmp_path):
    repo = write_config(tmp_path, field_count=2)
    with mock.patch.dict(os.environ, {"SKILL_REPO_PATH": str(repo)}, clear=False):
        draft, missing, question = MODULE.parse_raw_feedback("cap símptoma")
    assert draft["field"] == ""
    assert draft["disease"] == ""
    assert draft["feedback_type"] == "clean_inspection"
    assert set(missing) == {"field", "disease"}
    assert question.startswith("Confirmeu")


def test_proactive_context_supplies_exact_field_and_disease(tmp_path):
    repo = write_config(tmp_path, field_count=2)
    with mock.patch.dict(os.environ, {
        "SKILL_REPO_PATH": str(repo),
        "SKILL_FIELD": "field_2",
        "SKILL_DISEASE": "black_rot",
    }, clear=False):
        draft, missing, question = MODULE.parse_raw_feedback("cap símptoma")
    assert missing == []
    assert draft["field"] == "field_2"
    assert draft["disease"] == "black_rot"
    assert draft["feedback_type"] == "clean_inspection"
    assert question.startswith("Confirmeu")
