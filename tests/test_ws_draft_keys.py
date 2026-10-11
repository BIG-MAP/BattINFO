"""ws.load() does not drop draft keys it does not read (evaluation finding C-13).

The supplied MN2400 cell-spec draft carried its five datasheet values under
`specs`, the key drafts used until June; ws.load() kept none of them, and the
test-spec draft lost its structured `termination_criteria` cutoff, all without a
warning. `specs` is now read as an alias of `properties` (as the record models
read it), and any other key a draft loader does not read raises with a
did-you-mean and the list of keys it accepts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo

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
    payload = {**BASE, "properties": {"mass": {"value": 11.5, "unit": "g"}},
               "specs": {"mass": {"value": 99, "unit": "g"}, "nominal_voltage": {"value": 1.5, "unit": "V"}}}
    spec = ws.load(_write(tmp_path, "both.cell-spec.json", payload))
    model = battinfo.CellSpec(**payload)
    assert spec.properties == model.properties == QTY  # properties wins per key, as in CellSpec


def test_template_placeholders_are_dropped_but_ranges_are_kept(ws, tmp_path: Path) -> None:
    payload = {**BASE, "properties": {
        "nominal_voltage": {"value": None, "unit": "V"},                       # unfilled placeholder
        "maximum_storage_temperature": {"min_value": -20, "max_value": 35, "unit": "degC"},
        "cycle_life": {"value_text": "not stated", "unit": "1"},
    }}
    spec = ws.load(_write(tmp_path, "range.cell-spec.json", payload))
    assert set(spec.properties) == {"maximum_storage_temperature", "cycle_life"}


@pytest.mark.parametrize(("key", "suggestion"), [("speks", "properties"), ("manufactuer", "manufacturer")])
def test_unknown_cell_spec_key_raises_with_did_you_mean(ws, tmp_path: Path, key: str, suggestion: str) -> None:
    payload = {**BASE, key: QTY} if key == "speks" else {**{k: v for k, v in BASE.items() if k != "manufacturer"},
                                                         "manufacturer": "Duracell", key: "Duracell"}
    with pytest.raises(ValueError) as excinfo:
        ws.load(_write(tmp_path, "typo.cell-spec.json", payload))
    message = str(excinfo.value)
    assert f"'{key}' (did you mean '{suggestion}'?)" in message
    assert "typo.cell-spec.json" in message
    assert "manufacturer, model" in message  # the allowed keys are listed
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
    payload = {"name": "SkyRC MC3000", "manufacturer": "SkyRC", "model": "MC3000",
               "equipment_class": "cycler", "chanel_count": 4}
    with pytest.raises(ValueError, match=r"'chanel_count' \(did you mean 'channel_count'\?\)"):
        ws.load(_write(tmp_path, "mc3000.equipment-spec.json", payload))


def test_template_drafts_still_load(ws, tmp_path: Path) -> None:
    """Every key ws.template() writes is accepted, '_' comment keys included."""
    cell_draft = ws.template("cell-spec", manufacturer="Duracell", model="MN2400",
                             format="cylindrical", chemistry="zn-mno2")
    assert ws.load(cell_draft).manufacturer == "Duracell"
    test_draft = ws.template("test-spec", name="CC discharge", type="capacity_check",
                             steps=["Discharge at C/5 until 0.9 V"])
    assert ws.load(test_draft).name == "CC discharge"
    equipment_draft = ws.template("equipment-spec", name="SkyRC MC3000", manufacturer="SkyRC",
                                  model="MC3000", channel_count=4)
    assert ws.load(equipment_draft)["equipment_spec"]["name"] == "SkyRC MC3000"
