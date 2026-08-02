#!/usr/bin/env python3
"""Provision Vineyard Guard identity and field metadata on an existing rootfs.

The script does not partition, format, or modify the boot partition. It writes
only Vineyard Guard configuration beneath the mounted Linux root filesystem.
"""

import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import uuid

from sigpac_lookup import DEFAULT_ENDPOINT, query_sigpac


SCHEMA = "vineyard_board_manifest_v1"
INVENTORY_SCHEMA = "vineyard_board_inventory_v1"
DEFAULT_CONFIG_DIR = Path("root/.picoclaw/workspace/goidanich")
DEFAULT_INVENTORY_PATH = Path("root/.picoclaw/board_inventory.json")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SAFE_YAML_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "anon_key",
    "bot_token",
    "password",
    "publishable_key",
    "secret",
    "service_role_key",
    "supabase_anon_key",
    "supabase_publishable_key",
    "supabase_service_role_key",
    "telegram_token",
    "token",
}


def stable_board_uuid(board_id):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"goidanich-board:{board_id}"))


def stable_field_uuid(field_id):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"goidanich:{field_id}"))


def _require_mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _validate_id(value, label):
    text = str(value or "").strip()
    if not text or not SAFE_ID.fullmatch(text):
        raise ValueError(f"{label} must contain only letters, numbers, '.', '_' or '-'")
    return text


def _coordinates(field):
    coordinates = _require_mapping(field.get("coordinates"), f"{field.get('id', 'field')}.coordinates")
    try:
        latitude = float(coordinates["latitude"])
        longitude = float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{field.get('id', 'field')} requires numeric latitude/longitude") from exc
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(f"{field.get('id', 'field')} has invalid latitude/longitude")
    return latitude, longitude


def _reject_embedded_secrets(value, path="manifest"):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_SECRET_KEYS:
                raise ValueError(
                    f"{path}.{key} is a secret field; keep credentials in separate .env files"
                )
            _reject_embedded_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_embedded_secrets(item, f"{path}[{index}]")


def _normalize_age_context(field, field_id):
    planting_year = field.get("planting_year")
    vine_age_years = field.get("vine_age_years")
    current_year = dt.date.today().year
    if planting_year not in (None, ""):
        try:
            planting_year = int(planting_year)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_id}.planting_year must be an integer") from exc
        if not 1800 <= planting_year <= current_year:
            raise ValueError(
                f"{field_id}.planting_year must be between 1800 and {current_year}"
            )
        field["planting_year"] = planting_year
    if vine_age_years not in (None, ""):
        try:
            vine_age_years = float(vine_age_years)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_id}.vine_age_years must be numeric") from exc
        if vine_age_years <= 0:
            raise ValueError(f"{field_id}.vine_age_years must be greater than zero")
        field["vine_age_years"] = vine_age_years
    if planting_year in (None, "") and vine_age_years in (None, ""):
        raise ValueError(
            f"{field_id} requires planting_year or vine_age_years for model training context"
        )
    if planting_year not in (None, "") and vine_age_years not in (None, ""):
        expected_age = current_year - planting_year
        if abs(float(vine_age_years) - expected_age) > 2:
            raise ValueError(
                f"{field_id} has inconsistent planting_year and vine_age_years"
            )


def _field_context(field):
    context = {
        "crop": field.get("crop") or "grapevine",
        "variety": field.get("variety"),
        "management": field.get("management"),
        "water_management": field.get("water_management"),
        "irrigation": field.get("irrigation"),
        "planting_year": field.get("planting_year"),
        "vine_age_years": field.get("vine_age_years"),
        "training_system": field.get("training_system"),
        "row_orientation_degrees": field.get("row_orientation_degrees"),
    }
    return {key: value for key, value in context.items() if value not in (None, "")}


