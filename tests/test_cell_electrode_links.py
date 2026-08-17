"""A cell instance cites the electrodes physically built into it.

BIG-MAP/BattINFO#342 deferred this with "``cell_instance`` has no natural slot",
having looked at the fourteen fields the record then had. The maintainer's genome
review overruled that: *the electrode should be linked to material and cell*, and
a corpus of coin cells has *the same number of electrode instances as cell
instances* — one punched disc per cell. #345 then decided what such a link is
called, so the slot is no longer missing, it is named: ``working_electrode_id``
and ``counter_electrode_id``, the instance-level siblings of the cell spec's
``working_electrode_spec_id`` / ``counter_electrode_spec_id``.

The two levels say different things and neither replaces the other. The spec's
``*_spec_id`` names the DESIGN a cell of this type uses. The instance's
``*_electrode_id`` names the BATCH that went into this individual cell — which
coating run, which disc. A consumer that had only the spec link could not tell
two cells of one design apart, which is exactly the hop the corpus was asking a
reader to guess from a shared ``batch_id`` string.

Emission is a linked node, never an inline copy: the ``@id`` is the electrode
record's own IRI, so the electrode's chemistry, design link and as-built values
merge onto the node from the electrode record. The ``@type`` is the role the cell
assigned, which is the one thing the electrode record cannot know — the same disc
is a working electrode in one build and a counter electrode in another.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import Cell, CellSpec, ProvenanceInfo  # noqa: E402
from battinfo.electrodes import electrode_role_link, electrode_role_types  # noqa: E402
from battinfo.jsonld import cell_instance_to_jsonld, record_to_jsonld  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

CELL_IRI = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
SPEC_IRI = "https://w3id.org/battinfo/spec/eeee-ffff-gggg-hhhh"
WORKING_IRI = "https://w3id.org/battinfo/electrode/1111-2222-3333-4444"
COUNTER_IRI = "https://w3id.org/battinfo/electrode/5555-6666-7777-8888"


def _cell(**overrides) -> Cell:
    fields = {
        "id": CELL_IRI,
        "name": "LNMO-AQ-1 cell 03",
        "cell_spec_id": SPEC_IRI,
        "serial_number": "cell-03",
        "working_electrode_id": WORKING_IRI,
        "counter_electrode_id": COUNTER_IRI,
        "source": ProvenanceInfo(type="lab"),
    }
    fields.update(overrides)
    return Cell(**fields)


def _spec_draft(**overrides) -> dict:
    """The authoring dict ``ws.add("cell", spec=...)`` accepts."""
    fields = {
        "manufacturer": "Lab", "model": "LNMO-AQ", "format": "coin", "chemistry": "li-ion",
    }
    fields.update(overrides)
    return fields


def _spec(**overrides) -> CellSpec:
    fields = {
        "id": SPEC_IRI, "name": "LNMO half cell", "manufacturer": "Lab",
        "model": "LNMO-AQ", "format": "coin", "chemistry": "li-ion",
        "source": ProvenanceInfo(type="manual"),
    }
    fields.update(overrides)
    return CellSpec(**fields)


# ── The record ────────────────────────────────────────────────────────────────

def test_the_link_round_trips_through_the_record() -> None:
    """Author -> record -> model -> record, with the IRIs intact at every hop.

    The #344 defect family (a field in the schema that no model can carry, or a
    model field the record drops) is what this checks for the new pair.
    """
    record = _cell().to_record()
    body = record["cell_instance"]
    assert body["working_electrode_id"] == WORKING_IRI
    assert body["counter_electrode_id"] == COUNTER_IRI

    reloaded = Cell.from_record(record)
    assert reloaded.working_electrode_id == WORKING_IRI
    assert reloaded.counter_electrode_id == COUNTER_IRI
    assert reloaded.to_record()["cell_instance"] == body


def test_the_record_validates_against_the_schema() -> None:
    report = validate_record_report(_cell().to_record())
    assert list(report.errors) == [], report.errors


def test_the_fields_are_optional() -> None:
    """A cell that does not know its electrodes is still a valid cell.

    Most of the world buys cells sealed. The link is for the lab that built one.
    """
    record = Cell(
        id=CELL_IRI, cell_spec_id=SPEC_IRI, name="sealed", source=ProvenanceInfo(type="lab")
    ).to_record()
    assert "working_electrode_id" not in record["cell_instance"]
    assert list(validate_record_report(record).errors) == []


@pytest.mark.parametrize("field", ["working_electrode_id", "counter_electrode_id"])
def test_the_schema_refuses_an_iri_from_another_namespace(field: str) -> None:
    """An ``electrode/`` IRI, not an ``electrode-spec``.

    The design link already exists at the spec level; pointing this field at a
    spec would silently duplicate it and lose the batch, so the pattern is
    segment-scoped and the mistake is a validation error rather than a quiet
    downgrade.
    """
    record = _cell().to_record()
    record["cell_instance"][field] = "https://w3id.org/battinfo/spec/1111-2222-3333-4444"
    codes = {issue.code for issue in validate_record_report(record).errors}
    assert any(code.startswith("schema.") for code in codes), codes


# ── Emission ──────────────────────────────────────────────────────────────────

def test_the_cell_emits_its_electrodes_as_role_typed_linked_nodes() -> None:
    node = record_to_jsonld(_cell().to_record(), "cell-instance")

    assert node["hasWorkingElectrode"] == {"@id": WORKING_IRI, "@type": "WorkingElectrode"}
    assert node["hasCounterElectrode"] == {"@id": COUNTER_IRI, "@type": "CounterElectrode"}
    # A linked node, not an inline copy: the cell states the role and nothing
    # else about the electrode, so there is no second place for its chemistry to
    # drift away from the electrode record's.
    assert set(node["hasWorkingElectrode"]) == {"@id", "@type"}


def test_a_half_cell_counter_electrode_is_also_the_reference() -> None:
    """The #345 rule, applied at the instance level.

    An instance states no configuration of its own, so it reads its spec — the
    same inheritance that gives an instance its physical type and its
    manufacturer. A half cell has no third electrode, so its counter electrode IS
    its reference: a second class on the one node, never a second relation.
    """
    node = cell_instance_to_jsonld(
        _cell().to_record(), cell_spec={"cell_configuration": "half_cell"}
    )
    assert node["hasWorkingElectrode"]["@type"] == "WorkingElectrode"
    assert node["hasCounterElectrode"]["@type"] == ["CounterElectrode", "ReferenceElectrode"]


def test_reference_electrode_marker_reads_as_a_half_cell() -> None:
    """``reference_electrode`` is the schema's half-cell marker for older records."""
    node = cell_instance_to_jsonld(
        _cell().to_record(), cell_spec={"reference_electrode": "Li metal"}
    )
    assert node["hasCounterElectrode"]["@type"] == ["CounterElectrode", "ReferenceElectrode"]


