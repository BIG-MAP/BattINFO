"""Regression tests: record_to_jsonld must tolerate wrong-but-close input types.

These guard against silent JSON-LD corruption / crashes from hand-built or
externally-imported records whose fields drift from the canonical list[str] /
Mapping shapes (audit theme C).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402

_RECORDS_CONTEXT_V1 = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
_HOUSING_SPEC_SCHEMA = ROOT / "src" / "battinfo" / "data" / "schemas" / "housing-spec.schema.json"


def _housing_spec_formats() -> list[str]:
    schema = json.loads(_HOUSING_SPEC_SCHEMA.read_text(encoding="utf-8"))
    return schema["properties"]["housing_spec"]["properties"]["cell_format"]["enum"]


def test_dataset_about_as_string_is_not_shredded_into_per_character_nodes() -> None:
    iri = "https://w3id.org/emmo#LithiumIonBattery"
    out = record_to_jsonld({"dataset": {"id": "d1", "name": "DS", "about": iri}}, "dataset")
    assert out["dcterms:subject"] == [{"@id": iri}]


def test_dataset_about_as_list_still_works_and_drops_non_strings() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "about": ["https://x/a", None, "", "https://x/b"]}},
        "dataset",
    )
    assert out["dcterms:subject"] == [{"@id": "https://x/a"}, {"@id": "https://x/b"}]


def test_dataset_checksum_as_string_does_not_crash() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "distributions": [{"content_url": "http://x", "checksum": "deadbeef"}]}},
        "dataset",
    )
    # A bare-string checksum is tolerated (skipped), not an AttributeError.
    dist = out["dcat:distribution"][0]
    assert "spdx:checksum" not in dist


def test_dataset_checksum_as_mapping_is_emitted() -> None:
    out = record_to_jsonld(
        {
            "dataset": {
                "id": "d1",
                "name": "DS",
                "distributions": [{"content_url": "http://x", "checksum": {"algorithm": "sha256", "value": "ab"}}],
            }
        },
        "dataset",
    )
    assert out["dcat:distribution"][0]["spdx:checksum"]["spdx:checksumValue"] == "ab"


def test_test_dataset_ids_with_none_does_not_emit_null_id() -> None:
    out = record_to_jsonld({"test": {"id": "t1", "dataset_ids": ["ds-a", None, ""]}}, "test")
    assert out["schema:result"] == [{"@id": "ds-a"}]


def test_test_method_vocabulary_is_allowed() -> None:
    """The gold-standard checker accepts every @type the method graph emits.

    ws.preview_jsonld() on a workspace with a stepped test spec used to print
    8 errors (IterativeWorkflow, VoltageHold, Duration, ...) because the
    validator's allowed set never learned the test-method vocabulary the
    library itself emits.
    """
    from battinfo.jsonld import TEST_METHOD_CONTEXT_TERMS
    from battinfo.validate.jsonld import _allowed_type_terms

    missing = set(TEST_METHOD_CONTEXT_TERMS) - _allowed_type_terms()
    assert not missing, f"emitted method terms rejected by validator: {sorted(missing)}"


def test_every_class_term_of_the_records_context_is_allowed() -> None:
    """The emitters type nodes with terms of the bundled v1 records context, so
    the validator must accept every class term that context defines. Before,
    the allowed set was assembled from the mapping tables alone and missed
    terms such as the generic Case. Unit terms look like class terms but are
    never a node's type, so none of them is accepted."""
    from battinfo.validate.jsonld import _allowed_type_terms, _context_class_terms, _context_unit_terms

    context = json.loads(_RECORDS_CONTEXT_V1.read_text(encoding="utf-8"))["@context"]
    class_terms = _context_class_terms(context)
    unit_terms = _context_unit_terms(context)
    assert {"Case", "CoinCase", "BatteryCell", "Dataset"} <= class_terms - unit_terms
    assert {"V", "Ah", "MWh", "Volt", "UnitOne", "WattPerLitre"} <= unit_terms
    # Prefixes, properties and record keys are not class terms.
    assert not {"emmo", "hasProperty", "name", "nominal_capacity"} & class_terms
    allowed = _allowed_type_terms()
    missing = class_terms - unit_terms - allowed
    assert not missing, f"records-context class terms rejected by validator: {sorted(missing)}"
    assert not unit_terms & allowed, f"unit terms accepted as @type: {sorted(unit_terms & allowed)}"


def _typed_doc(type_term: str) -> dict:
    return {
        "@context": "https://w3id.org/battinfo/context/records/v1.json",
        "@graph": [{"@id": "https://example.org/x", "@type": type_term}],
    }


def test_type_defined_nowhere_is_still_rejected() -> None:
    from battinfo.validate.jsonld import validate_jsonld_report

    report = validate_jsonld_report(_typed_doc("CaseOfNothing"))
    assert [i.code for i in report.errors] == ["jsonld.type_term_unknown"]
    assert "'CaseOfNothing'" in report.errors[0].message


