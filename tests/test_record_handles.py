"""Record handles end to end: schema, semantic nudge, JSON-LD, authoring.

A handle is an optional display slug on the body of every record type. The
schema enforces its grammar, a semantic warning nudges its layout toward the
naming convention, the JSON-LD carries it as one more schema:identifier, and
every authoring surface that takes ``name=`` takes ``handle=``. Renaming must
not move an IRI, so the identity pins (test ``iri=``/``uid=``/``dataset_iris=``,
a test-spec draft's ``id``, an explicit ``Dataset(id=...)``) are covered here
too.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import rdflib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo._util import is_dataset_series  # noqa: E402
from battinfo.api import (  # noqa: E402
    create_component_instance,
    create_component_spec,
    create_equipment_spec,
    create_material_spec,
    create_organization,
    create_parameter_set,
    save_dataset,
)
from battinfo.bundle import Cell, Dataset, ProvenanceInfo  # noqa: E402
from battinfo.entities import ENTITY_KINDS, kind_for_doc  # noqa: E402
from battinfo.jsonld import HANDLE_PROPERTY_ID, record_to_jsonld  # noqa: E402
from battinfo.naming import handle_for  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
CONTEXTS = ROOT / "src" / "battinfo" / "data" / "context"
SPEC_UID = "aaaa-bbbb-cccc-0001"
SPEC_PIN = f"https://w3id.org/battinfo/spec/{SPEC_UID}"
TEST_PIN = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-0002"
DATASET_PIN = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-0003"
SERIES_PIN = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-0004"
MEMBER_PIN = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-0005"
CELL_IRI = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-0006"


def _example_per_kind() -> dict[str, dict]:
    """One shipped example record per entity kind (every kind has one)."""
    found: dict[str, dict] = {}
    for path in sorted(EXAMPLES.rglob("*.json")):
        if "profiles" in path.parts:
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        kind = kind_for_doc(doc) if isinstance(doc, dict) else None
        if kind is not None and kind.entity_type not in found:
            found[kind.entity_type] = doc
    return found


EXAMPLE_BY_KIND = _example_per_kind()
KIND_IDS = [kind.entity_type for kind in ENTITY_KINDS]


def _jsonld_type(entity_type: str) -> str:
    """record_to_jsonld names the physical cell 'cell-instance'."""
    return "cell-instance" if entity_type == "cell" else entity_type


def _conventional_handle(entity_type: str, body: dict) -> str:
    if entity_type == "dataset" and is_dataset_series(body.get("additional_type")):
        return handle_for("collection", group="examples")
    return handle_for(entity_type, group="examples", sample="probe")


def _with_handle(entity_type: str, handle: str) -> dict:
    record = copy.deepcopy(EXAMPLE_BY_KIND[entity_type])
    key = next(k.record_key for k in ENTITY_KINDS if k.entity_type == entity_type)
    record[key]["handle"] = handle
    return record


def _issue_keys(record: dict) -> set[tuple[str, str, str]]:
    report = validate_record_report(record, policy="strict")
    return {(issue.code, issue.severity, issue.path) for issue in report.issues}


# ── Schema ────────────────────────────────────────────────────────────────────


def test_every_entity_kind_has_an_example_to_sweep() -> None:
    assert set(EXAMPLE_BY_KIND) == set(KIND_IDS)


@pytest.mark.parametrize("entity_type", KIND_IDS)
def test_a_conventional_handle_validates_on_every_record_type(entity_type: str) -> None:
    key = next(k.record_key for k in ENTITY_KINDS if k.entity_type == entity_type)
    body = EXAMPLE_BY_KIND[entity_type][key]
    handled = _with_handle(entity_type, _conventional_handle(entity_type, body))
    # The handle adds no issue at all (schema, semantic, SHACL) under strict.
    assert _issue_keys(handled) == _issue_keys(EXAMPLE_BY_KIND[entity_type])


@pytest.mark.parametrize("entity_type", KIND_IDS)
@pytest.mark.parametrize("bad", ["Flores OCV", "flores_ocv/cell", "flores--ocv", "flores/", "flörés-cell"])
def test_a_handle_off_the_grammar_is_a_schema_error(entity_type: str, bad: str) -> None:
    key = next(k.record_key for k in ENTITY_KINDS if k.entity_type == entity_type)
    report = validate_record_report(_with_handle(entity_type, bad), policy="default")
    errors = [issue for issue in report.errors if issue.path == f"{key}.handle"]
    assert errors and errors[0].code == "schema.pattern"
    assert "handle_for()" in errors[0].message


def test_a_handle_over_the_length_limit_is_a_schema_error() -> None:
    long_handle = "flores-ocv/" + "a" * 120 + "-cell"
    report = validate_record_report(_with_handle("cell", long_handle), policy="default")
    assert any(
        issue.code == "schema.maxLength" and issue.path == "cell_instance.handle" for issue in report.errors
    )


# ── Semantic nudge ────────────────────────────────────────────────────────────


def _handle_warnings(record: dict, policy: str = "strict") -> list:
    report = validate_record_report(record, policy=policy)
    return [issue for issue in report.issues if issue.code == "semantic.handle_kind_word_expected"]


@pytest.mark.parametrize(("entity_type", "handle"), [
    ("cell", "flores-ocv/graphite-aq-1-063b77-cell-spec"),
    ("cell-spec", "flores-ocv/graphite-aq-1-cell"),
    ("material", "flores-ocv/graphite-material"),
    ("test-protocol", "flores-ocv/gitt-protocol"),
    ("electrode", "flores-ocv/graphite-aq-1-063b77"),
])
def test_a_handle_without_its_kind_word_gets_a_warning(entity_type: str, handle: str) -> None:
    warnings = _handle_warnings(_with_handle(entity_type, handle))
    assert len(warnings) == 1
    # A nudge, never a blocker: a warning even under the strict policy.
    assert warnings[0].severity == "warning"
    assert warnings[0].resource_type == entity_type
    assert "handle_for()" in warnings[0].message


def test_the_kind_word_may_be_the_whole_last_segment() -> None:
    assert not _handle_warnings(_with_handle("cell", "flores-ocv/cell"))
    assert not _handle_warnings(_with_handle("material", "material-lot"))


def test_a_collection_carries_no_kind_word_but_a_plain_dataset_does() -> None:
    series = Dataset(
        id=SERIES_PIN, name="Half-cell OCV collection", handle="flores-ocv",
        access_url="https://doi.org/10.5281/zenodo.20086298",
        additional_type=["DatasetSeries"],
        source=ProvenanceInfo(type="catalog", retrieved_at=1755648000),
    ).to_record()
    assert not _handle_warnings(series)
    plain = copy.deepcopy(series)
    plain["dataset"].pop("additional_type")
    assert len(_handle_warnings(plain)) == 1


# ── JSON-LD ───────────────────────────────────────────────────────────────────


def _handle_identifiers(node: dict) -> list[dict]:
    values = node.get("schema:identifier")
    values = values if isinstance(values, list) else [values]
    return [v for v in values if isinstance(v, dict) and v.get("schema:propertyID") == HANDLE_PROPERTY_ID]


@pytest.mark.parametrize("entity_type", KIND_IDS)
def test_every_record_type_emits_its_handle_as_an_identifier(entity_type: str) -> None:
    handle = handle_for(entity_type, group="examples", sample="probe")
    record = _with_handle(entity_type, handle)
    for mode in ("url", "inline"):
        node = record_to_jsonld(record, _jsonld_type(entity_type), context=mode)
        assert _handle_identifiers(node) == [{
            "@type": "schema:PropertyValue",
            "schema:propertyID": HANDLE_PROPERTY_ID,
            "schema:value": handle,
        }]


@pytest.mark.parametrize("entity_type", KIND_IDS)
def test_no_handle_means_no_handle_identifier(entity_type: str) -> None:
    node = record_to_jsonld(EXAMPLE_BY_KIND[entity_type], _jsonld_type(entity_type), context="inline")
    assert not _handle_identifiers(node)


def test_the_handle_joins_existing_identifiers_instead_of_replacing_them() -> None:
    record = _with_handle("cell", "flores-ocv/graphite-aq-1-063b77-cell")
    record["cell_instance"]["batch_id"] = "B-7"
    node = record_to_jsonld(record, "cell-instance", context="inline")
    ids = node["schema:identifier"]
    assert isinstance(ids, list) and len(ids) == 2
    assert ids[0]["schema:propertyID"] == "batch_id"
    assert ids[1]["schema:value"] == "flores-ocv/graphite-aq-1-063b77-cell"


_LOCAL_CONTEXTS = {
    "https://w3id.org/battinfo/context/records/v1.json": CONTEXTS / "records.context.v1.json",
    "https://w3id.org/emmo/domain/battery/context": CONTEXTS / "domain-battery.context.json",
}


def _graph(doc: dict) -> rdflib.Graph:
    """Parse offline: every context URL is swapped for its vendored copy."""
    doc = dict(doc)
    ctx = doc.get("@context")
    entries = ctx if isinstance(ctx, list) else [ctx]
    resolved = []
    for entry in entries:
        if isinstance(entry, str):
            resolved.append(json.loads(_LOCAL_CONTEXTS[entry].read_text(encoding="utf-8"))["@context"])
        else:
            resolved.append(entry)
    doc["@context"] = resolved if isinstance(ctx, list) else resolved[0]
    graph = rdflib.Graph()
    graph.parse(data=json.dumps(doc), format="json-ld", base="https://battinfo.invalid/base/")
    return graph


@pytest.mark.parametrize("entity_type", ["cell-spec", "cell", "dataset", "material-spec", "organization"])
def test_inline_and_url_emission_agree_on_the_handle_triples(entity_type: str) -> None:
    handle = handle_for(entity_type, group="examples", sample="probe")
    record = _with_handle(entity_type, handle)
    inline = _graph(record_to_jsonld(record, _jsonld_type(entity_type), context="inline"))
    url = _graph(record_to_jsonld(record, _jsonld_type(entity_type), context="url"))
    # Whole-graph isomorphism for every record is test_graph_equivalence's job;
    # here the handle must expand the same way in both modes.
    assert len(inline) == len(url)
    schema = rdflib.Namespace("https://schema.org/")
    subject = rdflib.URIRef(record[next(k.record_key for k in ENTITY_KINDS if k.entity_type == entity_type)]["id"])
    for graph in (inline, url):
        values = {
            str(value)
            for node in graph.objects(subject, schema.identifier)
            if (node, schema.propertyID, rdflib.Literal(HANDLE_PROPERTY_ID)) in graph
            for value in graph.objects(node, schema.value)
        }
        assert values == {handle}


# ── Builders and record models ────────────────────────────────────────────────


def test_api_builders_place_the_handle_next_to_the_name() -> None:
    handle = "flores-ocv/graphite-material-spec"
    records = [
        (create_material_spec(name="Graphite", kind="graphite", handle=handle), "material_spec"),
        (create_equipment_spec(uid=SPEC_UID, name="Cycler", handle="lab/cycler-equipment-spec"), "equipment_spec"),
        (create_organization(name="SINTEF", handle="sintef-organization"), "organization"),
        (create_component_spec("separator", uid=SPEC_UID, name="PP", handle="lab/pp-separator-spec"),
         "separator_spec"),
        (create_component_instance("separator", uid=SPEC_UID, spec_id=SPEC_PIN, name="PP roll 1",
                                   handle="lab/pp-1-separator"), "separator"),
        (create_parameter_set(name="Chen 2020 - graphite", material_kind="graphite",
                              handle="chen-2020/graphite-parameter-set",
                              claims=[{"parameter": "density", "quantity": {"value": 2.26, "unit": "g/cm3"},
                                       "provenance_class": "literature"}]), "parameter_set"),
    ]
    for record, key in records:
        body_keys = list(record[key])
        assert body_keys[body_keys.index("name") + 1] == "handle", key


def test_record_models_round_trip_the_handle() -> None:
    cell = Cell(id=CELL_IRI, cell_spec_id=SPEC_PIN, name="Graphite AQ-1 cell 063b77",
                handle="flores-ocv/graphite-aq-1-063b77-cell")
    record = cell.to_record()
    assert record["cell_instance"]["handle"] == "flores-ocv/graphite-aq-1-063b77-cell"
    assert Cell.from_record(record).to_record() == record
    no_handle = Cell(id=CELL_IRI, cell_spec_id=SPEC_PIN, name="x").to_record()
    assert "handle" not in no_handle["cell_instance"]


# ── Workspace authoring ───────────────────────────────────────────────────────


def _records(root: Path, folder: str) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / ".battinfo" / "records" / folder).glob("*.json"))
    ]


def _cell_spec(ws: AuthoringWorkspace, tmp_path: Path, handle: str | None = None):
    draft = {"manufacturer": "Flores Lab", "model": "Gr half cell", "format": "coin", "chemistry": "li-ion"}
    if handle:
        draft["handle"] = handle
    path = tmp_path / "gr.cell-spec.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    return ws.load(path)


def _gitt_session(tmp_path: Path, *, name: str, **test_kwargs) -> AuthoringWorkspace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _cell_spec(ws, tmp_path, handle="flores-ocv/graphite-aq-1-cell-spec")
    ws.add("cell", spec=spec, names=["063b77"], handles=["flores-ocv/graphite-aq-1-063b77-cell"])
    (tmp_path / "063b77.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    ws.add("test", type="gitt", cell="063b77", data="063b77.csv", name=name, **test_kwargs)
    ws.save()
    return ws


def test_ws_add_carries_handles_into_saved_records(tmp_path: Path) -> None:
    _gitt_session(tmp_path, name="Graphite AQ-1 cell 063b77 GITT test",
                  handle="flores-ocv/graphite-aq-1-063b77-gitt-test")
    (spec,) = _records(tmp_path, "cell-spec")
    (cell,) = _records(tmp_path, "cell-instance")
    (test,) = _records(tmp_path, "test")
    assert spec["cell_spec"]["handle"] == "flores-ocv/graphite-aq-1-cell-spec"
    assert cell["cell_instance"]["handle"] == "flores-ocv/graphite-aq-1-063b77-cell"
    assert test["test"]["handle"] == "flores-ocv/graphite-aq-1-063b77-gitt-test"
    assert Cell.from_record(cell).handle == "flores-ocv/graphite-aq-1-063b77-cell"


def test_ws_add_never_invents_a_handle(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _cell_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    ws.add("material_spec", name="Graphite", kind="graphite")
    ws.save()
    assert "handle" not in _records(tmp_path, "cell-instance")[0]["cell_instance"]
    assert "handle" not in _records(tmp_path, "material-spec")[0]["material_spec"]


def test_ws_add_side_records_and_equipment_accept_handle(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("material_spec", name="Graphite", kind="graphite", handle="flores-ocv/graphite-material-spec")
    ws.add("material", spec="Graphite", lot="L1", handle="flores-ocv/graphite-material-lot")
    ws.save()
    assert _records(tmp_path, "material-spec")[0]["material_spec"]["handle"] == "flores-ocv/graphite-material-spec"
    assert _records(tmp_path, "material")[0]["material"]["handle"] == "flores-ocv/graphite-material-lot"

    spec = create_equipment_spec(uid=SPEC_UID, name="Cycler", channel_count=1)
    ws.add("equipment", spec=spec, serial_number="SN1", name="Cycler 1", handle="lab/cycler-1-equipment")
    assert _records(tmp_path, "equipment")[0]["equipment"]["handle"] == "lab/cycler-1-equipment"


def test_cell_handles_must_parallel_the_cells(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _cell_spec(ws, tmp_path)
    with pytest.raises(ValueError, match="handles must match"):
        ws.add("cell", spec=spec, names=["c1", "c2"], handles=["a-cell"])


def test_a_new_test_title_moves_the_iri_unless_it_is_pinned(tmp_path: Path) -> None:
    first = _gitt_session(tmp_path / "a", name="063b77 gitt")
    renamed = _gitt_session(tmp_path / "b", name="Graphite AQ-1 cell 063b77 GITT test")
    assert first._ws.tests[0].id != renamed._ws.tests[0].id  # the seed includes the name

    original = _records(tmp_path / "a", "test")[0]["test"]["id"]
    original_dataset = _records(tmp_path / "a", "dataset")[0]["dataset"]["id"]
    _gitt_session(tmp_path / "c", name="Graphite AQ-1 cell 063b77 GITT test",
                  iri=original, dataset_iris=[original_dataset])
    (test,) = _records(tmp_path / "c", "test")
    (dataset,) = _records(tmp_path / "c", "dataset")
    assert test["test"]["id"] == original
    assert test["test"]["name"] == "Graphite AQ-1 cell 063b77 GITT test"
    assert test["test"]["dataset_ids"] == [original_dataset]
    assert dataset["dataset"]["id"] == original_dataset
    assert original in dataset["dataset"]["about"]


def test_a_test_can_be_pinned_by_uid(tmp_path: Path) -> None:
    _gitt_session(tmp_path, name="any title", uid="AAAA-BBBB-CCCC-0002", dataset_iris=[DATASET_PIN])
    assert _records(tmp_path, "test")[0]["test"]["id"] == TEST_PIN
    assert _records(tmp_path, "dataset")[0]["dataset"]["id"] == DATASET_PIN


@pytest.mark.parametrize(("pins", "message"), [
    ({"iri": "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-0002"}, "not a test IRI"),
    ({"iri": TEST_PIN, "uid": "aaaa-bbbb-cccc-0009"}, "different tests"),
    ({"uid": "not-a-uid"}, "UID must be"),
    ({"dataset_iris": [DATASET_PIN, MEMBER_PIN]}, "number of data files"),
    ({"dataset_iris": ["https://w3id.org/battinfo/test/aaaa-bbbb-cccc-0002"]}, "dataset IRIs"),
])
def test_bad_test_pins_fail_before_anything_is_created(tmp_path: Path, pins: dict, message: str) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _cell_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    (tmp_path / "c1.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        ws.add("test", type="gitt", cell="c1", data="c1.csv", **pins)
    assert not ws._ws.tests and not ws._ws.datasets


def test_a_pin_cannot_name_two_tests(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _cell_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    ws.add("test", type="gitt", cell="c1", iri=TEST_PIN)
    with pytest.raises(ValueError, match="already used"):
        ws.add("test", type="eis", cell="c1", iri=TEST_PIN)


def test_one_test_options_are_refused_in_batch_mode(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="explicit"):
        ws.add("test", type="gitt", datasets="*.csv", handle="lab/gitt-test")


def test_a_test_spec_draft_keeps_its_explicit_id_and_handle(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    draft = tmp_path / "gitt.test-spec.json"
    draft.write_text(json.dumps({
        "name": "GITT test spec", "type": "gitt", "id": SPEC_PIN,
        "handle": "flores-ocv/gitt-test-spec",
    }), encoding="utf-8")
    test_spec = ws.load(draft)
    spec = _cell_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    ws.add("test", spec=test_spec, cell="c1")
    ws.save()
    (saved,) = _records(tmp_path, "test-protocol")
    assert saved["test_spec"]["id"] == SPEC_PIN
    assert saved["test_spec"]["handle"] == "flores-ocv/gitt-test-spec"
    assert _records(tmp_path, "test")[0]["test"]["protocol_id"] == SPEC_PIN


def test_a_test_spec_draft_may_pin_by_uid_and_rejects_a_foreign_id(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    draft = tmp_path / "gitt.test-spec.json"
    draft.write_text(json.dumps({"name": "GITT", "type": "gitt", "uid": SPEC_UID}), encoding="utf-8")
    assert ws.load(draft).id == SPEC_PIN
    draft.write_text(json.dumps({"name": "GITT", "type": "gitt", "id": TEST_PIN}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a spec IRI"):
        ws.load(draft)


@pytest.mark.parametrize(("iri", "extra"), [
    (SERIES_PIN, {"additional_type": ["DatasetSeries"], "handle": "flores-ocv"}),
    (MEMBER_PIN, {"series_id": SERIES_PIN, "cell_instance_id": CELL_IRI,
                  "handle": "flores-ocv/graphite-aq-1-063b77-gitt-dataset"}),
])
def test_save_dataset_keeps_an_explicit_id_whatever_the_name(tmp_path: Path, iri: str, extra: dict) -> None:
    """A collection's IRI otherwise seeds from access_url + name; an explicit id wins."""
    for name in ("Old title", "Graphite AQ-1 cell 063b77 GITT dataset"):
        dataset = Dataset(
            id=iri, name=name, access_url="https://doi.org/10.5281/zenodo.20086298",
            source=ProvenanceInfo(type="catalog", retrieved_at=1755648000), **extra,
        )
        result = save_dataset(dataset, source_root=tmp_path, mode="upsert",
                              resolve_references=False, build_jsonld=False, build_html=False)
        assert result["id"] == iri
    (saved,) = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "dataset").glob("*.json")]
    assert saved["dataset"]["id"] == iri
    assert saved["dataset"]["name"] == "Graphite AQ-1 cell 063b77 GITT dataset"
    assert saved["dataset"]["handle"] == extra["handle"]