def test_a_three_electrode_cell_counter_is_not_the_reference() -> None:
    """Its reference is a third electrode the cell spec names separately."""
    node = cell_instance_to_jsonld(
        _cell().to_record(), cell_spec={"cell_configuration": "three_electrode_cell"}
    )
    assert node["hasCounterElectrode"]["@type"] == "CounterElectrode"


def test_without_a_spec_the_counter_electrode_claims_only_its_own_role() -> None:
    """Silence about the configuration is not evidence of a half cell.

    ``record_to_jsonld`` transforms one record and cannot resolve the spec, so it
    states the role it was told and stops. Inventing the reference role from an
    unresolved spec would be a claim the document does not support.
    """
    node = record_to_jsonld(_cell().to_record(), "cell-instance")
    assert node["hasCounterElectrode"]["@type"] == "CounterElectrode"


def test_the_emitted_terms_resolve_offline() -> None:
    """The inline context carries the role terms the document uses.

    ``records.context.json`` is generated from the schema's ``slot_uri``
    declarations and holds no EMMO class terms, so a cell-instance document that
    names a role has to bring them along or a reader gets a dangling term.
    """
    doc = record_to_jsonld(_cell().to_record(), "cell-instance", context="inline")
    context = doc["@context"]
    for term in ("hasWorkingElectrode", "hasCounterElectrode", "WorkingElectrode",
                 "CounterElectrode", "ReferenceElectrode"):
        assert term in context, term


