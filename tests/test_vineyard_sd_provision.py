import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import provision_vineyard_sd as provision  # noqa: E402
import sigpac_lookup  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_sigpac_lookup_selects_expected_vineyard_recinto():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "provincia": "43 - TARRAGONA",
                    "municipio": "165 - VENDRELL (EL)",
                    "agregado": 0,
                    "zona": 0,
                    "poligono": 14,
                    "parcela": 18,
                    "recinto": 3,
                    "superficie_ha": 0.983,
                    "uso_sigpac": "IM - IMPRODUCTIVOS",
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "provincia": "43 - TARRAGONA",
                    "municipio": "165 - VENDRELL (EL)",
                    "agregado": 0,
                    "zona": 0,
                    "poligono": 14,
                    "parcela": 18,
                    "recinto": 7,
                    "superficie_ha": 0.039,
                    "pendiente": 9.2,
                    "coef_regadio": 0,
                    "uso_sigpac": "VI - VIÑEDO",
                    "altitud": 47,
                },
            },
        ],
    }

    def opener(_request, timeout):
        assert timeout == 30
        return FakeResponse(payload)

    result = sigpac_lookup.query_sigpac(
        41.207,
        1.525,
        expected_use_code="VI",
        opener=opener,
    )

    assert result["status"] == "selected"
    assert result["candidate_count"] == 2
    assert result["selected"]["use_code"] == "VI"
    assert result["selected"]["reference"] == "43:165:0:0:14:18:7"
    assert result["selected"]["slope_percent"] == 9.2


def manifest():
    return {
        "schema": provision.SCHEMA,
        "board": {
            "id": "board_test_01",
            "name": "Test Board",
            "preferred_language": "ca",
            "timezone": "Europe/Madrid",
            "supabase_project_ref": "project-ref",
        },
        "weather": {
            "observed_provider": "meteocat",
            "forecast_provider": "open_meteo",
        },
        "hardware": {
            "leaf_wetness_sensor": {"present": False, "channel": None},
        },
        "fields": [
            {
                "id": "field_test_01",
                "name": "Field One",
                "location": "Penedes",
                "coordinates": {"latitude": 41.2, "longitude": 1.5},
                "variety": "Chardonnay",
                "planting_year": 2014,
                "management": "organic",
                "water_management": "dryland",
                "irrigation": "none",
                "sigpac": {
                    "expected_use_code": "VI",
                    "reference": {
                        "province_code": "43",
                        "municipality_code": "165",
                        "aggregate": 0,
                        "zone": 0,
                        "polygon": 14,
                        "parcel": 18,
                        "recinto": 7,
                    },
                    "properties": {
                        "use_code": "VI",
                        "area_ha": 0.5,
                        "slope_percent": 8.0,
                    },
                },
                "disease_context": {
                    "black_rot_inoculum_status": "unknown",
                    "black_rot_evidence_source": "regional_expert_observation",
                    "secondary_bunch_rot_status": "reported_concern",
                    "secondary_bunch_rot_primary_concern": "Aspergillus spp.",
                },
            }
        ],
    }


def rootfs(tmp_path):
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "root").mkdir(exist_ok=True)
    return tmp_path


def test_provision_writes_valid_yaml_and_inventory(tmp_path):
    result = provision.provision(
        manifest(),
        rootfs(tmp_path),
        require_sigpac=True,
    )

    config_path = Path(result["config_path"])
    inventory_path = Path(result["inventory_path"])
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    assert config["board"]["id"] == "board_test_01"
    assert config["board"]["supabase_board_uuid"] == provision.stable_board_uuid("board_test_01")
    assert config["fields"][0]["metadata"]["supabase_agent_uuid"] == provision.stable_field_uuid("field_test_01")
    assert config["fields"][0]["metadata"]["sigpac_reference"] == "43:165:0:0:14:18:7"
    assert config["fields"][0]["field_context"]["planting_year"] == 2014
    metadata = config["fields"][0]["metadata"]
    assert metadata["black_rot_history"] == "unknown"
    assert "black_rot_inoculum_present" not in metadata
    assert metadata["secondary_bunch_rot_status"] == "reported_concern"
    assert metadata["secondary_bunch_rot_primary_concern"] == "Aspergillus spp."
    assert inventory["fields"][0]["sigpac_status"] == "selected"
    assert inventory["fields"][0]["sigpac"]["selection_basis"] == "manual_reference"
    assert inventory["hardware"]["leaf_wetness_sensor"]["present"] is False


def test_provision_requires_age_context(tmp_path):
    incomplete = manifest()
    incomplete["fields"][0].pop("planting_year")

    try:
        provision.provision(incomplete, rootfs(tmp_path))
    except ValueError as exc:
        assert "planting_year or vine_age_years" in str(exc)
    else:
        raise AssertionError("missing training age context was accepted")


def test_provision_rejects_embedded_credentials(tmp_path):
    unsafe = manifest()
    unsafe["board"]["telegram_token"] = "do-not-store-here"

    try:
        provision.provision(unsafe, rootfs(tmp_path))
    except ValueError as exc:
        assert "separate .env files" in str(exc)
    else:
        raise AssertionError("credential was accepted in the board manifest")


def test_existing_config_requires_force_and_is_backed_up(tmp_path):
    mounted_rootfs = rootfs(tmp_path)
    first = provision.provision(manifest(), mounted_rootfs)
    config_path = Path(first["config_path"])
    original = config_path.read_text(encoding="utf-8")

    try:
        provision.provision(manifest(), mounted_rootfs)
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing configuration was overwritten without --force")

    second_manifest = manifest()
    second_manifest["board"]["name"] = "Updated Board"
    second = provision.provision(second_manifest, mounted_rootfs, force=True)

    assert Path(second["backup_path"]).read_text(encoding="utf-8") == original
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["board"]["name"] == "Updated Board"


def test_provision_rejects_boot_only_volume(tmp_path):
    (tmp_path / "extlinux").mkdir()

    try:
        provision.provision(manifest(), tmp_path)
    except ValueError as exc:
        assert "do not point --rootfs at the boot partition" in str(exc)
    else:
        raise AssertionError("boot-only volume was accepted as a Linux rootfs")
