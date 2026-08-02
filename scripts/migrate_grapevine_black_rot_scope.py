#!/usr/bin/env python3
"""Correct legacy negative Guignardia evidence without overriding confirmed state."""

import argparse
import datetime as dt
import json
from pathlib import Path
import shutil

import yaml


DEFAULT_NOTE = (
    "A regional expert reported no personal observation or prior knowledge of "
    "grapevine black rot. This is not a systematic regional presence/absence assessment."
)
SECONDARY_ROT_NOTE = (
    "Regional report: secondary bunch rots cause damage, principally "
    "Aspergillus. Penicillium and the reported term 'Clamidospora' were also "
    "mentioned; organism identity has not been independently confirmed."
)

LEGACY_NEGATIVE_HISTORY = {
    "absent",
    "not_present",
    "not_reported",
    "no_known_presence",
    "not_documented",
}


def is_legacy_expert_negative(metadata):
    history = str(metadata.get("black_rot_history") or "").strip().lower()
    source = str(metadata.get("black_rot_evidence_source") or "").strip().lower()
    note = str(metadata.get("black_rot_evidence_note") or "").strip().lower()
    return bool(
        metadata.get("black_rot_inoculum_present") is False
        or (
            history in LEGACY_NEGATIVE_HISTORY
            and ("regional_expert" in source or "no personal observation" in note)
        )
        or "regional_expert_no_known_presence" in source
    )


def update_metadata(metadata, evidence_date):
    metadata = dict(metadata or {})
    history = str(metadata.get("black_rot_history") or "").strip().lower()
    positive = metadata.get("black_rot_inoculum_present") is True or history in {
        "present", "confirmed", "detected",
    }
    legacy_negative = is_legacy_expert_negative(metadata)
    metadata.pop("black_rot_inoculum_present", None)
    if positive:
        metadata["black_rot_history"] = "present"
        return metadata
    if legacy_negative:
        metadata.update({
            "black_rot_history": "unknown",
            "black_rot_evidence_source": (
                f"regional_expert_observation_{evidence_date}"
            ),
            "black_rot_evidence_note": DEFAULT_NOTE,
            "secondary_bunch_rot_status": "reported_concern",
            "secondary_bunch_rot_primary_concern": "Aspergillus spp.",
            "secondary_bunch_rot_reported_taxa": [
                "Aspergillus niger",
                "Penicillium spp.",
                "Clamidospora spp. (reported term; taxon unverified)",
            ],
            "secondary_bunch_rot_evidence_source": (
                f"regional_expert_report_{evidence_date}"
            ),
            "secondary_bunch_rot_evidence_note": SECONDARY_ROT_NOTE,
        })
    return metadata


def migrate(config_path, evidence_date, backup=True):
    config_path = Path(config_path)
    original_text = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(original_text) or {}
    fields = config.get("fields") or []
    changed_fields = []
    for field in fields:
        previous = dict(field.get("metadata") or {})
        updated = update_metadata(previous, evidence_date)
        field["metadata"] = updated
        if updated != previous:
            changed_fields.append(field.get("id") or field.get("name") or "unknown")

    local_agent = config.get("local_agent")
    if isinstance(local_agent, dict):
        local_agent["metadata"] = update_metadata(
            local_agent.get("metadata"), evidence_date
        )

    rendered = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    if rendered == original_text:
        return {
            "status": "success",
            "changed": False,
            "config": str(config_path),
            "backup": None,
            "fields": changed_fields,
            "black_rot_history": "unknown",
            "secondary_bunch_rot_status": "reported_concern",
            "secondary_bunch_rot_primary_concern": "Aspergillus spp.",
            "secondary_bunch_rot_reported_taxa": [
                "Aspergillus niger",
                "Penicillium spp.",
                "Clamidospora spp. (reported term; taxon unverified)",
            ],
        }

    backup_path = None
    if backup:
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
        shutil.copy2(config_path, backup_path)

    temporary = config_path.with_name(f".{config_path.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    yaml.safe_load(temporary.read_text(encoding="utf-8"))
    temporary.replace(config_path)

    return {
        "status": "success",
        "changed": True,
        "config": str(config_path),
        "backup": str(backup_path) if backup_path else None,
        "fields": changed_fields,
        "black_rot_history": "unknown",
        "secondary_bunch_rot_status": "reported_concern",
        "secondary_bunch_rot_primary_concern": "Aspergillus spp.",
        "secondary_bunch_rot_reported_taxa": [
            "Aspergillus niger",
            "Penicillium spp.",
            "Clamidospora spp. (reported term; taxon unverified)",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument(
        "--evidence-date",
        default=dt.date.today().isoformat(),
        help="Date attached to the regional expert evidence source.",
    )
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        migrate(args.config, args.evidence_date, backup=not args.no_backup),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
