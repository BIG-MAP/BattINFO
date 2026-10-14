"""The declared chemistry decides the battery classes of a cell.

The described battery of a cell spec is typed from its format, cell
configuration, chemistry, electrode bases and IEC code. An electrode basis adds
its battery class only when that class belongs to the declared chemistry, so a
zinc cell with an MnO2 positive is never a LithiumManganeseDioxideBattery and a
K-ion cell with a graphite negative never a LithiumIonGraphiteBattery. A record
whose negative electrode contradicts its chemistry is refused by the strict and
publisher policies.

ws.import_() reads the chemistry back from the first chemistry class in the
stack and rebuilds the electrode bases and the cell configuration, so a deposit
written before this change, whose stacks carry the extra classes, imports with
the chemistry its author declared.
"""

from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path
from typing import Any

import pytest

import battinfo
from battinfo.jsonld import record_to_jsonld
from battinfo.transform.cell_spec_node import physical_type_stack
from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
from battinfo.validate.record import validate_record_report
from battinfo.ws import AuthoringWorkspace

ROOT = Path(__file__).resolve().parents[1]
# Written by BattINFO at 057b66a0, before the electrode bases were gated by the
# chemistry: the same cells as CASES below, each spec with one cell, through
# ws.save() and ws.preview_jsonld().
OLD_DEPOSIT = ROOT / "tests" / "fixtures" / "deposits" / "type-stacks-before-0.8.0.battinfo.json"
CONFLICT = "semantic.chemistry_electrode_conflict"
SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"

# model -> (CellSpec fields, the described battery's @type stack)
CASES: dict[str, tuple[dict[str, str], list[str]]] = {
    "ZnMnO2-ALK": (
        {
            "format": "coin",
            "chemistry": "alkaline-zn-mno2",
            "positive_electrode_basis": "mno2",
            "negative_electrode_basis": "zinc",
        },
        ["BatteryCell", "CoinCell", "AlkalineZincManganeseDioxideBattery"],
    ),
    "ZnC-R6": (
        {
            "format": "cylindrical",
            "chemistry": "zinc-carbon",
            "positive_electrode_basis": "mno2",
            "negative_electrode_basis": "zinc",
        },
        ["BatteryCell", "CylindricalBattery", "ZincCarbonBattery"],
    ),
    "LiMnO2-2032": (
        {
            "format": "coin",
            "chemistry": "li-mno2",
            "positive_electrode_basis": "mno2",
            "negative_electrode_basis": "lithium",
        },
        ["BatteryCell", "CoinCell", "LithiumManganeseDioxideBattery", "LithiumMetalBattery"],
    ),
    "Li-NMC811": (
        {
            "format": "coin",
            "chemistry": "li-metal",
            "positive_electrode_basis": "nmc811",
            "negative_electrode_basis": "lithium",
        },
        ["BatteryCell", "CoinCell", "LithiumMetalBattery"],
    ),
    "NMC811-Li-half": (
        {
            "format": "coin",
            "chemistry": "li-ion",
            "positive_electrode_basis": "nmc811",
            "negative_electrode_basis": "lithium",
            "cell_configuration": "half_cell",
        },
        [
            "BatteryCell",
            "CoinCell",
            "BatteryHalfCell",
            "HalfCellDevice",
            "LithiumIonBattery",
            "LithiumIonNickelManganeseCobaltOxideBattery",
        ],
    ),
    "K-graphite": (
        {"format": "coin", "chemistry": "k-ion", "negative_electrode_basis": "graphite"},
        ["BatteryCell", "CoinCell", "PotassiumIonBattery"],
    ),
    # NVPF is not in the electrode-basis vocabulary: it is written as a
    # labelled generic electrode, and the import reads the label back.
    "NVPF-hard-carbon": (
        {
            "format": "coin",
            "chemistry": "na-ion",
            "positive_electrode_basis": "NVPF",
            "negative_electrode_basis": "hard-carbon",
        },
        ["BatteryCell", "CoinCell", "SodiumIonBattery"],
    ),
    "LiS-pouch": (
        {"format": "pouch", "chemistry": "li-s", "negative_electrode_basis": "lithium"},
        ["BatteryCell", "PouchCell", "LithiumSulfurBattery", "LithiumMetalBattery"],
    ),
    "LFP-graphite": (
        {
            "format": "cylindrical",
            "chemistry": "li-ion",
            "positive_electrode_basis": "lfp",
            "negative_electrode_basis": "graphite",
        },
        [
            "BatteryCell",
            "CylindricalBattery",
            "LithiumIonBattery",
            "LithiumIonIronPhosphateBattery",
            "LithiumIonGraphiteBattery",
        ],
    ),
    "LFP-LTO": (
        {
            "format": "cylindrical",
            "chemistry": "li-ion",
            "positive_electrode_basis": "lfp",
            "negative_electrode_basis": "lto",
        },
        [
            "BatteryCell",
            "CylindricalBattery",
            "LithiumIonBattery",
            "LithiumIonIronPhosphateBattery",
            "LithiumIonTitanateBattery",
        ],
    ),
}

