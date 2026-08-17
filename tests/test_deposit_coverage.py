"""Guard: every record type either reaches the deposit graph or says why not.

The Flores half-cell corpus published 323 records and got a ``deposit.jsonld``
with 301 nodes. All 24 missing ones were electrodes: ``_assemble_zenodo_jsonld``
promoted standalone ``material-spec``/``material`` records to first-class deposit
nodes and nothing else, so the electrode layer was read off disk by
``_read_record_sets``, never used, and silently absent from the artifact a reader
downloads. Records that save cleanly, validate cleanly and emit cleanly still did
not get published.

Nothing failed. The gap was found by a human diffing record counts against node
counts and writing it up as a report footnote, which is not a mechanism.

This module is the mechanism: it builds one record of every registered
:data:`ENTITY_KINDS` type, wires them into a single record set, assembles the
deposit graph and asserts each record's IRI is a node in it — or that the type is
listed in :data:`battinfo.ws.DEPOSIT_COVERAGE_EXEMPT` with a reason. Registering a
new record type without giving it a path into the deposit therefore fails a test,
and (as with ``KNOWN_GAPS`` in the parity sweep) an exemption that stops being
true also fails, so the list cannot become a graveyard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (  # noqa: E402
    create_channel,
    create_component_instance,
    create_component_spec,
    create_electrode,
    create_electrode_spec,
    create_equipment,
    create_equipment_spec,
    create_material,
    create_material_spec,
    create_parameter_set,
)
from battinfo.bundle import Cell, CellSpec, Dataset, ProvenanceInfo, Test, TestSpec  # noqa: E402
from battinfo.entities import COMPONENT_FAMILIES, ENTITY_KINDS  # noqa: E402
from battinfo.ws import (  # noqa: E402
    DEPOSIT_COVERAGE_EXEMPT,
    DEPOSIT_STANDALONE_KINDS,
    AuthoringWorkspace,
)

UID = "aaaa-bbbb-cccc-dddd"
CELL_SPEC_IRI = f"https://w3id.org/battinfo/spec/{UID}"
CELL_IRI = f"https://w3id.org/battinfo/cell/{UID}"
TEST_IRI = f"https://w3id.org/battinfo/test/{UID}"
TEST_SPEC_IRI = "https://w3id.org/battinfo/spec/bbbb-cccc-dddd-eeee"
DATASET_IRI = f"https://w3id.org/battinfo/dataset/{UID}"
EQUIPMENT_IRI = f"https://w3id.org/battinfo/equipment/{UID}"
CHANNEL_IRI = f"https://w3id.org/battinfo/channel/{UID}"
MATERIAL_SPEC_IRI = "https://w3id.org/battinfo/spec/cccc-dddd-eeee-ffff"
ELECTRODE_SPEC_IRI = "https://w3id.org/battinfo/spec/dddd-eeee-ffff-gggg"


def _record_sets() -> dict[str, list[dict]]:
    """One wired record of every registered type, keyed by on-disk subdir.

    Wired the way a real corpus is (cell spec -> cell -> test -> dataset, test on
    a channel of a unit, electrode batch on its design, powder under it), because
    several types reach the graph only through the record that references them.
    """
    material_spec = create_material_spec(
        validate=False, uid=MATERIAL_SPEC_IRI.rsplit("/", 1)[-1], name="Graphite powder",
        kind="graphite",
    )
    material = create_material(
        validate=False, uid="1111-2222-3333-4444", name="Graphite lot",
        material_spec_id=material_spec["material_spec"]["id"], lot="LOT-1",
    )
    electrode_spec = create_electrode_spec(
        validate=False, uid=ELECTRODE_SPEC_IRI.rsplit("/", 1)[-1], name="Graphite anode",
        kind="graphite", active_material_spec_id=material_spec["material_spec"]["id"],
        property={"areal_capacity": {"value": 3.4, "unit": "mA.h/cm2"}},
    )
    electrode = create_electrode(
        validate=False, uid="2222-3333-4444-5555", name="Coating batch A",
        electrode_spec_id=electrode_spec["electrode_spec"]["id"], batch="B-1",
    )
    equipment_spec = create_equipment_spec(
        validate=False, uid="3333-4444-5555-6666", name="MC3000",
    )
    equipment = create_equipment(
        validate=False, uid=UID, equipment_spec_id=equipment_spec["equipment_spec"]["id"],
        serial_number="SN-1",
    )
    channel = create_channel(validate=False, uid=UID, equipment_id=EQUIPMENT_IRI, index=1)
    parameter_set = create_parameter_set(
        validate=False, uid="4444-5555-6666-7777", name="Demo source - graphite",
        material_kind="graphite",
        claims=[{
            "parameter": "specific_capacity",
            "quantity": {"value": 372.0, "unit": "mAh/g"},
            "provenance_class": "literature",
        }],
    )

    cell_spec = CellSpec(
        id=CELL_SPEC_IRI, name="Demo half cell", manufacturer="Demo Co", model="DEMO-1",
        format="coin", chemistry="lithium_ion",
        positive_electrode_spec_id=electrode_spec["electrode_spec"]["id"],
        source=ProvenanceInfo(type="datasheet"),
    ).to_record()
    cell = Cell(
        id=CELL_IRI, name="cell-001", cell_spec_id=CELL_SPEC_IRI, serial_number="cell-001",
        source=ProvenanceInfo(type="measurement"),
    ).to_record()
    test_spec = TestSpec(
        id=TEST_SPEC_IRI, name="pOCV protocol", source=ProvenanceInfo(type="protocol"),
    ).to_record()
    test = Test(
        id=TEST_IRI, name="pOCV run", kind="cycling", cell_id=CELL_IRI,
        protocol_id=TEST_SPEC_IRI, equipment_id=EQUIPMENT_IRI, channel_id=CHANNEL_IRI,
        dataset_ids=[DATASET_IRI], source=ProvenanceInfo(type="measurement"),
    ).to_record()
    dataset = Dataset(
        id=DATASET_IRI, name="pOCV curves", cell_instance_id=CELL_IRI, test_id=TEST_IRI,
        access_url="https://example.org/data.parquet",
        source=ProvenanceInfo(type="measurement"),
    ).to_record()

    sets: dict[str, list[dict]] = {
        "cell-spec": [cell_spec],
        "cell-instance": [cell],
        "test-protocol": [test_spec],
        "test": [test],
        "dataset": [dataset],
        "material-spec": [material_spec],
        "material": [material],
        "electrode-spec": [electrode_spec],
        "electrode": [electrode],
        "equipment-spec": [equipment_spec],
        "equipment": [equipment],
        "channel": [channel],
        "parameter-set": [parameter_set],
    }
    # Generic component families (separator, current-collector, electrolyte,
    # housing): spec + instance, so the sweep sees them too.
    for index, family in enumerate(COMPONENT_FAMILIES):
        hyphen = family.replace("_", "-")
        spec_uid = f"{index}aaa-bbbb-cccc-dddd"
        inst_uid = f"{index}eee-ffff-gggg-hhhh"
        spec = create_component_spec(
            family, validate=False, uid=spec_uid, name=f"{hyphen} spec",
        )
        sets[f"{hyphen}-spec"] = [spec]
        sets[hyphen] = [
            create_component_instance(
                family, validate=False, uid=inst_uid,
                spec_id=f"https://w3id.org/battinfo/spec/{spec_uid}",
            )
        ]
    return sets


def _record_iri(record: dict) -> str:
    for body in record.values():
        if isinstance(body, dict) and isinstance(body.get("id"), str):
            return body["id"]
    raise AssertionError(f"record carries no body id: {sorted(record)}")


def _deposit_graph(record_sets: dict[str, list[dict]]) -> dict:
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="coverage sweep",
    )


def _deposit_node_ids(record_sets: dict[str, list[dict]]) -> set[str]:
    """IRIs of the TOP-LEVEL ``@graph`` members.

    Deliberately not a recursive walk: a nested ``{"@id": ...}`` is a reference to
    a node, not a described one, and a deposit whose electrode IRIs appeared only
    as dangling references would be exactly the artifact this guard exists to
    reject.
    """
    return {
        node["@id"]
        for node in _deposit_graph(record_sets)["@graph"]
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }


def _coverage() -> dict[str, bool]:
    """entity_type -> whether that type's record reached the deposit graph."""
    record_sets = _record_sets()
    ids = _deposit_node_ids(record_sets)
    return {
        kind.entity_type: all(_record_iri(rec) in ids for rec in record_sets[kind.subdir])
        for kind in ENTITY_KINDS
    }