@pytest.mark.parametrize("unit", ["V", "MWh", "UnitOne", "WattPerLitre", "MilliAmperePerSquareCentiMetre"])
def test_unit_is_rejected_as_a_type(unit: str) -> None:
    """A unit is the value of hasMeasurementUnit, never a node's type. The
    records context binds unit terms such as V and MWh, which the class-term
    naming rule alone would accept, so an emitter typing a node "V" would pass.
    MilliAmperePerSquareCentiMetre is rejected whether or not the context and
    the unit map define it yet."""
    from battinfo.validate.jsonld import validate_jsonld_report

    report = validate_jsonld_report(_typed_doc(unit))
    assert [i.code for i in report.errors] == ["jsonld.type_term_unknown"]


@pytest.mark.parametrize("cls", ["Case", "Dataset"])
def test_class_is_accepted_as_a_type(cls: str) -> None:
    from battinfo.validate.jsonld import validate_jsonld_report

    assert not validate_jsonld_report(_typed_doc(cls)).errors


@pytest.mark.parametrize("cell_format", _housing_spec_formats())
def test_housing_spec_case_type_is_accepted_for_every_format(cell_format: str) -> None:
    """A housing spec emits for every format its schema allows. "other" and
    "unknown" have no case class of their own, so the case falls back to the
    generic Case; the validator rejected that @type, and record_to_jsonld
    raised instead of returning a document."""
    from battinfo.validate.jsonld import validate_jsonld_report

    record = {
        "schema_version": "0.2.0",
        "housing_spec": {
            "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
            "name": "PTFE cell",
            "cell_format": cell_format,
            "case": {"material": "PTFE"},
        },
    }
    out = record_to_jsonld(record, "housing-spec")
    case_type = out["isDescriptionFor"]["hasConstituent"]["@type"]
    if cell_format in ("other", "unknown"):
        assert case_type == "Case"
    errors = [i.message for i in validate_jsonld_report(out).issues if i.severity == "error"]
    assert not errors, errors


def test_dcterms_dates_are_iso_datetime_not_epoch_ints() -> None:
    """DCMI terms expect date literals; raw epoch ints typed xsd:integer
    poisoned DCAT harvesters (red-team W3.4)."""
    out = record_to_jsonld(
        {
            "dataset": {
                "id": "https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
                "name": "DS",
                "created_at": 1771718400,
                "modified_at": 1771718500,
            }
        },
        "dataset",
    )
    assert out["dcterms:created"] == "2026-02-22T00:00:00Z"
    assert out["dcterms:modified"] == "2026-02-22T00:01:40Z"


def test_inline_context_is_the_versioned_hosted_context() -> None:
    """Inline emission must expand identically to the hosted context URL the
    files name (0.8.0 review F4: the flat assembled context drifted — stale
    equipment terms and retired IRIs made inline @types expand relative or
    wrong). One authority: records.context.v1.json."""
    import json

    from battinfo.jsonld import _CONTEXT_INLINE, _CONTEXT_URL

    hosted = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json").read_text(encoding="utf-8")
    )["@context"]
    assert _CONTEXT_INLINE == hosted
    assert _CONTEXT_URL.endswith("/records/v1.json")


def test_every_packaged_record_type_resolves_in_the_inline_context() -> None:
    """No emitted @type may expand relative to the document base: every bare
    token must be a term of the inline context (prefixed and absolute forms
    resolve by construction), and the validator must accept it. Sweeps the
    whole packaged corpus, so equipment and prismatic records — the 0.8.0
    review's divergent cases — are covered."""
    from battinfo.jsonld import _CONTEXT_INLINE
    from battinfo.validate.jsonld import _allowed_type_terms

    allowed = _allowed_type_terms()
    examples = ROOT / "src" / "battinfo" / "data" / "examples"
    kind_dirs = sorted(p for p in examples.iterdir() if p.is_dir())
    assert kind_dirs, "packaged examples missing"

    def collect_types(value, out):
        if isinstance(value, list):
            for item in value:
                collect_types(item, out)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k == "@type":
                    for t in v if isinstance(v, list) else [v]:
                        if isinstance(t, str):
                            out.add(t)
                else:
                    collect_types(v, out)

    checked = 0
    unresolved: set[str] = set()
    rejected: set[str] = set()
    for kind_dir in kind_dirs:
        kind = kind_dir.name
        for path in sorted(kind_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            try:
                out = record_to_jsonld(record, kind)
            except ValueError as exc:
                if str(exc).startswith("Unknown record_type"):
                    continue  # a folder with no standalone emitter
                raise  # an example the validator rejects fails the sweep, it is not skipped
            types: set[str] = set()
            collect_types(out, types)
            checked += 1
            for t in types:
                if "://" in t or ":" in t:
                    continue  # absolute or prefixed — resolves by construction
                if t not in _CONTEXT_INLINE:
                    unresolved.add(f"{kind}: {t}")
                if t not in allowed:
                    rejected.add(f"{kind}: {t}")
    assert checked > 50, f"corpus sweep looks broken (only {checked} records emitted)"
    assert not unresolved, f"@type tokens that would expand relative: {sorted(unresolved)}"
    assert not rejected, f"emitted @type tokens the validator rejects: {sorted(rejected)}"
