"""P0 — emit what users author (lab-engineer campaign, cluster C1).

The canonical cell-spec node (shared by the resolver artifact, the Zenodo/local
publication graph, ``record_to_jsonld``, ``ws.preview_jsonld`` and ``ws.export``)
must carry the composition a lab engineer authors:

- inline electrode / electrolyte / separator / housing holders (the 96/2/2
  coating, salts, solvents, mass fractions);
- all five ``*_spec_id`` component references (bare ``{"@id"}`` nodes when there
  is no inline holder; merged onto the inline node when there is — never a
  duplicate of the same component);
- ``material_spec_id`` edges on constituent nodes (``schema:isVariantOf``, the
  same link whole-record material instances emit);
- equipment/channel provenance on tests: ``equipment_id``/``channel_id`` become
  a real equipment node (IRI, name, serial number) plus the channel reference,
  not a nameless ``schema:Thing``.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo
from battinfo.api._resolver import _resolver_jsonld
from battinfo.api._shared import _validate_publication_artifact
from battinfo.entities import stable_uid
from battinfo.jsonld import record_to_jsonld
from battinfo.transform.cell_spec_node import build_cell_spec_node

EXAMPLES = ROOT / "examples"

SPEC_ID = "https://w3id.org/battinfo/spec/" + stable_uid("p0-cell-spec")
MAT_ID = "https://w3id.org/battinfo/spec/" + stable_uid("p0-nmc811-material")
SALT_ID = "https://w3id.org/battinfo/spec/" + stable_uid("p0-lipf6-material")
REFS = {
    field: "https://w3id.org/battinfo/spec/" + stable_uid(f"p0-{field}")
    for field in (
        "positive_electrode_spec_id",
        "negative_electrode_spec_id",
        "electrolyte_spec_id",
        "separator_spec_id",
        "housing_spec_id",
    )
}

# The four cell-level relations a *_spec_id reference merges into (housing_spec_id
# rides hasConstituent).
_REF_RELATIONS = {
    "positive_electrode_spec_id": "hasPositiveElectrode",
    "negative_electrode_spec_id": "hasNegativeElectrode",
    "electrolyte_spec_id": "hasElectrolyte",
    "separator_spec_id": "hasSeparator",
}


def _inline_composition() -> dict:
    """Inline 96/2/2 coating + electrolyte + separator holders (dict shape)."""
    return {
        "positive_electrode": {
            "coating": {
                "component": {
                    "active_material": [
                        {
                            "name": "NMC811",
                            "material_spec_id": MAT_ID,
                            "property": {"mass_fraction": {"value": 96, "unit": "%"}},
                        }
                    ],
                    "binder": [
                        {"name": "PVDF", "property": {"mass_fraction": {"value": 2, "unit": "%"}}}
                    ],
                    "additive": [
                        {
                            "name": "Carbon black",
                            "property": {"mass_fraction": {"value": 2, "unit": "%"}},
                        }
                    ],
                },
                "property": {"loading": {"value": 18.5, "unit": "mg/cm2"}},
            },
            "current_collector": {"name": "Aluminium foil"},
        },
        "negative_electrode": {
            "coating": {
                "component": {
                    "active_material": [
                        {"name": "Graphite", "property": {"mass_fraction": {"value": 96, "unit": "%"}}}
                    ]
                }
            },
            "current_collector": {"name": "Copper foil"},
        },
        "electrolyte": {
            "family": "organic",
            "salt": {
                "name": "LiPF6",
                "material_spec_id": SALT_ID,
                "property": {"concentration": {"value": 1.0, "unit": "mol/L"}},
            },
            "solvent_mixture": {
                "component": [
                    {"name": "EC", "property": {"volume_fraction": {"value": 50, "unit": "%"}}},
                    {"name": "EMC", "property": {"volume_fraction": {"value": 50, "unit": "%"}}},
                ]
            },
        },
        "separator": {
            "material": "polyethylene",
            "property": {"thickness": {"value": 12, "unit": "um"}},
        },
    }


def _composed_record(*, inline: bool = True, refs: bool = True) -> dict:
    record: dict = {
        "schema_version": "0.1.0",
        "cell_spec": {
            "id": SPEC_ID,
            "name": "Acme 21700-X",
            "model": "21700-X",
            "manufacturer": {"type": "Organization", "name": "Acme"},
            "cell_format": "cylindrical",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "NMC811",
            "negative_electrode_basis": "graphite",
        },
        "properties": {"nominal_capacity": {"value": 5.0, "unit": "Ah"}},
        "provenance": {"source_type": "datasheet", "retrieved_at": 1769585584},
    }
    if inline:
        record.update(_inline_composition())
    if refs:
        record.update(REFS)
    return record


def _assert_composition_tree(node: dict) -> None:
    """The shared assertions: composition tree, mass fractions, five ref IRIs,
    and constituent → material-spec edges, on a cell-spec JSON-LD node."""
    pe = node["hasPositiveElectrode"]
    assert pe["@id"] == REFS["positive_electrode_spec_id"]
    coating = pe["hasCoating"]
    assert coating["@type"] == "ElectrodeCoating"
    active = coating["hasActiveMaterial"]
    assert active["schema:name"] == "NMC811"
    assert active["schema:isVariantOf"] == {"@id": MAT_ID}
    fraction = active["hasProperty"]
    assert fraction["@type"][0] == "MassFraction"
    assert fraction["hasNumericalPart"]["hasNumberValue"] == 0.96
    assert coating["hasBinder"]["schema:name"] == "PVDF"
    assert coating["hasBinder"]["hasProperty"]["hasNumericalPart"]["hasNumberValue"] == 0.02
    assert coating["hasConductiveAdditive"]["schema:name"] == "Carbon black"
    assert "CurrentCollector" in pe["hasCurrentCollector"]["@type"]

    ne = node["hasNegativeElectrode"]
    assert ne["@id"] == REFS["negative_electrode_spec_id"]
    assert ne["hasCoating"]["hasActiveMaterial"]["schema:name"] == "Graphite"

    elyte = node["hasElectrolyte"]
    assert elyte["@id"] == REFS["electrolyte_spec_id"]
    assert elyte["@type"] == "OrganicElectrolyte"
    assert elyte["hasSolute"]["schema:name"] == "LiPF6"
    assert elyte["hasSolute"]["schema:isVariantOf"] == {"@id": SALT_ID}
    solvents = elyte["hasSolvent"]
    assert {s["schema:name"] for s in solvents} == {"EC", "EMC"}

    sep = node["hasSeparator"]
    assert sep["@id"] == REFS["separator_spec_id"]
    assert "Separator" in sep["@type"]

    assert node["hasConstituent"] == {"@id": REFS["housing_spec_id"]}


def _collect_bare_terms(value, out: set[str]) -> None:
    """Every dict key and @type string that must resolve in the inline context."""
    if isinstance(value, list):
        for item in value:
            _collect_bare_terms(item, out)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not key.startswith("@") and ":" not in key:
                out.add(key)
            if key == "@type":
                types = item if isinstance(item, list) else [item]
                for t in types:
                    if isinstance(t, str) and ":" not in t:
                        out.add(t)
            else:
                _collect_bare_terms(item, out)


# ── 1. record_to_jsonld (canonical single-record emitter) ────────────────────


def test_record_to_jsonld_emits_composition_and_refs() -> None:
    doc = record_to_jsonld(_composed_record(), "cell-spec")
    _assert_composition_tree(doc)
    # Canonical shape invariants are intact — extended, not reshaped.
    assert doc["@type"] == ["BatteryCellSpecification", "schema:CreativeWork"]
    assert "isDescriptionFor" in doc
    assert any(p["@type"][0] == "NominalCapacity" for p in doc["hasProperty"])
    assert doc["dcterms:source"]["dcterms:type"] == "datasheet"


def test_record_to_jsonld_composition_terms_resolve_in_inline_context() -> None:
    doc = record_to_jsonld(_composed_record(), "cell-spec")
    context = doc["@context"]
    terms: set[str] = set()
    _collect_bare_terms({k: v for k, v in doc.items() if k != "@context"}, terms)
    unresolved = {t for t in terms if t not in context}
    assert not unresolved, f"terms missing from the inline context: {sorted(unresolved)}"


# ── 2. Publish / resolver artifact builder ───────────────────────────────────


def test_resolver_artifact_emits_composition_and_refs() -> None:
    doc = _resolver_jsonld(_composed_record())
    _assert_composition_tree(doc)
    _validate_publication_artifact(doc)


# ── 3. Both reference styles ─────────────────────────────────────────────────


def test_refs_only_cell_emits_reference_nodes() -> None:
    node = build_cell_spec_node(_composed_record(inline=False, refs=True))
    for field, relation in _REF_RELATIONS.items():
        ref = node[relation]
        assert ref["@id"] == REFS[field], relation
        # No inline holder: nothing beyond the reference and (for electrodes) the
        # basis-derived @type refinement may appear.
        assert set(ref) <= {"@id", "@type"}, relation
    assert node["hasConstituent"] == {"@id": REFS["housing_spec_id"]}


def test_inline_only_cell_emits_nested_holders_without_ids() -> None:
    node = build_cell_spec_node(_composed_record(inline=True, refs=False))
    assert "@id" not in node["hasPositiveElectrode"]
    assert node["hasPositiveElectrode"]["hasCoating"]["@type"] == "ElectrodeCoating"
    assert "@id" not in node["hasElectrolyte"]
    assert "hasConstituent" not in node


def test_inline_plus_ref_is_one_merged_node_per_component() -> None:
    node = build_cell_spec_node(_composed_record(inline=True, refs=True))
    for relation in _REF_RELATIONS.values():
        merged = node[relation]
        assert isinstance(merged, dict), f"{relation} must stay a single node"
        assert "@id" in merged
        assert len(merged) > 1, f"{relation} lost its inline content"


# ── 4. ws.preview_jsonld + ws.export (the workspace surface) ─────────────────


def _authored_workspace(tmp_path: Path):
    ws = battinfo.workspace(tmp_path, registry_url=None)
    spec = battinfo.CellSpec(
        manufacturer="Acme",
        model="21700-X",
        format="cylindrical",
        chemistry="Li-ion",
        positive_electrode_basis="NMC811",
        negative_electrode_basis="graphite",
        specs={"nominal_capacity": {"value": 5.0, "unit": "Ah"}},
        **_inline_composition(),
        **REFS,
    )
    ws.add("cell", spec=spec, serial_numbers=["CELL-001"])
    ws.save()
    return ws


def _find_spec_node(graph: list[dict]) -> dict:
    return next(
        n
        for n in graph
        if "BatteryCellSpecification" in (
            n["@type"] if isinstance(n.get("@type"), list) else [n.get("@type")]
        )
        and "hasPositiveElectrode" in n
    )


def test_preview_jsonld_emits_composition_and_refs(tmp_path: Path) -> None:
    ws = _authored_workspace(tmp_path)
    out = ws.preview_jsonld(tmp_path / "preview.jsonld")
    doc = json.loads(out.read_text(encoding="utf-8"))
    node = _find_spec_node(doc["@graph"])
    # The workspace mints the spec IRI at save; check content, not the fixture @id.
    coating = node["hasPositiveElectrode"]["hasCoating"]
    assert coating["hasActiveMaterial"]["schema:isVariantOf"] == {"@id": MAT_ID}
    assert coating["hasActiveMaterial"]["hasProperty"]["hasNumericalPart"]["hasNumberValue"] == 0.96
    assert node["hasPositiveElectrode"]["@id"] == REFS["positive_electrode_spec_id"]
    assert node["hasNegativeElectrode"]["@id"] == REFS["negative_electrode_spec_id"]
    assert node["hasElectrolyte"]["@id"] == REFS["electrolyte_spec_id"]
    assert node["hasElectrolyte"]["hasSolute"]["schema:isVariantOf"] == {"@id": SALT_ID}
    assert node["hasSeparator"]["@id"] == REFS["separator_spec_id"]
    assert node["hasConstituent"] == {"@id": REFS["housing_spec_id"]}
    # Every composition term resolves in the deposit's inline context.
    context = doc["@context"]
    terms: set[str] = set()
    _collect_bare_terms(node, terms)
    unresolved = {t for t in terms if t not in context}
    assert not unresolved, f"terms missing from the inline context: {sorted(unresolved)}"


def test_export_ttl_carries_composition_and_refs(tmp_path: Path) -> None:
    ws = _authored_workspace(tmp_path)
    written = ws.export("ttl", tmp_path / "rdf")
    ttl_files = [p for p in written if "cell-spec" in str(p.parent)]
    assert ttl_files, "no cell-spec ttl written"
    text = ttl_files[0].read_text(encoding="utf-8")
    for iri in (*REFS.values(), MAT_ID, SALT_ID):
        assert iri in text, f"{iri} missing from Turtle export"
    # The active-material mass fraction survived to RDF (as a numeric literal).
    from rdflib import Graph, Literal

    g = Graph()
    g.parse(data=text, format="turtle")
    values = {float(o) for _, _, o in g if isinstance(o, Literal) and o.datatype and "double" in str(o.datatype)}
    values |= {float(o) for _, _, o in g if isinstance(o, Literal) and str(o).replace(".", "", 1).isdigit()}
    assert 0.96 in values, "mass fraction 0.96 missing from Turtle export"


# ── 5. Equipment / channel provenance on tests (Persona B #18) ───────────────


def _equipment_spec_record() -> dict:
    paths = sorted((EXAMPLES / "equipment-spec").glob("*.json"))
    assert paths, "no equipment-spec example available"
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _tested_workspace(tmp_path: Path):
    ws = battinfo.workspace(tmp_path, registry_url=None)
    records = ws.add(
        "equipment",
        spec=_equipment_spec_record(),
        serial_number="MC3K-P0-0001",
        name="Cycler 1",
        location="Lab B",
    )
    equipment_id = records[0]["equipment"]["id"]
    channel_id = records[2]["channel"]["id"]  # CH2
    spec = battinfo.CellSpec(
        manufacturer="Acme", model="X-1", format="cylindrical", chemistry="Li-ion"
    )
    ws.add("cell", spec=spec, serial_numbers=["CELL-001"])
    ws.add("test", type="cycling", cell="CELL-001", channel="Cycler 1/CH2")
    ws.save()
    return ws, equipment_id, channel_id


def test_preview_graph_contains_equipment_node_and_channel(tmp_path: Path) -> None:
    ws, equipment_id, channel_id = _tested_workspace(tmp_path)
    out = ws.preview_jsonld(tmp_path / "preview.jsonld")
    doc = json.loads(out.read_text(encoding="utf-8"))
    graph = doc["@graph"]
    by_id = {n.get("@id"): n for n in graph if n.get("@id")}

    # The test links its registered equipment (a resolvable node, not a
    # nameless schema:Thing) and the channel it ran on.
    tnode = next(n for n in graph if "BatteryTest" in (n.get("@type") or []))
    assert tnode["hasTestEquipment"]["@id"] == equipment_id
    assert tnode["hasTestEquipment"]["schema:name"] == "Cycler 1"
    used = tnode["prov:used"]
    assert {"@id": channel_id} in (used if isinstance(used, list) else [used])

    # The graph carries the real equipment node: IRI, name, serial, spec link.
    equipment = by_id[equipment_id]
    assert equipment["schema:name"] == "Cycler 1"
    assert equipment["schema:serialNumber"] == "MC3K-P0-0001"
    assert equipment["@type"][0] == "BatteryCycler"
    assert equipment["hasDescription"]["@id"].startswith("https://w3id.org/battinfo/spec/")

    # ... and the channel node, tied to its unit.
    channel = by_id[channel_id]
    assert channel["schema:isPartOf"] == {"@id": equipment_id}
    assert channel["schema:name"] == "Cycler 1/CH2"


def test_exported_test_record_carries_equipment_and_channel(tmp_path: Path) -> None:
    ws, equipment_id, channel_id = _tested_workspace(tmp_path)
    test_file = sorted((ws._ws.source_root / "test").glob("*.json"))[0]
    raw = json.loads(test_file.read_text(encoding="utf-8"))
    doc = record_to_jsonld(raw, "test")
    assert doc["hasTestEquipment"]["@id"] == equipment_id
    assert doc["prov:used"] == {"@id": channel_id}

    # The resolver artifact for the same record carries the same provenance.
    resolver_doc = _resolver_jsonld(raw)
    equip = resolver_doc["hasTestEquipment"]
    assert equip["@id"] == equipment_id
    assert resolver_doc["prov:used"] == {"@id": channel_id}


def test_instrument_string_only_keeps_legacy_named_node() -> None:
    """No registered equipment: the instrument string still yields a named node."""
    from battinfo.ws import AuthoringWorkspace

    test_record = {
        "test": {
            "id": "https://w3id.org/battinfo/test/" + stable_uid("p0-test"),
            "cell_id": "https://w3id.org/battinfo/cell/" + stable_uid("p0-cell"),
            "kind": "cycling",
            "instrument_name": "Neware BTS-4000",
        }
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        package = AuthoringWorkspace._assemble_zenodo_jsonld(
            {"test": [test_record]},
            zenodo_record_id=1,
            prereserved_doi="10.5281/zenodo.1",
            record_url="https://zenodo.org/records/1",
            data_filenames=[],
        )
    tnode = next(n for n in package["@graph"] if "BatteryTest" in (n.get("@type") or []))
    assert tnode["hasTestEquipment"]["schema:name"] == "Neware BTS-4000"
