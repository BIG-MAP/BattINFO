"""Regression tests: record_to_jsonld must tolerate wrong-but-close input types.

These guard against silent JSON-LD corruption / crashes from hand-built or
externally-imported records whose fields drift from the canonical list[str] /
Mapping shapes (audit theme C).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402


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
        {"dataset": {"id": "d1", "name": "DS", "distributions": [
            {"content_url": "http://x", "checksum": {"algorithm": "sha256", "value": "ab"}}]}},
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


def test_dcterms_dates_are_iso_datetime_not_epoch_ints() -> None:
    """DCMI terms expect date literals; raw epoch ints typed xsd:integer
    poisoned DCAT harvesters (red-team W3.4)."""
    out = record_to_jsonld(
        {"dataset": {"id": "https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
                     "name": "DS", "created_at": 1771718400, "modified_at": 1771718500}},
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
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json")
        .read_text(encoding="utf-8")
    )["@context"]
    assert _CONTEXT_INLINE == hosted
    assert _CONTEXT_URL.endswith("/records/v1.json")


def test_every_packaged_record_type_resolves_in_the_inline_context() -> None:
    """No emitted @type may expand relative to the document base: every bare
    token must be a term of the inline context (prefixed and absolute forms
    resolve by construction). Sweeps the whole packaged corpus, so equipment
    and prismatic records — the 0.8.0 review's divergent cases — are covered."""
    import json

    from battinfo.jsonld import _CONTEXT_INLINE

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
    for kind_dir in kind_dirs:
        kind = kind_dir.name
        for path in sorted(kind_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            try:
                out = record_to_jsonld(record, kind)
            except (KeyError, ValueError):
                continue  # kinds without a standalone emitter
            types: set[str] = set()
            collect_types(out, types)
            checked += 1
            for t in types:
                if "://" in t or ":" in t:
                    continue  # absolute or prefixed — resolves by construction
                if t not in _CONTEXT_INLINE:
                    unresolved.add(f"{kind}: {t}")
    assert checked > 50, f"corpus sweep looks broken (only {checked} records emitted)"
    assert not unresolved, f"@type tokens that would expand relative: {sorted(unresolved)}"