def test_a_cell_without_electrode_links_keeps_the_plain_context() -> None:
    """No role terms are added to a document that names no role."""
    plain = record_to_jsonld(
        Cell(id=CELL_IRI, cell_spec_id=SPEC_IRI, source=ProvenanceInfo(type="lab")).to_record(),
        "cell-instance", context="inline",
    )
    assert "hasWorkingElectrode" not in plain["@context"]


def test_url_and_inline_contexts_agree_on_the_role_terms() -> None:
    """The hosted v1 context already serves them, so both forms expand alike."""
    v1 = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json")
        .read_text(encoding="utf-8")
    )["@context"]
    inline = record_to_jsonld(_cell().to_record(), "cell-instance", context="inline")["@context"]
    for term in ("hasWorkingElectrode", "hasCounterElectrode", "WorkingElectrode",
                 "CounterElectrode", "ReferenceElectrode"):
        assert v1[term] == inline[term], term


# ── The one implementation of the role rule ───────────────────────────────────

@pytest.mark.parametrize(
    "configuration,expected",
    [
        (None, ["CounterElectrode"]),
        ("full_cell", ["CounterElectrode"]),
        ("half_cell", ["CounterElectrode", "ReferenceElectrode"]),
        ("half-cell", ["CounterElectrode", "ReferenceElectrode"]),
        ("Half Cell", ["CounterElectrode", "ReferenceElectrode"]),
        ("three_electrode_cell", ["CounterElectrode"]),
    ],
)
def test_counter_role_types_by_configuration(configuration, expected) -> None:
    assert electrode_role_types("counter", configuration) == expected


def test_working_role_never_depends_on_the_configuration() -> None:
    for configuration in (None, "full_cell", "half_cell", "three_electrode_cell"):
        assert electrode_role_types("working", configuration) == ["WorkingElectrode"]


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown electrode role"):
        electrode_role_types("auxiliary")


def test_the_cell_spec_holder_emitter_uses_the_shared_rule() -> None:
    """The spec holder and the instance link cannot disagree about a half cell.

    #345 put the counter-is-reference rule inside the cell-spec holder loop. If a
    second copy were written for the instance, a half cell could type its counter
    electrode one way on the spec and another on the cell. Both now call
    ``electrode_role_types``; this pins the two answers to each other.
    """
    from battinfo.bundle import Electrode

    spec = _spec(
        cell_configuration="half_cell",
        working_electrode=Electrode(
            coating={"component": {"active_material": [{"name": "LNMO"}]}}
        ),
        counter_electrode=Electrode(
            coating={"component": {"active_material": [{"name": "Lithium"}]}}
        ),
    )
    holder = record_to_jsonld(spec.to_record(), "cell-spec")["hasCounterElectrode"]
    link = electrode_role_link("counter", COUNTER_IRI, "half_cell")
    assert holder["@type"] == link["@type"]


# ── Reference resolution ──────────────────────────────────────────────────────