# Not in the old deposit: NCA has no electrode class, so its electrode is not
# written and the import reads the basis from the battery class instead.
FRESH_ONLY: dict[str, tuple[dict[str, str], list[str]]] = {
    "NCA-graphite": (
        {
            "format": "cylindrical",
            "chemistry": "li-ion",
            "positive_electrode_basis": "nca",
            "negative_electrode_basis": "graphite",
        },
        [
            "BatteryCell",
            "CylindricalBattery",
            "LithiumIonBattery",
            "LithiumIonNickelCobaltAluminiumOxideBattery",
            "LithiumIonGraphiteBattery",
        ],
    ),
}
ALL_CASES = {**CASES, **FRESH_ONLY}


def _types(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def _cell_body(fields: dict[str, str]) -> dict[str, str]:
    """CellSpec keyword fields as the record's cell_spec body spells them."""
    body = dict(fields)
    body["cell_format"] = body.pop("format")
    return body


def _record(**fields: str) -> dict[str, Any]:
    spec = battinfo.CellSpec(id=SPEC_IRI, manufacturer="Example Lab", model="X1", source_type="manual", **fields)
    return spec.to_record()


def _saved_specs(root: Path) -> dict[str, dict[str, Any]]:
    folder = root / ".battinfo" / "records" / "cell-spec"
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]
    return {record["cell_spec"]["model"]: record for record in records}


def _spec_nodes(deposit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node["schema:model"]: node
        for node in deposit["@graph"]
        if "BatteryCellSpecification" in _types(node.get("@type"))
    }


def _emitted(record: dict[str, Any]) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return record_to_jsonld(record, "cell-spec")["isDescriptionFor"]


def _electrode_types(described: dict[str, Any]) -> dict[str, Any]:
    return {
        relation: described[relation].get("@type")
        for relation in ("hasPositiveElectrode", "hasNegativeElectrode")
        if isinstance(described.get(relation), dict)
    }


