"""ws.load() does not drop draft keys it does not read (evaluation finding C-13).

The supplied MN2400 cell-spec draft carried its five datasheet values under
`specs`, the key drafts used until June; ws.load() kept none of them, and the
test-spec draft lost its structured `termination_criteria` cutoff, all without a
warning. `specs` is now read as an alias of `properties` (as the record models
read it). A draft reads every key that has a home in the record it becomes (the
record model's fields and the spellings its constructor takes), and only a key
with no home raises, with a did-you-mean and the list of keys it accepts.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import battinfo
from battinfo import api
from battinfo.api._equipment import _record_from_equipment_spec
from battinfo.ws import _EQUIPMENT_SPEC_DRAFT_KEYS

BASE = {"manufacturer": "Duracell", "model": "MN2400", "format": "cylindrical", "chemistry": "Zn-MnO2"}
QTY = {"nominal_voltage": {"value": 1.5, "unit": "V"}, "mass": {"value": 11.5, "unit": "g"}}

# The two drafts supplied with the collection evaluation, verbatim.
DURACELL_DRAFT = {
    "manufacturer": "Duracell",
    "model": "MN2400",
    "format": "cylindrical",
    "chemistry": "Zn-MnO2",
    "size_code": "R03",
    "iec_code": "LR03",
    "rechargeable": False,
    "specs": {
        "nominal_voltage": {"value": 1.5, "unit": "V"},
        "discharging_cutoff_voltage": {"value": 0.8, "unit": "V"},
        "diameter": {"value": 10.5, "unit": "mm"},
        "height": {"value": 44.5, "unit": "mm"},
        "mass": {"value": 11.5, "unit": "g"},
    },
}
CC_DISCHARGE_DRAFT = {
    "name": "CC discharge to 0.9 V cutoff",
    "type": "capacity_check",
    "description": "Constant-current discharge to a 0.9 V cutoff at room temperature.",
    "termination_criteria": {"discharging_cutoff_voltage": {"value": 0.9, "unit": "V"}},
    "conditions": {"temperature": {"value": 20, "unit": "degC"}},
}


def _write(root: Path, name: str, payload: dict) -> str:
    (root / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


@pytest.fixture()
def ws(tmp_path: Path) -> battinfo.ws.AuthoringWorkspace:
    return battinfo.workspace(tmp_path, registry_url=None)


def test_supplied_draft_keeps_its_five_datasheet_values(ws, tmp_path: Path) -> None:
    spec = ws.load(_write(tmp_path, "duracell-mn2400.cell-spec.json", DURACELL_DRAFT))
    assert spec.properties == DURACELL_DRAFT["specs"]
    saved = ws.save()
    record = json.loads(Path(saved["cell_specs"][0]["path"]).read_text(encoding="utf-8"))
    assert set(record["properties"]) == set(DURACELL_DRAFT["specs"])


def test_specs_and_properties_merge_like_the_model(ws, tmp_path: Path) -> None:
    payload = {
        **BASE,
        "properties": {"mass": {"value": 11.5, "unit": "g"}},
        "specs": {"mass": {"value": 99, "unit": "g"}, "nominal_voltage": {"value": 1.5, "unit": "V"}},
    }
    spec = ws.load(_write(tmp_path, "both.cell-spec.json", payload))
    model = battinfo.CellSpec(**payload)
    assert spec.properties == model.properties == QTY  # properties wins per key, as in CellSpec


def test_template_placeholders_are_dropped_but_ranges_are_kept(ws, tmp_path: Path) -> None:
    payload = {
        **BASE,
        "properties": {
            "nominal_voltage": {"value": None, "unit": "V"},  # unfilled placeholder
            "maximum_storage_temperature": {"min_value": -20, "max_value": 35, "unit": "degC"},
            "cycle_life": {"value_text": "not stated", "unit": "1"},
        },
    }
    spec = ws.load(_write(tmp_path, "range.cell-spec.json", payload))
    assert set(spec.properties) == {"maximum_storage_temperature", "cycle_life"}


@pytest.mark.parametrize(("key", "suggestion"), [("speks", "properties"), ("manufactuer", "manufacturer")])
def test_unknown_cell_spec_key_raises_with_did_you_mean(ws, tmp_path: Path, key: str, suggestion: str) -> None:
    payload = (
        {**BASE, key: QTY}
        if key == "speks"
        else {**{k: v for k, v in BASE.items() if k != "manufacturer"}, "manufacturer": "Duracell", key: "Duracell"}
    )
    with pytest.raises(ValueError) as excinfo:
        ws.load(_write(tmp_path, "typo.cell-spec.json", payload))
    message = str(excinfo.value)
    assert f"'{key}' (did you mean '{suggestion}'?)" in message
    assert "typo.cell-spec.json" in message
    assert "A cell-spec draft accepts: " in message and "datasheet_revision" in message  # the keys are listed
    assert ws._ws.cell_specs == []  # nothing was loaded


def test_unknown_key_without_a_close_match_is_named(ws, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'bogus_field'"):
        ws.load(_write(tmp_path, "b.cell-spec.json", {**BASE, "bogus_field": 1}))
    with pytest.raises(ValueError, match="'bogus_field'"):
        ws.load(_write(tmp_path, "t.test-spec.json", {"name": "T", "type": "capacity_check", "bogus_field": 1}))
    assert ws._ws.test_specs == []


def test_termination_criteria_raises_and_says_how_to_state_a_cutoff(ws, tmp_path: Path) -> None:
    with pytest.raises(ValueError) as excinfo:
        ws.load(_write(tmp_path, "cc-discharge.test-spec.json", CC_DISCHARGE_DRAFT))
    message = str(excinfo.value)
    assert "termination_criteria" in message
    assert "until 0.9 V" in message  # the cutoff stated in a step
    assert '"termination"' in message  # or as a structured termination on a method step
    assert ws._ws.test_specs == []
    # Stating the cutoff the current way loads, and the cutoff is kept.
    fixed = {k: v for k, v in CC_DISCHARGE_DRAFT.items() if k != "termination_criteria"}
    fixed["steps"] = ["Discharge at 5 mA until 0.9 V"]
    protocol = ws.load(_write(tmp_path, "cc-discharge-fixed.test-spec.json", fixed))
    termination = protocol.method[0].termination[0]
    assert (termination.quantity, termination.value, termination.unit) == ("voltage", 0.9, "V")


def test_unknown_equipment_spec_key_raises(ws, tmp_path: Path) -> None:
    payload = {
        "name": "SkyRC MC3000",
        "manufacturer": "SkyRC",
        "model": "MC3000",
        "equipment_class": "cycler",
        "chanel_count": 4,
    }
    with pytest.raises(ValueError, match=r"'chanel_count' \(did you mean 'channel_count'\?\)"):
        ws.load(_write(tmp_path, "mc3000.equipment-spec.json", payload))


def test_template_drafts_still_load(ws, tmp_path: Path) -> None:
    """Every key ws.template() writes is accepted, '_' comment keys included."""
    cell_draft = ws.template(
        "cell-spec", manufacturer="Duracell", model="MN2400", format="cylindrical", chemistry="zn-mno2"
    )
    assert ws.load(cell_draft).manufacturer == "Duracell"
    test_draft = ws.template(
        "test-spec", name="CC discharge", type="capacity_check", steps=["Discharge at C/5 until 0.9 V"]
    )
    assert ws.load(test_draft).name == "CC discharge"
    equipment_draft = ws.template(
        "equipment-spec", name="SkyRC MC3000", manufacturer="SkyRC", model="MC3000", channel_count=4
    )
    assert ws.load(equipment_draft)["equipment_spec"]["name"] == "SkyRC MC3000"


# ── Every key with a home in the record loads ─────────────────────────────────

ORCID = "https://orcid.org/0000-0002-1825-0097"


def _saved(saved: dict, kind: str) -> dict:
    item = saved[kind][0]
    assert item["status"] == "created" and not item.get("failed"), item
    return json.loads(Path(item["path"]).read_text(encoding="utf-8"))


def test_cell_spec_draft_reads_the_record_fields(ws, tmp_path: Path) -> None:
    draft = {
        "manufacturer": "Duracell",
        "model_name": "MN2400",
        "format": "cylindrical",
        "chemistry": "zn-mno2",
        "product_type": "commercial",
        "datasheet_revision": "2019-03",
        "rechargeable": False,
        "construction": {"assembly_type": "other"},
        "housing": {"comment": "nickel-plated steel can"},
        "comment": "Values from the 2019 datasheet.",
        "notes": ["Checked by hand."],
        "source_url": "https://example.org/mn2400.pdf",
        "retrieved_at": "2026-10-01",
        "curated_by": ORCID,
        "uid": "1f8r6v2k9p4m3t7x",
        "nominal_capacity": {"value": 1.2, "unit": "Ah"},  # a flat property name, as CellSpec takes it
        "properties": {"nominal_voltage": {"value": 1.5, "unit": "V"}},
    }
    spec = ws.load(_write(tmp_path, "mn2400.cell-spec.json", draft))
    assert spec.id == "https://w3id.org/battinfo/id/1001/spec/1f8r-6v2k-9p4m-3t7x"  # the new workspace's base
    assert (spec.model, spec.datasheet_revision) == ("MN2400", "2019-03")
    assert spec.properties == {
        "nominal_voltage": {"value": 1.5, "unit": "V"},
        "nominal_capacity": {"value": 1.2, "unit": "Ah"},
    }

    record = _saved(ws.save(), "cell_specs")
    body = record["cell_spec"]
    assert (body["product_type"], body["datasheet_revision"], body["rechargeable"]) == ("commercial", "2019-03", False)
    assert record["construction"] == {"assembly_type": "other"}
    assert record["housing"]["comment"] == "nickel-plated steel can"
    assert record["notes"] == ["Values from the 2019 datasheet.", "Checked by hand."]
    provenance = record["provenance"]
    assert (provenance["source_type"], provenance["source_url"], provenance["curated_by"]) == (
        "datasheet",
        "https://example.org/mn2400.pdf",
        ORCID,
    )
    assert isinstance(provenance["retrieved_at"], int)


def test_cell_spec_draft_reads_component_links(ws, tmp_path: Path) -> None:
    links = {
        "manufacturer_id": "https://w3id.org/battinfo/organization/1f8r-6v2k-9p4m-3t7a",
        "positive_electrode_spec_id": "https://w3id.org/battinfo/spec/1f8r-6v2k-9p4m-3t7b",
        "electrolyte_spec_id": "https://w3id.org/battinfo/spec/1f8r-6v2k-9p4m-3t7c",
    }
    spec = ws.load(_write(tmp_path, "links.cell-spec.json", {**BASE, **links}))
    assert {key: getattr(spec, key) for key in links} == links


def test_test_spec_draft_reads_the_record_fields(ws, tmp_path: Path) -> None:
    draft = {
        "name": "CC discharge",
        "test_kind": "capacity_check",
        "steps": ["Discharge at C/5 until 0.9 V"],
        "version": "2",
        "protocol": "IEC 60086-2 application test",
        "protocol_url": "https://example.org/iec",
        "comment": "Run at room temperature.",
        "notes": ["Second note."],
        "source_type": "lab",
        "source_name": "Lab handbook",
        "source_url": "https://example.org/protocol.pdf",
        "retrieved_at": "2026-10-01",
        "workflow_version": "w1",
        "curated_by": ORCID,
    }
    protocol = ws.load(_write(tmp_path, "cc.test-spec.json", draft))
    assert (protocol.version, protocol.protocol.url) == ("2", "https://example.org/iec")

    record = _saved(ws.save(), "test_specs")
    assert (record["test_spec"]["version"], record["test_spec"]["protocol_url"]) == ("2", "https://example.org/iec")
    # The test-spec record has no field for a protocol's name, so it is kept as a note.
    assert record["notes"] == ["Run at room temperature.", "Second note.", "protocol: IEC 60086-2 application test"]
    provenance = record["provenance"]
    assert {
        key: provenance[key] for key in ("source_type", "source_name", "source_url", "workflow_version", "curated_by")
    } == {
        "source_type": "lab",
        "source_name": "Lab handbook",
        "source_url": "https://example.org/protocol.pdf",
        "workflow_version": "w1",
        "curated_by": ORCID,
    }


def test_equipment_spec_draft_reads_the_builder_fields(ws, tmp_path: Path) -> None:
    draft = {
        "name": "SkyRC MC3000",
        "manufacturer": "SkyRC",
        "model": "MC3000",
        "equipment_class": "cycler",
        "uid": "1f8r6v2k9p4m3t7z",
        "notes": "Bought in 2024.",
        "source_type": "manual",
        "source_name": "SkyRC site",
        "source_file": "mc3000-manual.pdf",
        "retrieved_at": "2026-10-01",
    }
    record = ws.load(_write(tmp_path, "mc3000.equipment-spec.json", draft))
    assert record["equipment_spec"]["id"] == "https://w3id.org/battinfo/id/1001/spec/1f8r-6v2k-9p4m-3t7z"
    assert record["notes"] == ["Bought in 2024."]
    provenance = record["provenance"]
    assert (provenance["source_type"], provenance["source_name"], provenance["source_file"]) == (
        "manual",
        "SkyRC site",
        "mc3000-manual.pdf",
    )
    assert isinstance(provenance["retrieved_at"], int)


def test_equipment_spec_draft_keys_are_the_builder_fields() -> None:
    """The equipment-spec record has no model class: its draft keys follow create_equipment_spec().

    All but ``base``: the base a record mints under is the workspace's, never a draft's.
    """
    assert set(inspect.signature(_record_from_equipment_spec).parameters) - {"base"} == _EQUIPMENT_SPEC_DRAFT_KEYS


def test_api_authoring_drafts_load_with_every_key(ws, tmp_path: Path) -> None:
    """template_cell_spec_draft() and template_test_spec_draft() write keys ws.load() now reads."""
    cell_draft = api.template_cell_spec_draft(
        manufacturer="Duracell",
        model_name="MN2400",
        chemistry="zn-mno2",
        format="cylindrical",
        datasheet_revision="2019-03",
    )
    spec = ws.load(_write(tmp_path, "draft.cell-spec.json", cell_draft))
    assert spec.datasheet_revision == "2019-03"
    assert spec.comment == [cell_draft["comment"]]
    test_draft = api.template_test_spec_draft(name="CC discharge", version="2", protocol_url="https://example.org/iec")
    protocol = ws.load(_write(tmp_path, "draft.test-spec.json", test_draft))
    assert (protocol.version, protocol.protocol.url) == ("2", "https://example.org/iec")
    assert protocol.comment == [test_draft["comment"]]


@pytest.mark.parametrize(
    ("name", "payload", "match"),
    [
        ("a.cell-spec.json", {**BASE, "model_name": "MN1500"}, "'model_name' and 'model' disagree"),
        (
            "b.cell-spec.json",
            {**BASE, "source_url": "https://example.org/a", "source": {"url": "https://example.org/b"}},
            "'source_url' and 'source.url' disagree",
        ),
        ("c.test-spec.json", {"name": "T", "type": "capacity_check", "kind": "cycling"}, "name different test types"),
        (
            "d.test-spec.json",
            {
                "name": "T",
                "type": "capacity_check",
                "protocol_url": "https://example.org/a",
                "protocol": {"url": "https://example.org/b"},
            },
            "'protocol_url' and 'protocol.url' disagree",
        ),
    ],
)
def test_a_value_given_two_ways_must_agree(ws, tmp_path: Path, name: str, payload: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ws.load(_write(tmp_path, name, payload))
    assert ws._ws.cell_specs == [] and ws._ws.test_specs == []


def test_a_property_that_is_not_a_quantity_raises(ws, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"property 'nominal_voltage' must be a quantity object"):
        ws.load(_write(tmp_path, "bare.cell-spec.json", {**BASE, "nominal_voltage": 1.5}))
    assert ws._ws.cell_specs == []


@pytest.mark.parametrize("key", ["kind", "schema_version", "cell_specification_id", "short_id"])
def test_keys_with_no_home_in_the_record_still_raise(ws, tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match=f"unknown key\\(s\\) in a cell-spec draft: '{key}'"):
        ws.load(_write(tmp_path, "x.cell-spec.json", {**BASE, key: "x"}))