def _save_corpus(root: Path, *, cell_overrides: dict | None = None) -> None:
    from battinfo.api import create_electrode, create_electrode_spec

    (root / "cell-spec").mkdir(parents=True, exist_ok=True)
    (root / "cell-instance").mkdir(parents=True, exist_ok=True)
    (root / "electrode-spec").mkdir(parents=True, exist_ok=True)
    (root / "electrode").mkdir(parents=True, exist_ok=True)

    electrode_spec = create_electrode_spec(
        validate=False, uid="9999-8888-7777-6666", name="LNMO cathode", kind="lnmo",
    )
    design_iri = electrode_spec["electrode_spec"]["id"]
    (root / "electrode-spec" / "electrode-spec-9999-8888-7777-6666.json").write_text(
        json.dumps(electrode_spec), encoding="utf-8"
    )
    for uid, name in ((WORKING_IRI, "LNMO disc"), (COUNTER_IRI, "Li disc")):
        tail = uid.rsplit("/", 1)[-1]
        record = create_electrode(
            validate=False, uid=tail, name=name,
            electrode_spec_id=design_iri, batch=name,
        )
        record["electrode"]["id"] = uid
        (root / "electrode" / f"electrode-{tail}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    spec_record = _spec(cell_configuration="half_cell").to_record()
    (root / "cell-spec" / "cell-spec-eeee-ffff-gggg-hhhh.json").write_text(
        json.dumps(spec_record), encoding="utf-8"
    )
    cell_record = _cell().to_record()
    if cell_overrides:
        cell_record["cell_instance"].update(cell_overrides)
    (root / "cell-instance" / "cell-aaaa-bbbb-cccc-dddd.json").write_text(
        json.dumps(cell_record), encoding="utf-8"
    )


def test_a_resolvable_electrode_reference_passes_the_save_gate(tmp_path: Path) -> None:
    _save_corpus(tmp_path)
    record = json.loads(
        (tmp_path / "cell-instance" / "cell-aaaa-bbbb-cccc-dddd.json").read_text(encoding="utf-8")
    )
    report = validate_record_report(record, source_root=tmp_path)
    assert [issue for issue in report.errors if "electrode" in issue.message] == []


def test_a_missing_electrode_is_a_reference_error(tmp_path: Path) -> None:
    _save_corpus(
        tmp_path,
        cell_overrides={
            "working_electrode_id": "https://w3id.org/battinfo/electrode/0000-0000-0000-0000"
        },
    )
    record = json.loads(
        (tmp_path / "cell-instance" / "cell-aaaa-bbbb-cccc-dddd.json").read_text(encoding="utf-8")
    )
    report = validate_record_report(record, source_root=tmp_path)
    codes = {issue.code for issue in report.errors}
    paths = {issue.path for issue in report.errors}
    assert "reference.missing" in codes
    assert "cell_instance.working_electrode_id" in paths


# ── The deposit graph ─────────────────────────────────────────────────────────

def _deposit(record_sets: dict[str, list[dict]]) -> dict:
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="electrode links",
    )


def test_the_deposit_graph_carries_the_link_and_reads_the_spec() -> None:
    """The published artifact is where the instance genuinely reads its spec.

    Every record is in hand here, so the half-cell rule applies: the counter
    electrode node carries both role classes. This is the path the corpus
    publishes through, so it is the one that has to be right.
    """
    graph = _deposit({
        "cell-spec": [_spec(cell_configuration="half_cell").to_record()],
        "cell-instance": [_cell().to_record()],
    })["@graph"]
    cell_node = next(node for node in graph if node.get("@id") == CELL_IRI)

    assert cell_node["hasWorkingElectrode"] == {"@id": WORKING_IRI, "@type": "WorkingElectrode"}
    assert cell_node["hasCounterElectrode"] == {
        "@id": COUNTER_IRI, "@type": ["CounterElectrode", "ReferenceElectrode"],
    }


def test_a_full_cell_in_the_deposit_graph_keeps_its_counter_role_alone() -> None:
    graph = _deposit({
        "cell-spec": [_spec(cell_configuration="full_cell").to_record()],
        "cell-instance": [_cell().to_record()],
    })["@graph"]
    cell_node = next(node for node in graph if node.get("@id") == CELL_IRI)
    assert cell_node["hasCounterElectrode"]["@type"] == "CounterElectrode"


