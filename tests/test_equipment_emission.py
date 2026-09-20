"""Equipment/channel JSON-LD emission (0.8.0 core-features scope ruling).

The family had authoring, validation and deposit-graph presence but no record
emitter — the last "no JSON-LD emitter" gap on the docs pages. These pin the
new emitters and the convergence rule: a standalone equipment record emits the
SAME node shape the deposit graph builds for hasTestEquipment targets.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import create_channel, create_equipment, create_equipment_spec  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402

SPEC_UID = "aaaa-bbbb-cccc-dddd"
SPEC_IRI = f"https://w3id.org/battinfo/spec/{SPEC_UID}"


def _spec() -> dict:
    return create_equipment_spec(
        uid=SPEC_UID, name="SkyRC MC3000", manufacturer="SkyRC", model="MC3000",
        equipment_class="cycler", channel_count=4,
        supported_chemistries=["NiMH", "Li-ion"],
        property={"max_current": {"value": 3.0, "unit": "A"}},
    )


def test_equipment_spec_follows_the_description_pattern() -> None:
    ld = record_to_jsonld(_spec(), "equipment-spec")
    assert ld["@context"] == "https://w3id.org/battinfo/context/records/v1.json"
    assert ld["@type"] == ["Description", "schema:ProductModel", "schema:CreativeWork"]
    described = ld["isDescriptionFor"]
    assert described["@id"] == f"{SPEC_IRI}#described"
    assert described["@type"] == ["BatteryCycler", "schema:Product"]
    assert described["skos:prefLabel"] == "SkyRC MC3000"
    # Nothing physical stays on the spec node.
    assert not any(key.startswith("has") and key != "isDescriptionFor" for key in ld)
    # Equipment quantities are named PropertyValues, not minted EMMO terms.
    names = {p["schema:name"] for p in described["schema:additionalProperty"]}
    assert {"equipment_class", "channel_count", "supported_chemistries", "max_current"} <= names


def test_equipment_unit_matches_the_deposit_node_shape() -> None:
    unit = create_equipment(
        uid="bbbb-cccc-dddd-eeee", spec_id=SPEC_IRI, serial_number="MC3K-1",
        name="Cycler 1", location="Lab B", status="active",
    )
    ld = record_to_jsonld(unit, "equipment")
    assert ld["@type"] == ["BatteryCycler", "prov:Entity"]
    assert ld["schema:serialNumber"] == "MC3K-1"
    assert ld["schema:location"] == "Lab B"
    # The instance seam, as everywhere: description link + conformance +
    # ProductModel variant edge.
    for term in ("hasDescription", "dcterms:conformsTo", "schema:isVariantOf"):
        assert ld[term] == {"@id": SPEC_IRI}, term


def test_channel_carries_parent_and_position() -> None:
    equipment_iri = "https://w3id.org/battinfo/equipment/bbbb-cccc-dddd-eeee"
    channel = create_channel(uid="cccc-dddd-eeee-ffff", equipment_id=equipment_iri, index=3)
    ld = record_to_jsonld(channel, "channel")
    assert ld["@type"] == ["schema:Thing", "prov:Entity"]
    assert ld["schema:name"] == "CH3"
    assert ld["schema:position"] == 3
    assert ld["schema:isPartOf"] == {"@id": equipment_iri}


def test_every_emitted_term_resolves_in_the_hosted_context() -> None:
    import json

    v1 = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json")
        .read_text(encoding="utf-8")
    )["@context"]

    def bare_terms(value, out):
        if isinstance(value, list):
            for item in value:
                bare_terms(item, out)
        elif isinstance(value, dict):
            for k, v in value.items():
                if not k.startswith("@") and ":" not in k:
                    out.add(k)
                if k == "@type":
                    for t in (v if isinstance(v, list) else [v]):
                        if isinstance(t, str) and ":" not in t:
                            out.add(t)
                else:
                    bare_terms(v, out)

    unit = create_equipment(uid="bbbb-cccc-dddd-eeee", spec_id=SPEC_IRI, serial_number="S1")
    channel = create_channel(
        uid="cccc-dddd-eeee-ffff",
        equipment_id="https://w3id.org/battinfo/equipment/bbbb-cccc-dddd-eeee", index=1,
    )
    for rec, rt in ((_spec(), "equipment-spec"), (unit, "equipment"), (channel, "channel")):
        ld = record_to_jsonld(rec, rt, context="inline")
        terms: set[str] = set()
        bare_terms({k: v for k, v in ld.items() if k != "@context"}, terms)
        unresolved = sorted(t for t in terms if t not in v1)
        assert not unresolved, (rt, unresolved)