def _manual_sigpac(spec, latitude, longitude):
    reference = dict(spec.get("reference") or {})
    required = (
        "province_code",
        "municipality_code",
        "aggregate",
        "zone",
        "polygon",
        "parcel",
        "recinto",
    )
    missing = [key for key in required if reference.get(key) in (None, "")]
    if missing:
        raise ValueError(f"manual SIGPAC reference is missing: {', '.join(missing)}")
    selected = {
        **reference,
        **dict(spec.get("properties") or {}),
    }
    selected["reference"] = ":".join(str(selected[key]) for key in required)
    selected.setdefault("use_code", spec.get("expected_use_code"))
    query = {
        "provincia": selected["province_code"],
        "municipio": selected["municipality_code"],
        "agregado": selected["aggregate"],
        "zona": selected["zone"],
        "poligono": selected["polygon"],
        "parcela": selected["parcel"],
        "recinto": selected["recinto"],
    }
    selected["viewer_url"] = (
        "https://sigpac.mapa.gob.es/fega/visor/?"
        + "&".join(f"{key}={value}" for key, value in query.items())
    )
    expected_use_code = str(spec.get("expected_use_code") or "").strip().upper()
    actual_use_code = str(selected.get("use_code") or "").strip().upper()
    status = "selected"
    active_selection = selected
    if expected_use_code and actual_use_code and expected_use_code != actual_use_code:
        status = "use_code_mismatch"
        active_selection = None
    return {
        "status": status,
        "selected": active_selection,
        "candidates": [selected],
        "candidate_count": 1,
        "selection_basis": "manual_reference" if active_selection else None,
        "review_required": True,
        "expected_use_code": expected_use_code or None,
        "query_coordinates": {"latitude": latitude, "longitude": longitude},
        "service": {
            "provider": "MAPA/FEGA",
            "standard": "manual SIGPAC reference",
            "endpoint": DEFAULT_ENDPOINT,
            "layer": "AU.Sigpac:recinto",
            "authoritative_status": "orientative_non_binding",
        },
    }


def resolve_sigpac(field, latitude, longitude, fetch_sigpac=False, endpoint=DEFAULT_ENDPOINT):
    spec = dict(field.get("sigpac") or {})
    if spec.get("reference"):
        return _manual_sigpac(spec, latitude, longitude)
    expected_use_code = spec.get("expected_use_code")
    if fetch_sigpac:
        return query_sigpac(
            latitude,
            longitude,
            expected_use_code=expected_use_code,
            endpoint=endpoint,
        )
    return {
        "status": "pending_lookup" if spec else "not_configured",
        "selected": None,
        "candidates": [],
        "candidate_count": 0,
        "selection_basis": None,
        "review_required": bool(spec),
        "expected_use_code": expected_use_code,
        "query_coordinates": {"latitude": latitude, "longitude": longitude},
        "service": {
            "provider": "MAPA/FEGA",
            "standard": "OGC WMS 1.3.0 GetFeatureInfo",
            "endpoint": endpoint,
            "layer": "AU.Sigpac:recinto",
            "authoritative_status": "orientative_non_binding",
        },
    }


def _apply_disease_context(metadata, field):
    context = dict(field.get("disease_context") or {})
    status = str(context.pop("black_rot_inoculum_status", "")).strip().lower()
    if status:
        if status not in {"present", "not_reported", "unknown"}:
            raise ValueError(
                f"{field['id']}.disease_context.black_rot_inoculum_status "
                "must be present, not_reported, or unknown"
            )
        metadata["black_rot_history"] = status
        if status == "present":
            metadata["black_rot_inoculum_present"] = True
        elif status == "not_reported":
            metadata["black_rot_inoculum_present"] = False
        else:
            metadata.pop("black_rot_inoculum_present", None)
    metadata.update(context)


def normalize_field(field, board, fetch_sigpac=False, endpoint=DEFAULT_ENDPOINT):
    field = copy.deepcopy(_require_mapping(field, "field"))
    field_id = _validate_id(field.get("id"), "field.id")
    name = str(field.get("name") or field_id).strip()
    location = str(field.get("location") or name).strip()
    variety = str(field.get("variety") or "").strip()
    if not variety:
        raise ValueError(f"{field_id}.variety is required for model training context")
    _normalize_age_context(field, field_id)
    latitude, longitude = _coordinates(field)
    context = _field_context(field)
    sigpac = resolve_sigpac(
        field,
        latitude,
        longitude,
        fetch_sigpac=fetch_sigpac,
        endpoint=endpoint,
    )
    metadata = copy.deepcopy(field.get("metadata") or {})
    metadata.update({
        "board_id": board["id"],
        "field_id": field_id,
        "supabase_agent_uuid": stable_field_uuid(field_id),
        "location": location,
        "variety": variety,
        "lat": latitude,
        "lon": longitude,
        "crop": context["crop"],
        "field_context": context,
        "sigpac": sigpac,
    })
    for key, value in context.items():
        metadata[key] = value
    for source_key in ("station_code", "municipality", "municipality_code", "meteocat_municipality_code"):
        if field.get(source_key) not in (None, ""):
            metadata[source_key] = field[source_key]
    metadata.update(copy.deepcopy(field.get("phenology") or {}))
    _apply_disease_context(metadata, {**field, "id": field_id})

    selected = sigpac.get("selected") or {}
    for target_key, source_key in (
        ("sigpac_reference", "reference"),
        ("sigpac_use_code", "use_code"),
        ("sigpac_area_ha", "area_ha"),
        ("sigpac_slope_percent", "slope_percent"),
        ("sigpac_irrigation_coefficient", "irrigation_coefficient"),
        ("sigpac_altitude_m", "altitude_m"),
    ):
        if selected.get(source_key) not in (None, ""):
            metadata[target_key] = selected[source_key]

    output = {
        "id": field_id,
        "name": name,
        "location": location,
        "coordinates": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "crop": context["crop"],
        "variety": variety,
        "field_context": context,
        "metadata": metadata,
    }
    for key in (
        "management",
        "water_management",
        "irrigation",
        "planting_year",
        "vine_age_years",
        "training_system",
        "row_orientation_degrees",
        "station_code",
        "municipality",
        "municipality_code",
        "meteocat_municipality_code",
    ):
        if field.get(key) not in (None, ""):
            output[key] = field[key]
    return output