def test_the_link_resolves_to_a_described_node_in_the_same_deposit() -> None:
    """A link that points nowhere is not a link.

    #344 promoted electrode records to first-class deposit nodes. That is what
    makes this reference land on a node with the electrode's own chemistry and
    design link rather than on a bare IRI.
    """
    from battinfo.api import create_electrode, create_electrode_spec

    electrode_spec = create_electrode_spec(
        validate=False, uid="9999-8888-7777-6666", name="LNMO cathode", kind="lnmo",
    )
    electrode = create_electrode(
        validate=False, uid=WORKING_IRI.rsplit("/", 1)[-1], name="LNMO disc",
        electrode_spec_id=electrode_spec["electrode_spec"]["id"], batch="LNMO-AQ-1",
    )
    electrode["electrode"]["id"] = WORKING_IRI

    graph = _deposit({
        "cell-spec": [_spec(cell_configuration="half_cell").to_record()],
        "cell-instance": [_cell().to_record()],
        "electrode-spec": [electrode_spec],
        "electrode": [electrode],
    })["@graph"]

    cell_node = next(node for node in graph if node.get("@id") == CELL_IRI)
    electrode_node = next(node for node in graph if node.get("@id") == WORKING_IRI)
    assert cell_node["hasWorkingElectrode"]["@id"] == electrode_node["@id"]
    # The electrode keeps its own typing; the cell contributes only the role, so
    # the merged node carries both without either emitter restating the other.
    assert "WorkingElectrode" not in json.dumps(electrode_node.get("@type"))


# ── Authoring ─────────────────────────────────────────────────────────────────

def test_ws_add_applies_one_electrode_to_a_whole_batch(tmp_path: Path) -> None:
    """Cells punched from one coated web share their electrode batch."""
    ws = AuthoringWorkspace(tmp_path)
    spec = _spec_draft(cell_configuration="half_cell")
    cells = ws.add(
        "cell", spec=spec, serial_numbers=["c-1", "c-2", "c-3"],
        working_electrode_id=WORKING_IRI, counter_electrode_id=COUNTER_IRI,
    )
    assert len(cells) == 3
    assert {cell.working_electrode_id for cell in cells} == {WORKING_IRI}
    assert {cell.counter_electrode_id for cell in cells} == {COUNTER_IRI}


def test_ws_add_assigns_one_electrode_per_cell(tmp_path: Path) -> None:
    """The maintainer's shape: as many electrode instances as cell instances."""
    ws = AuthoringWorkspace(tmp_path)
    spec = _spec_draft(cell_configuration="half_cell")
    discs = [f"https://w3id.org/battinfo/electrode/000{n}-2222-3333-4444" for n in (1, 2, 3)]
    cells = ws.add(
        "cell", spec=spec, serial_numbers=["c-1", "c-2", "c-3"], working_electrode_id=discs,
    )
    assert [cell.working_electrode_id for cell in cells] == discs


def test_a_mismatched_electrode_list_is_refused(tmp_path: Path) -> None:
    """Zipping short would attach the wrong physical disc to a physical cell."""
    ws = AuthoringWorkspace(tmp_path)
    spec = _spec_draft()
    with pytest.raises(ValueError, match="working_electrode_id list must match"):
        ws.add(
            "cell", spec=spec, serial_numbers=["c-1", "c-2", "c-3"],
            working_electrode_id=[WORKING_IRI],
        )


def test_saved_cells_reload_with_their_electrodes(tmp_path: Path) -> None:
    """A cell read back off disk still knows what it was built from."""
    ws = AuthoringWorkspace(tmp_path)
    spec = _spec_draft()
    ws.add("cell", spec=spec, serial_numbers=["c-1"], working_electrode_id=WORKING_IRI)
    ws.save(validation_policy="ingest")

    reopened = AuthoringWorkspace(tmp_path)
    assert reopened.reload_cells() == 1
    reloaded = reopened._cells_by_short_id["c-1"]
    assert reloaded.working_electrode_id == WORKING_IRI


def test_the_electrode_link_is_not_part_of_the_cell_identity(tmp_path: Path) -> None:
    """Two cells from one batch are still two cells, and the same cell re-saved
    with its electrode named is still the same cell.

    The identity seed is (spec, serial/batch/name). Folding the electrode into it
    would re-mint every published IRI the day a lab filled the field in.
    """
    from battinfo.entities import cell_instance_identity_seed

    seed = cell_instance_identity_seed(cell_spec_id=SPEC_IRI, serial_number="cell-03")
    assert WORKING_IRI not in seed
    assert COUNTER_IRI not in seed