def test_every_record_type_reaches_the_deposit_graph_or_is_exempt() -> None:
    """The E2 guard: a saved record type absent from the deposit fails here."""
    missing = [
        entity_type
        for entity_type, covered in _coverage().items()
        if not covered and entity_type not in DEPOSIT_COVERAGE_EXEMPT
    ]
    assert not missing, (
        "record types read by _read_record_sets but absent from the assembled "
        "deposit graph. Promote them in _assemble_zenodo_jsonld (see "
        "DEPOSIT_STANDALONE_KINDS), or add them to DEPOSIT_COVERAGE_EXEMPT with a "
        f"reason: {sorted(missing)}"
    )


def test_the_electrode_layer_is_in_the_deposit_graph() -> None:
    """E2 by name: the specific regression the corpus found, pinned."""
    record_sets = _record_sets()
    ids = _deposit_node_ids(record_sets)
    for entity_type in ("electrode-spec", "electrode"):
        iri = _record_iri(record_sets[entity_type][0])
        assert iri in ids, f"{entity_type} record {iri} is missing from deposit.jsonld"


def test_electrode_nodes_carry_their_full_emission() -> None:
    """A promoted node must be the emitter's node, not a stub.

    The electrode specs are where the chemistry, polarity, processing route and
    design values live; promoting a bare ``@id`` would satisfy the coverage sweep
    while still losing what makes the layer worth publishing.
    """
    record_sets = _record_sets()
    doc = _deposit_graph(record_sets)
    by_id = {n["@id"]: n for n in doc["@graph"] if isinstance(n.get("@id"), str)}

    spec_node = by_id[_record_iri(record_sets["electrode-spec"][0])]
    types = spec_node["@type"] if isinstance(spec_node["@type"], list) else [spec_node["@type"]]
    assert "GraphiteElectrode" in types, types           # chemistry from the kind
    assert "NegativeElectrode" in types, types           # polarity derived from the kind
    assert spec_node["hasProperty"]["@type"][0] == "AreicCapacity"

    batch_node = by_id[_record_iri(record_sets["electrode"][0])]
    assert batch_node["schema:isVariantOf"] == {"@id": ELECTRODE_SPEC_IRI}


