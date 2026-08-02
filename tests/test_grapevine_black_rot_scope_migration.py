from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import migrate_grapevine_black_rot_scope as migration  # noqa: E402


def test_migration_separates_guignardia_from_secondary_bunch_rot(tmp_path):
    config_path = tmp_path / "agent_config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "fields": [{
                "id": "field_1",
                "metadata": {
                    "black_rot_inoculum_present": False,
                    "black_rot_history": "not_reported",
                    "black_rot_evidence_source": "regional_expert_no_known_presence_2026-07-29",
                    "unrelated": "preserved",
                },
            }],
            "local_agent": {
                "id": "field_1",
                "metadata": {
                    "black_rot_inoculum_present": False,
                    "black_rot_history": "not_reported",
                    "black_rot_evidence_source": "regional_expert_no_known_presence_2026-07-29",
                },
            },
        }, sort_keys=False),
        encoding="utf-8",
    )

    result = migration.migrate(config_path, "2026-07-29")
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    metadata = updated["fields"][0]["metadata"]

    assert result["status"] == "success"
    assert result["changed"] is True
    assert Path(result["backup"]).exists()
    assert "black_rot_inoculum_present" not in metadata
    assert metadata["black_rot_history"] == "unknown"
    assert "not a systematic regional presence/absence assessment" in metadata["black_rot_evidence_note"]
    assert metadata["secondary_bunch_rot_primary_concern"] == "Aspergillus spp."
    assert metadata["secondary_bunch_rot_reported_taxa"][0] == "Aspergillus niger"
    assert "taxon unverified" in metadata["secondary_bunch_rot_reported_taxa"][2]
    assert metadata["unrelated"] == "preserved"
    assert (
        updated["local_agent"]["metadata"]["secondary_bunch_rot_status"]
        == "reported_concern"
    )

    second = migration.migrate(config_path, "2026-07-29")
    assert second["changed"] is False
    assert second["backup"] is None


def test_migration_never_overwrites_confirmed_presence(tmp_path):
    config_path = tmp_path / "agent_config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "fields": [{
                "id": "field_present",
                "metadata": {
                    "black_rot_inoculum_present": True,
                    "black_rot_history": "present",
                    "black_rot_evidence_source": "farmer_confirmed_feedback",
                    "black_rot_evidence_note": "Compatible symptoms confirmed in this field.",
                },
            }],
        }, sort_keys=False),
        encoding="utf-8",
    )

    migration.migrate(config_path, "2026-07-29")
    metadata = yaml.safe_load(config_path.read_text(encoding="utf-8"))["fields"][0]["metadata"]

    assert "black_rot_inoculum_present" not in metadata
    assert metadata["black_rot_history"] == "present"
    assert metadata["black_rot_evidence_source"] == "farmer_confirmed_feedback"
    assert metadata["black_rot_evidence_note"] == "Compatible symptoms confirmed in this field."
    assert "secondary_bunch_rot_status" not in metadata


def test_migration_leaves_unrelated_unknown_state_untouched(tmp_path):
    config_path = tmp_path / "agent_config.yaml"
    original = {
        "fields": [{
            "id": "field_unknown",
            "metadata": {
                "black_rot_history": "unknown",
                "black_rot_evidence_source": "field_not_yet_scouted",
            },
        }],
    }
    config_path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    result = migration.migrate(config_path, "2026-07-29")
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert result["changed"] is False
    assert updated == original