def build_agent_config(manifest, fetch_sigpac=False, endpoint=DEFAULT_ENDPOINT):
    manifest = _require_mapping(manifest, "manifest")
    _reject_embedded_secrets(manifest)
    schema = manifest.get("schema") or SCHEMA
    if schema != SCHEMA:
        raise ValueError(f"unsupported manifest schema: {schema}")
    source_board = _require_mapping(manifest.get("board"), "board")
    board_id = _validate_id(source_board.get("id"), "board.id")
    board = copy.deepcopy(source_board)
    board["id"] = board_id
    board["name"] = str(board.get("name") or board_id)
    board.setdefault("preferred_language", "ca")
    board.setdefault("timezone", "Europe/Madrid")
    board.setdefault("supabase_board_uuid", stable_board_uuid(board_id))
    board_metadata = copy.deepcopy(board.get("metadata") or {})
    for key in ("timezone", "supabase_project_ref"):
        if board.get(key) not in (None, ""):
            board_metadata[key] = board[key]
    for key in ("weather", "hardware"):
        if manifest.get(key):
            board_metadata[key] = copy.deepcopy(manifest[key])
    board["metadata"] = board_metadata

    raw_fields = manifest.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError("manifest.fields must contain at least one field")
    normalized_fields = [
        normalize_field(
            field,
            board,
            fetch_sigpac=fetch_sigpac,
            endpoint=endpoint,
        )
        for field in raw_fields
    ]
    field_ids = [field["id"] for field in normalized_fields]
    if len(field_ids) != len(set(field_ids)):
        raise ValueError("manifest.fields contains duplicate field ids")

    notifications = copy.deepcopy(manifest.get("notifications") or {})
    notifications.setdefault("language", board["preferred_language"])
    config = {
        "board": board,
        "notifications": notifications,
        "weather": copy.deepcopy(manifest.get("weather") or {}),
        "hardware": copy.deepcopy(manifest.get("hardware") or {}),
        "fields": normalized_fields,
        "local_agent": copy.deepcopy(normalized_fields[0]),
        "neighbours_file": manifest.get("neighbours_file") or "neighbours.yaml",
    }
    if manifest.get("site"):
        config["site"] = copy.deepcopy(manifest["site"])
    return config


def _yaml_scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_key(value):
    text = str(value)
    return text if SAFE_YAML_KEY.fullmatch(text) else json.dumps(text, ensure_ascii=False)


