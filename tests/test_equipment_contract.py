"""Contract tests for the equipment/channel entity families (IDENTIFIER_POLICY 6.1).

Design rules under test:
- equipment-spec (the model) mints under the shared spec/ namespace;
- equipment (the physical unit) mints under equipment/;
- channel is instance-only with flat IRIs: parent link equipment_id lives in
  the record body, and the uid is DETERMINISTIC from (equipment uid, index) so
  registration is idempotent;
- equipment category is data (equipment_class), never a namespace segment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from battinfo.api import (
    create_channel,
    create_equipment,
    create_equipment_spec,
    save_record,
)
from battinfo.validate.record import validate_record_report

ROOT = Path(__file__).resolve().parents[1]

SPEC_IRI = re.compile(r"^https://w3id\.org/battinfo/spec/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")
EQUIPMENT_IRI = re.compile(r"^https://w3id\.org/battinfo/equipment/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")
CHANNEL_IRI = re.compile(r"^https://w3id\.org/battinfo/channel/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")


def test_equipment_spec_mints_under_shared_spec_namespace() -> None:
    record = create_equipment_spec(
        name="Neware BTS-4000 series",
        equipment_class="cycler",
        channel_count=8,
    )
    assert SPEC_IRI.fullmatch(record["equipment_spec"]["id"])
    assert record["equipment_spec"]["equipment_class"] == "cycler"


def test_equipment_spec_rejects_non_spec_namespace_id() -> None:
    with pytest.raises(ValueError, match="spec"):
        create_equipment_spec(
            name="X",
            id="https://w3id.org/battinfo/equipment-spec/0000-0000-0000-0000",
        )


def test_equipment_mints_under_equipment_and_references_validate(tmp_path: Path) -> None:
    spec = create_equipment_spec(name="Neware BTS-4000 series", equipment_class="cycler")
    save_record(spec, source_root=tmp_path, build_jsonld=False, build_html=False)

    equipment = create_equipment(
        equipment_spec_id=spec["equipment_spec"]["id"],
        serial_number="NW-4000-0117",
        name="Cycler 1",
        location="Lab B",
        status="active",
    )
    assert EQUIPMENT_IRI.fullmatch(equipment["equipment"]["id"])

    # The instance->spec link resolves through the generic registry-family
    # reference machinery (spec_ref_field on the EntityKind row).
    report = validate_record_report(equipment, source_root=tmp_path, policy="strict")
    assert report.ok, [issue.message for issue in report.errors]

    # A dangling spec reference must fail reference validation.
    dangling = create_equipment(equipment_spec_id="https://w3id.org/battinfo/spec/zzzz-zzzz-zzzz-zzzz")
    report = validate_record_report(dangling, source_root=tmp_path, policy="strict")
    assert not report.ok
    assert any(issue.code == "reference.missing" for issue in report.errors)


def test_channel_uid_is_deterministic_from_equipment_and_index() -> None:
    equipment_id = "https://w3id.org/battinfo/equipment/cy01-7r4d-2j9m-5w8e"
    first = create_channel(equipment_id=equipment_id, index=2)
    again = create_channel(equipment_id=equipment_id, index=2, label="CH2")
    other_index = create_channel(equipment_id=equipment_id, index=3)
    other_unit = create_channel(
        equipment_id="https://w3id.org/battinfo/equipment/ab12-cd34-ef56-gh78", index=2
    )

    assert CHANNEL_IRI.fullmatch(first["channel"]["id"])
    assert first["channel"]["id"] == again["channel"]["id"], "same (equipment, index) must mint the same IRI"
    assert first["channel"]["id"] != other_index["channel"]["id"]
    assert first["channel"]["id"] != other_unit["channel"]["id"]
    # Flat IRI: the parent lives in the record body, never in the address.
    assert first["channel"]["equipment_id"] == equipment_id
    assert first["channel"]["id"].split("/")[-2] == "channel"


def test_channel_requires_equipment_id_and_valid_index() -> None:
    with pytest.raises(TypeError):
        create_channel(index=1)
    with pytest.raises(ValueError, match="equipment"):
        create_channel(equipment_id="https://w3id.org/battinfo/spec/0000-0000-0000-0000", index=1)
    with pytest.raises(ValueError, match="index"):
        create_channel(
            equipment_id="https://w3id.org/battinfo/equipment/cy01-7r4d-2j9m-5w8e", index=0
        )


@pytest.mark.parametrize("subdir", ["equipment-spec", "equipment", "channel"])
def test_example_records_pass_strict_validation(subdir: str) -> None:
    examples_dir = ROOT / "examples" / subdir
    paths = sorted(examples_dir.glob("*.json"))
    assert paths, f"no examples in {examples_dir}"
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        report = validate_record_report(doc, policy="strict")
        assert report.ok, f"{path.name}: {[issue.message for issue in report.errors]}"


def test_example_channel_uid_matches_the_deterministic_mint() -> None:
    """The committed channel example must be re-derivable from its own body."""
    from battinfo.entities import stable_uid

    examples_dir = ROOT / "examples" / "channel"
    for path in sorted(examples_dir.glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))["channel"]
        equipment_uid = body["equipment_id"].rsplit("/", 1)[-1]
        expected = stable_uid(f"channel:{equipment_uid}:{body['index']}")
        assert body["id"].rsplit("/", 1)[-1] == expected