def _import_and_save(deposit_path: Path, root: Path) -> AuthoringWorkspace:
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.import_(str(deposit_path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws.save()
    return ws


# ── The stack follows the declared chemistry ──────────────────────────────────


@pytest.mark.parametrize("model", list(ALL_CASES))
def test_the_canonical_builder_types_each_cell_by_its_chemistry(model: str) -> None:
    fields, expected = ALL_CASES[model]
    assert physical_type_stack(_cell_body(fields)) == expected


@pytest.mark.parametrize("model", list(ALL_CASES))
def test_the_descriptor_path_agrees_with_the_canonical_builder(model: str) -> None:
    fields, expected = ALL_CASES[model]
    node = _descriptor_specification_to_jsonld(dict(fields))
    assert _types(node["isDescriptionFor"]["@type"]) == expected


@pytest.mark.parametrize(
    ("chemistry", "positive", "negative", "added", "absent"),
    [
        # li-metal says the negative electrode is lithium, so MnO2 makes it a Li-MnO2 cell.
        ("li-metal", "mno2", None, "LithiumManganeseDioxideBattery", None),
        ("li-primary", "mno2", None, "LithiumManganeseDioxideBattery", None),
        # Another lithium-metal couple is not a Li-MnO2 cell, whatever its electrodes say.
        ("li-cfx", "mno2", "lithium", "LithiumMetalBattery", "LithiumManganeseDioxideBattery"),
        # Lithium-ion positives and graphite add their classes to li-ion cells only.
        ("li-metal", "lfp", "lithium", "LithiumMetalBattery", "LithiumIonIronPhosphateBattery"),
        ("na-ion", "lfp", "graphite", "SodiumIonBattery", "LithiumIonGraphiteBattery"),
        # A chemistry outside the vocabulary declares no class, so the bases add none,
        ("Zn-MnO2 alkaline", "mno2", "zinc", "CoinCell", "LithiumManganeseDioxideBattery"),
        ("Li-ion polymer", "lfp", "graphite", "CoinCell", "LithiumIonIronPhosphateBattery"),
        ("Li-ion polymer", "lfp", "lithium", "CoinCell", "LithiumIonIronPhosphateBattery"),
        ("Li coin (vendor text)", None, "lithium", "CoinCell", "LithiumMetalBattery"),
        # except that an MnO2 positive with a lithium negative is a Li-MnO2 cell
        # (li-mno2 sits under li-metal, whose negative is lithium).
        ("Li/MnO2 coin (vendor text)", "MnO2", "lithium", "LithiumManganeseDioxideBattery", "LithiumMetalBattery"),
        ("Li/MnO2 coin (vendor text)", "mno2", "li-metal", "LithiumManganeseDioxideBattery", None),
        ("Li/MnO2 coin (vendor text)", "mno2", "zinc", "CoinCell", "LithiumManganeseDioxideBattery"),
    ],
)
def test_an_electrode_basis_class_must_belong_to_the_declared_chemistry(
    chemistry: str, positive: str | None, negative: str | None, added: str, absent: str | None
) -> None:
    cell = {"cell_format": "coin", "chemistry": chemistry}
    if positive:
        cell["positive_electrode_basis"] = positive
    if negative:
        cell["negative_electrode_basis"] = negative
    stack = physical_type_stack(cell)
    assert added in stack, stack
    if absent:
        assert absent not in stack, stack


@pytest.mark.parametrize("configuration", [{"cell_configuration": "half_cell"}, {"reference_electrode": "lithium"}])
def test_a_lithium_counter_electrode_does_not_make_a_free_text_mno2_cell_li_mno2(configuration: dict) -> None:
    cell = {
        "cell_format": "coin",
        "chemistry": "MnO2 half cell (vendor text)",
        "positive_electrode_basis": "mno2",
        "negative_electrode_basis": "lithium",
        **configuration,
    }
    assert "LithiumManganeseDioxideBattery" not in physical_type_stack(cell)


def test_the_descriptor_path_types_a_free_text_mno2_lithium_cell_as_li_mno2() -> None:
    fields = {
        "format": "coin",
        "chemistry": "Li/MnO2 coin (vendor text)",
        "positive_electrode_basis": "mno2",
        "negative_electrode_basis": "lithium",
    }
    node = _descriptor_specification_to_jsonld(dict(fields))
    assert "LithiumManganeseDioxideBattery" in _types(node["isDescriptionFor"]["@type"])
    assert physical_type_stack(_cell_body(fields)) == _types(node["isDescriptionFor"]["@type"])


def test_the_packaged_alkaline_example_is_an_alkaline_zinc_cell() -> None:
    path = ROOT / "examples" / "cell-spec" / "cell-spec-jgyy-x3h5-drmv-5tn5.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["cell_spec"]["chemistry"] == "alkaline-zn-mno2"
    assert _types(_emitted(record)["@type"]) == ["BatteryCell", "CoinCell", "AlkalineZincManganeseDioxideBattery"]
    report = validate_record_report(record, policy="strict")
    assert report.ok, report.render_errors()
    assert CONFLICT not in {issue.code for issue in report.issues}


# ── The semantic rule judges the inputs ───────────────────────────────────────


def _conflicts(record: dict[str, Any], policy: str) -> list[Any]:
    report = validate_record_report(record, policy=policy)
    return [issue for issue in report.issues if issue.code == CONFLICT]


@pytest.mark.parametrize(
    "fields",
    [
        # A full li-ion cell cannot have a lithium-metal negative.
        {
            "format": "coin",
            "chemistry": "li-ion",
            "positive_electrode_basis": "nmc811",
            "negative_electrode_basis": "lithium",
        },
        {"format": "coin", "chemistry": "Li-ion", "negative_electrode_basis": "li-metal"},
        # A lithium-metal couple names its negative electrode.
        {"format": "coin", "chemistry": "li-metal", "negative_electrode_basis": "graphite"},
        {"format": "pouch", "chemistry": "li-s", "negative_electrode_basis": "hard-carbon"},
        {"format": "coin", "chemistry": "li-primary", "negative_electrode_basis": "zinc"},
        # So does a zinc couple, half cell or not.
        {"format": "coin", "chemistry": "alkaline-zn-mno2", "negative_electrode_basis": "lithium"},
        {
            "format": "coin",
            "chemistry": "zinc-carbon",
            "negative_electrode_basis": "lithium",
            "cell_configuration": "half_cell",
        },
        # A zinc negative makes a full cell a zinc cell.
        {
            "format": "coin",
            "chemistry": "li-ion",
            "positive_electrode_basis": "lfp",
            "negative_electrode_basis": "zinc",
        },
    ],
)
def test_a_negative_electrode_that_contradicts_the_chemistry_is_an_error(fields: dict[str, str]) -> None:
    record = _record(**fields)
    for policy in ("strict", "publisher"):
        found = _conflicts(record, policy)
        assert [issue.severity for issue in found] == ["error"], (policy, found)
        assert found[0].path == "cell_spec.negative_electrode_basis"
    # The tolerant policies still say so, as a warning.
    for policy in ("default", "ingest"):
        assert [issue.severity for issue in _conflicts(record, policy)] == ["warning"], policy


@pytest.mark.parametrize(
    "fields",
    [
        *(fields for fields, _ in ALL_CASES.values()),
        # Lithium can be the counter or reference electrode of any half or three-electrode cell.
        {
            "format": "coin",
            "chemistry": "li-ion",
            "negative_electrode_basis": "lithium",
            "reference_electrode": "lithium",
        },
        {
            "format": "coin",
            "chemistry": "li-ion",
            "negative_electrode_basis": "lithium-metal",
            "cell_configuration": "three_electrode_cell",
        },
        {"format": "coin", "chemistry": "li-primary", "negative_electrode_basis": "li-metal"},
        {"format": "coin", "chemistry": "zn-mno2", "negative_electrode_basis": "Zinc"},
        {"format": "coin", "chemistry": "zn-air", "negative_electrode_basis": "zinc"},
        # A chemistry or a basis outside the vocabulary is not judged.
        {"format": "coin", "chemistry": "Zn-MnO2 alkaline", "negative_electrode_basis": "lithium"},
        {"format": "coin", "chemistry": "li-metal", "negative_electrode_basis": "copper foil"},
        {"format": "coin", "chemistry": "li-ion", "negative_electrode_basis": "unknown"},
    ],
)
def test_a_negative_electrode_that_fits_the_chemistry_passes(fields: dict[str, str]) -> None:
    assert _conflicts(_record(**fields), "publisher") == []


# ── Import reads the declared chemistry back ──────────────────────────────────


@pytest.fixture(scope="module")
def fresh_round_trip(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """save -> preview_jsonld -> import_ -> save, with every case in one deposit."""
    base = tmp_path_factory.mktemp("fresh")
    source = AuthoringWorkspace(root=base / "source", registry_url=None)
    source.license("cc-by-4.0")
    for model, (fields, _) in ALL_CASES.items():
        spec = battinfo.CellSpec(
            manufacturer="Example Lab",
            model=model,
            properties={"nominal_voltage": {"value": 3.6, "unit": "V"}},
            **fields,
        )
        source.add("cell", spec=spec, serial_numbers=[f"{model}-01"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source.save()
        deposit_path = source.preview_jsonld()
    _import_and_save(deposit_path, base / "imported")
    return {
        "source": _saved_specs(base / "source"),
        "deposit": json.loads(deposit_path.read_text(encoding="utf-8")),
        "imported": _saved_specs(base / "imported"),
    }


@pytest.mark.parametrize("model", list(ALL_CASES))
def test_the_deposit_carries_the_stack(fresh_round_trip: dict[str, Any], model: str) -> None:
    _, expected = ALL_CASES[model]
    deposit = fresh_round_trip["deposit"]
    node = _spec_nodes(deposit)[model]
    assert _types(node["isDescriptionFor"]["@type"]) == expected
    # The cell built to the spec carries the same classes.
    [cell] = [n for n in deposit["@graph"] if (n.get("dcterms:conformsTo") or {}).get("@id") == node["@id"]]
    assert _types(cell["@type"]) == expected


@pytest.mark.parametrize("model", list(ALL_CASES))
def test_save_preview_import_save_keeps_chemistry_bases_and_stack(fresh_round_trip: dict[str, Any], model: str) -> None:
    _, expected = ALL_CASES[model]
    source = fresh_round_trip["source"][model]
    imported = fresh_round_trip["imported"][model]
    for field in ("id", "chemistry", "cell_format", "cell_configuration"):
        assert imported["cell_spec"].get(field) == source["cell_spec"].get(field), field
    source_node, imported_node = _emitted(source), _emitted(imported)
    assert _types(imported_node["@type"]) == _types(source_node["@type"]) == expected
    # The electrode bases come back as the electrodes they were written as. A
    # specific NMC grade comes back as nmc: all of them share one electrode class.
    assert _electrode_types(imported_node) == _electrode_types(source_node)
    for field in ("positive_electrode_basis", "negative_electrode_basis"):
        stated = source["cell_spec"].get(field)
        recovered = imported["cell_spec"].get(field)
        assert (recovered is None) == (stated is None), field
        if stated is not None and not stated.startswith("nmc"):
            assert recovered == stated, field


def test_an_unmapped_basis_and_a_classless_basis_come_back(fresh_round_trip: dict[str, Any]) -> None:
    imported = fresh_round_trip["imported"]
    # Written as a labelled generic electrode.
    assert imported["NVPF-hard-carbon"]["cell_spec"]["positive_electrode_basis"] == "NVPF"
    # NCA has no electrode class, so no electrode node; its battery class names it.
    assert "hasPositiveElectrode" not in _emitted(fresh_round_trip["source"]["NCA-graphite"])
    assert imported["NCA-graphite"]["cell_spec"]["positive_electrode_basis"] == "nca"


# ── Deposits written with the earlier stacks ──────────────────────────────────


def test_an_electrode_class_a_basis_used_to_emit_still_names_it(tmp_path: Path) -> None:
    """Before 0.8.0 an lnmo electrode was typed with the class upstream deprecated."""
    deposit = {
        "@context": {"schema": "https://schema.org/"},
        "@graph": [
            {
                "@id": SPEC_IRI,
                "@type": ["BatteryCellSpecification", "schema:ProductModel", "schema:CreativeWork"],
                "schema:name": "Example Lab LNMO-graphite",
                "schema:model": "LNMO-graphite",
                "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Example Lab"},
                "isDescriptionFor": {
                    "@type": ["BatteryCell", "CoinCell", "LithiumIonBattery", "LithiumIonGraphiteBattery"],
                    "hasPositiveElectrode": {"@type": "LithiumNickelManganeseOxideElectrode"},
                    "hasNegativeElectrode": {"@type": "GraphiteElectrode"},
                },
            }
        ],
    }
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(deposit), encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path / "ws", registry_url=None)
    ws.import_(str(path))
    [spec] = ws._ws.cell_specs
    assert (spec.chemistry, spec.positive_electrode_basis, spec.negative_electrode_basis) == (
        "li-ion",
        "lnmo",
        "graphite",
    )


@pytest.fixture(scope="module")
def old_round_trip(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("old") / "imported"
    _import_and_save(OLD_DEPOSIT, root)
    return {
        "deposit": json.loads(OLD_DEPOSIT.read_text(encoding="utf-8")),
        "imported": _saved_specs(root),
    }


def test_the_old_deposit_carries_the_old_stacks(old_round_trip: dict[str, Any]) -> None:
    nodes = _spec_nodes(old_round_trip["deposit"])
    assert set(nodes) == set(CASES)
    # The electrode bases added classes of other chemistries after the declared one.
    assert _types(nodes["ZnMnO2-ALK"]["isDescriptionFor"]["@type"])[-1] == "LithiumManganeseDioxideBattery"
    assert _types(nodes["K-graphite"]["isDescriptionFor"]["@type"])[-1] == "LithiumIonGraphiteBattery"
    assert _types(nodes["NMC811-Li-half"]["isDescriptionFor"]["@type"])[-1] == "LithiumMetalBattery"


@pytest.mark.parametrize("model", list(CASES))
def test_an_old_deposit_imports_the_declared_chemistry_and_saves_the_new_stack(
    old_round_trip: dict[str, Any], model: str
) -> None:
    fields, expected = CASES[model]
    node = _spec_nodes(old_round_trip["deposit"])[model]
    imported = old_round_trip["imported"][model]["cell_spec"]
    assert imported["id"] == node["@id"]
    assert imported["chemistry"] == fields["chemistry"]
    assert imported.get("cell_configuration") == fields.get("cell_configuration")
    for field in ("positive_electrode_basis", "negative_electrode_basis"):
        stated = fields.get(field)
        recovered = imported.get(field)
        assert (recovered is None) == (stated is None), field
        if stated is not None and not stated.startswith("nmc"):
            assert recovered == stated, field
    assert _types(_emitted(old_round_trip["imported"][model])["@type"]) == expected


def test_an_old_alkaline_deposit_with_a_free_text_chemistry_is_not_saved_as_li_mno2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The alkaline example's chemistry was once the free text 'Zn-MnO2 alkaline'.

    That text named no class, so the deposit's stack held only the class the
    MnO2 positive added, LithiumManganeseDioxideBattery. The import reads li-mno2
    from it and the zinc negative from the electrode, says they disagree, and
    the strict save refuses the record rather than republish it as li-mno2.
    """
    deposit = json.loads(OLD_DEPOSIT.read_text(encoding="utf-8"))
    spec_node = _spec_nodes(deposit)["ZnMnO2-ALK"]
    keep = {spec_node["@id"]}
    graph = []
    for node in deposit["@graph"]:
        conforms = (node.get("dcterms:conformsTo") or {}).get("@id")
        if node.get("@id") in keep or conforms in keep:
            node = copy.deepcopy(node)
            target = node["isDescriptionFor"] if node.get("@id") in keep else node
            target["@type"] = [t for t in _types(target["@type"]) if t != "AlkalineZincManganeseDioxideBattery"]
            graph.append(node)
    assert len(graph) == 2
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps({**deposit, "@graph": graph}), encoding="utf-8")

    ws = AuthoringWorkspace(root=tmp_path / "ws", registry_url=None)
    ws.import_(str(path))
    out = capsys.readouterr().out
    assert "WARNING" in out and "li-mno2" in out and "zinc" in out, out
    [spec] = ws._ws.cell_specs
    assert (spec.chemistry, spec.positive_electrode_basis, spec.negative_electrode_basis) == ("li-mno2", "mno2", "zinc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="negative_electrode_basis"):
            ws.save()