@pytest.mark.parametrize("entity_type", sorted(DEPOSIT_COVERAGE_EXEMPT))
def test_exemptions_are_still_real(entity_type: str) -> None:
    """Delete the entry when the type starts reaching the deposit on its own."""
    assert not _coverage()[entity_type], (
        f"{entity_type} now reaches the deposit graph; remove it from "
        "DEPOSIT_COVERAGE_EXEMPT"
    )


def test_exemptions_name_registered_types_and_carry_a_reason() -> None:
    registered = {kind.entity_type for kind in ENTITY_KINDS}
    unknown = sorted(set(DEPOSIT_COVERAGE_EXEMPT) - registered)
    assert not unknown, f"DEPOSIT_COVERAGE_EXEMPT names unregistered types: {unknown}"
    empty = [key for key, reason in DEPOSIT_COVERAGE_EXEMPT.items() if not reason.strip()]
    assert not empty, f"DEPOSIT_COVERAGE_EXEMPT entries without a reason: {empty}"


def test_standalone_kinds_are_registered_types() -> None:
    registered = {kind.entity_type for kind in ENTITY_KINDS}
    unknown = sorted(set(DEPOSIT_STANDALONE_KINDS) - registered)
    assert not unknown, f"DEPOSIT_STANDALONE_KINDS names unregistered types: {unknown}"
    overlap = sorted(set(DEPOSIT_STANDALONE_KINDS) & set(DEPOSIT_COVERAGE_EXEMPT))
    assert not overlap, f"types both promoted and exempt: {overlap}"
