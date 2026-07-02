"""D-2 / D-3: exported RDF must not silently leak the authoring machine's filesystem.

D-2 — an unmapped unit must be emitted as a plain-text literal (schema:unitText), never as a bare
symbol under the @id-typed hasMeasurementUnit (which rdflib coerces into a cwd-relative file://
IRI). D-3 — when validating a record for publication, a bare-token @id (no scheme, no CURIE) is
rejected, because it would resolve against the cwd on export; local/staging validation and
legitimate file:// bundle links are left untouched."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import _quantity
from battinfo.validate.core import DEFAULT_POLICY, PUBLISHER_POLICY, STRICT_POLICY
from battinfo.validate.jsonld import validate_jsonld_report


# ── D-2: unit emission ────────────────────────────────────────────────────────
def test_quantity_maps_known_unit_to_id() -> None:
    node = _quantity(3.7, "V")
    unit = node["hasMeasurementUnit"]
    assert isinstance(unit, dict) and "@id" in unit  # mapped -> @id reference
    assert "schema:unitText" not in node


def test_quantity_emits_unmapped_unit_as_literal_not_bare_id() -> None:
    node = _quantity(50, "furlongs")
    # The @id-typed hasMeasurementUnit must NOT carry the bare symbol (that becomes a file:// IRI).
    assert node.get("hasMeasurementUnit") != "furlongs"
    assert "hasMeasurementUnit" not in node
    assert node["schema:unitText"] == "furlongs"


def test_publication_property_node_emits_unmapped_unit_as_literal() -> None:
    from battinfo.publication import PROPERTY_TYPE_MAP, UNIT_IRI_MAP, _cell_spec_property_node

    name = next(iter(PROPERTY_TYPE_MAP))
    bad_unit = "furlongs"
    assert bad_unit not in UNIT_IRI_MAP
    node = _cell_spec_property_node(name, {"value": 1.0, "unit": bad_unit})
    assert node is not None
    assert node.get("hasMeasurementUnit") != bad_unit  # not a bare @id-typed leak
    assert node.get("schema:unitText") == bad_unit


# ── D-3: @id portability sweep ────────────────────────────────────────────────
def _bare_id_doc() -> dict:
    return {"@graph": [{"@id": "c1", "@type": "battinfo:Cell"}]}


def _has_id_error(report) -> bool:  # noqa: ANN001
    return any(i.code == "jsonld.id_not_portable" for i in report.issues)


def test_bare_id_rejected_under_publisher_policy() -> None:
    report = validate_jsonld_report(_bare_id_doc(), policy=PUBLISHER_POLICY)
    assert _has_id_error(report)


def test_bare_id_ignored_under_authoring_policies() -> None:
    # Mid-pipeline authoring/strict validation must not flag local ids that get namespaced later.
    assert not _has_id_error(validate_jsonld_report(_bare_id_doc(), policy=DEFAULT_POLICY))
    assert not _has_id_error(validate_jsonld_report(_bare_id_doc(), policy=STRICT_POLICY))


def test_portable_ids_pass_under_publisher_policy() -> None:
    doc = {
        "@graph": [
            {"@id": "https://w3id.org/battinfo/spec/abcd", "@type": "battinfo:Cell"},
            {"@id": "battinfo:hasProperty"},  # compact CURIE
            {"@id": "_:b0"},  # blank node
        ]
    }
    assert not _has_id_error(validate_jsonld_report(doc, policy=PUBLISHER_POLICY))


def test_file_scheme_id_tolerated_for_offline_bundle() -> None:
    # The offline DCAT bundle links sibling data files with absolute file:// @ids by design;
    # the sweep targets bare tokens, not explicit file:// IRIs.
    doc = {"@graph": [{"@id": "file:///tmp/bundle/data.csv", "@type": "schema:Dataset"}]}
    assert not _has_id_error(validate_jsonld_report(doc, policy=PUBLISHER_POLICY))