def yaml_dump(value, indent=0):
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return f"{prefix}{{}}\n"
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{prefix}{_yaml_key(key)}:\n")
                lines.append(yaml_dump(item, indent + 2))
            else:
                rendered = _yaml_scalar(item) if not isinstance(item, (dict, list)) else "{}" if isinstance(item, dict) else "[]"
                lines.append(f"{prefix}{_yaml_key(key)}: {rendered}\n")
        return "".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]\n"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-\n")
                lines.append(yaml_dump(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}\n")
        return "".join(lines)
    return f"{prefix}{_yaml_scalar(value)}\n"


def build_inventory(config):
    fields = []
    for field in config["fields"]:
        sigpac = field["metadata"].get("sigpac") or {}
        fields.append({
            "field_id": field["id"],
            "agent_uuid": field["metadata"]["supabase_agent_uuid"],
            "name": field["name"],
            "location": field["location"],
            "coordinates": field["coordinates"],
            "variety": field["variety"],
            "planting_year": field.get("planting_year"),
            "vine_age_years": field.get("vine_age_years"),
            "management": field.get("management"),
            "water_management": field.get("water_management"),
            "station_code": field.get("station_code"),
            "sigpac_status": sigpac.get("status"),
            "sigpac": sigpac,
        })
    return {
        "schema": INVENTORY_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "board": {
            "id": config["board"]["id"],
            "uuid": config["board"]["supabase_board_uuid"],
            "name": config["board"]["name"],
            "preferred_language": config["board"]["preferred_language"],
            "timezone": config["board"]["timezone"],
            "supabase_project_ref": config["board"].get("supabase_project_ref"),
        },
        "weather": config.get("weather") or {},
        "hardware": config.get("hardware") or {},
        "fields": fields,
    }


def _atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _backup_existing(path):
    if not path.exists():
        return None
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    backup.write_bytes(path.read_bytes())
    return backup


def provision(
    manifest,
    rootfs,
    fetch_sigpac=False,
    require_sigpac=False,
    endpoint=DEFAULT_ENDPOINT,
    force=False,
    dry_run=False,
):
    rootfs = Path(rootfs).expanduser().resolve()
    if not rootfs.is_dir():
        raise ValueError(f"rootfs does not exist or is not a directory: {rootfs}")
    missing_rootfs_markers = [
        str(path.relative_to(rootfs))
        for path in (rootfs / "etc", rootfs / "root")
        if not path.is_dir()
    ]
    if missing_rootfs_markers:
        raise ValueError(
            f"{rootfs} does not look like a Linux rootfs "
            f"(missing directories: {', '.join(missing_rootfs_markers)}); "
            "do not point --rootfs at the boot partition"
        )
    config = build_agent_config(
        manifest,
        fetch_sigpac=fetch_sigpac,
        endpoint=endpoint,
    )
    unresolved = [
        field["id"]
        for field in config["fields"]
        if (field["metadata"].get("sigpac") or {}).get("status") != "selected"
    ]
    if require_sigpac and unresolved:
        raise ValueError(f"SIGPAC recinto is unresolved for: {', '.join(unresolved)}")

    yaml_text = (
        "# Generated by scripts/provision_vineyard_sd.py.\n"
        "# SIGPAC data are orientative and must be reviewed against the official record.\n"
        + yaml_dump(config)
    )
    inventory = build_inventory(config)
    config_path = rootfs / DEFAULT_CONFIG_DIR / "agent_config.yaml"
    manifest_path = rootfs / DEFAULT_CONFIG_DIR / "board_manifest.json"
    inventory_path = rootfs / DEFAULT_INVENTORY_PATH
    if dry_run:
        return {
            "status": "dry_run",
            "config_path": str(config_path),
            "inventory_path": str(inventory_path),
            "unresolved_sigpac_fields": unresolved,
            "agent_config_yaml": yaml_text,
            "inventory": inventory,
        }
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to back it up and replace it"
        )
    backup = _backup_existing(config_path) if force else None
    _atomic_write(config_path, yaml_text)
    _atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    _atomic_write(
        inventory_path,
        json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return {
        "status": "success",
        "config_path": str(config_path),
        "manifest_path": str(manifest_path),
        "inventory_path": str(inventory_path),
        "backup_path": str(backup) if backup else None,
        "board_id": config["board"]["id"],
        "board_uuid": config["board"]["supabase_board_uuid"],
        "field_ids": [field["id"] for field in config["fields"]],
        "unresolved_sigpac_fields": unresolved,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Board manifest JSON")
    parser.add_argument(
        "--rootfs",
        required=True,
        help="Mounted Linux rootfs (for a live board use /)",
    )
    parser.add_argument(
        "--fetch-sigpac",
        action="store_true",
        help="Resolve each field against the official MAPA/FEGA WMS",
    )
    parser.add_argument(
        "--require-sigpac",
        action="store_true",
        help="Abort if any field lacks one unambiguous SIGPAC recinto",
    )
    parser.add_argument("--sigpac-endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Back up and replace an existing agent_config.yaml",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with open(args.manifest, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    result = provision(
        manifest,
        args.rootfs,
        fetch_sigpac=args.fetch_sigpac,
        require_sigpac=args.require_sigpac,
        endpoint=args.sigpac_endpoint,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
