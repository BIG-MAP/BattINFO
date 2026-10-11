"""battinfo.naming: handles and titles built from structured parts.

The Flores table is the owner's naming contract (2026-10-08) verbatim: every
row must come out exactly, handle and title both.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.entities import ENTITY_KINDS  # noqa: E402
from battinfo.naming import (  # noqa: E402
    HANDLE_MAX_LENGTH,
    HANDLE_PATTERN,
    KIND_WORDS,
    PRODUCT_KINDS,
    handle_for,
    is_valid_handle,
    kind_word,
    organization_handle,
    title_for,
)

GROUP = "flores-ocv"
GR = {"subject": "graphite", "variant": "Gr-AQ-1"}
GR_SAMPLE = {**GR, "sample": "063b77"}

# (kind, parts, handle, title) - the contract table, row for row.
FLORES = [
    ("collection", {}, "flores-ocv", "Flores et al. 2026 half-cell OCV collection"),
    ("material-spec", {"subject": "graphite"}, "flores-ocv/graphite-material-spec", "Graphite material spec"),
    ("material", {"subject": "graphite"}, "flores-ocv/graphite-material-lot", "Graphite material lot"),
    ("electrode-spec", GR, "flores-ocv/graphite-aq-1-electrode-spec", "Graphite AQ-1 electrode spec"),
    ("electrode", GR_SAMPLE, "flores-ocv/graphite-aq-1-063b77-electrode", "Graphite AQ-1 electrode 063b77"),
    ("cell-spec", GR, "flores-ocv/graphite-aq-1-cell-spec", "Graphite AQ-1 cell spec"),
    ("cell", GR_SAMPLE, "flores-ocv/graphite-aq-1-063b77-cell", "Graphite AQ-1 cell 063b77"),
    ("test-spec", {"method": "gitt"}, "flores-ocv/gitt-test-spec", "GITT test spec"),
    ("test", {**GR_SAMPLE, "method": "gitt"}, "flores-ocv/graphite-aq-1-063b77-gitt-test",
     "Graphite AQ-1 cell 063b77 GITT test"),
    ("dataset", {**GR_SAMPLE, "method": "gitt"}, "flores-ocv/graphite-aq-1-063b77-gitt-dataset",
     "Graphite AQ-1 cell 063b77 GITT dataset"),
]


@pytest.mark.parametrize(("kind", "parts", "handle", "title"), FLORES, ids=[row[0] for row in FLORES])
def test_flores_contract_rows_come_out_exactly(kind: str, parts: dict, handle: str, title: str) -> None:
    assert handle_for(kind, group=GROUP, **parts) == handle
    if kind == "collection":
        assert title_for(kind, label="Flores et al. 2026 half-cell OCV") == title
    else:
        assert title_for(kind, **parts) == title
    assert is_valid_handle(handle)


def test_kind_words_cover_every_entity_kind_and_nothing_else() -> None:
    assert set(KIND_WORDS) == {kind.entity_type for kind in ENTITY_KINDS}
    assert KIND_WORDS["material"] == "material-lot"
    assert KIND_WORDS["test-protocol"] == "test-spec"
    for word in KIND_WORDS.values():
        assert is_valid_handle(word)


@pytest.mark.parametrize(("kind", "word"), [
    ("material", "material-lot"),
    ("material-lot", "material-lot"),
    ("test_spec", "test-spec"),
    ("test-protocol", "test-spec"),
    ("cell_instance", "cell"),
    ("Cell Spec", "cell-spec"),
    ("current_collector", "current-collector"),
    ("collection", None),
    ("dataset-series", None),
])
def test_kind_word_resolves_every_spelling_of_a_kind(kind: str, word: str | None) -> None:
    assert kind_word(kind) == word


def test_unknown_kind_is_a_value_error_listing_the_kinds() -> None:
    with pytest.raises(ValueError, match="material-spec"):
        handle_for("widget", group=GROUP)


def test_kind_word_is_always_last() -> None:
    handle = handle_for("dataset", group=GROUP, subject="lnmo", variant="LNMO-NMP-2",
                        sample="A7", method="p-OCV hold")
    assert handle == "flores-ocv/lnmo-nmp-2-a7-p-ocv-hold-dataset"
    assert handle.endswith("-dataset")


@pytest.mark.parametrize(("subject", "variant", "expected"), [
    ("graphite", "Gr-AQ-1", "aq-1"),
    ("lnmo", "LNMO-NMP-2", "nmp-2"),           # NMP is a material kind too, but not the subject
    ("silicon_graphite", "Si-Gr-AQ-1", "aq-1"),  # a two-token prefix
    ("silicon-graphite", "SiGr_AQ_3", "aq-3"),
    ("silicon", "Si-AQ-1", "aq-1"),
    ("graphite", "AQ-1", "aq-1"),               # already without a prefix: unchanged
    ("lnmo", "Gr-AQ-1", "gr-aq-1"),             # another material's prefix is kept
])
def test_variant_drops_only_the_subjects_material_prefix(subject: str, variant: str, expected: str) -> None:
    handle = handle_for("electrode-spec", subject=subject, variant=variant)
    assert handle == f"{subject.replace('_', '-')}-{expected}-electrode-spec"


def test_variant_that_is_only_the_prefix_is_left_out() -> None:
    assert handle_for("electrode-spec", subject="graphite", variant="Gr") == "graphite-electrode-spec"
    assert title_for("electrode-spec", subject="graphite", variant="Gr") == "Graphite electrode spec"


def test_variant_without_subject_keeps_every_token() -> None:
    assert handle_for("electrode-spec", variant="Gr-AQ-1") == "gr-aq-1-electrode-spec"


def test_subject_aliases_resolve_to_the_vocabulary_key() -> None:
    assert handle_for("material-spec", subject="Gr") == "graphite-material-spec"
    assert handle_for("material-spec", subject="Si/Gr") == "silicon-graphite-material-spec"
    assert handle_for("material-spec", subject="NMC 532") == "nmc532-material-spec"


def test_subject_outside_the_vocabulary_is_slugged_as_given() -> None:
    assert handle_for("equipment", subject="Maccor 4000") == "maccor-4000-equipment"
    assert title_for("equipment", subject="Maccor 4000") == "Maccor 4000 equipment"


@pytest.mark.parametrize(("subject", "label"), [
    ("graphite", "Graphite"),
    ("silicon_graphite", "Silicon-graphite"),
    ("silicon", "Silicon"),
    ("lnmo", "LNMO"),
    ("lfp", "LFP"),
    ("nmc111", "NMC111"),
    ("nmc532", "NMC532"),
    ("litfsi", "LiTFSI"),  # the trailing abbreviation, not "Lithium bis"
])
def test_subject_labels_are_short(subject: str, label: str) -> None:
    assert title_for("material-spec", subject=subject) == f"{label} material spec"


def test_inputs_are_normalised_defensively() -> None:
    handle = handle_for("cell", group="  Flörés OCV / Batch_2 ", subject="graphite",
                        variant="Gr  AQ--1", sample=" 063B77 ")
    assert handle == "flores-ocv/batch-2/graphite-aq-1-063b77-cell"
    assert handle_for("cell", group=GROUP, sample=42) == "flores-ocv/42-cell"


@pytest.mark.parametrize("parts", [
    {"group": "!!!"},
    {"group": GROUP, "sample": "---"},
    {"group": GROUP, "method": "  "},
    {"group": GROUP, "subject": "%%"},
    {"group": "//"},
])
def test_a_part_with_nothing_left_after_normalising_is_a_value_error(parts: dict) -> None:
    with pytest.raises(ValueError):
        handle_for("cell", **parts)


def test_wrong_part_types_are_type_errors() -> None:
    with pytest.raises(TypeError):
        handle_for("cell", group=GROUP, sample=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        handle_for("cell", group=GROUP, sample=["063b77"])  # type: ignore[arg-type]


def test_collection_handle_is_the_bare_group_and_takes_nothing_else() -> None:
    assert handle_for("collection", group="Flores OCV") == "flores-ocv"
    with pytest.raises(ValueError, match="bare group"):
        handle_for("collection", group=GROUP, subject="graphite")
    with pytest.raises(ValueError, match="group"):
        handle_for("collection")


def test_handle_without_group_is_the_bare_segment() -> None:
    assert handle_for("material-spec", subject="lfp") == "lfp-material-spec"


def test_handle_longer_than_the_limit_is_refused() -> None:
    with pytest.raises(ValueError, match=str(HANDLE_MAX_LENGTH)):
        handle_for("cell", group=GROUP, sample="x" * HANDLE_MAX_LENGTH)


@pytest.mark.parametrize(("value", "ok"), [
    ("flores-ocv", True),
    ("flores-ocv/graphite-aq-1-063b77-cell", True),
    ("a/b/c-1", True),
    ("0", True),
    ("Flores-OCV", False),
    ("flores_ocv", False),
    ("flores--ocv", False),
    ("-flores", False),
    ("flores-", False),
    ("flores//ocv", False),
    ("/flores", False),
    ("flores/", False),
    ("flörés", False),
    ("", False),
    (None, False),
    (12, False),
    ("a" * HANDLE_MAX_LENGTH, True),
    ("a" * (HANDLE_MAX_LENGTH + 1), False),
])
def test_is_valid_handle(value: object, ok: bool) -> None:
    assert is_valid_handle(value) is ok


def test_pattern_constant_matches_the_schema_definition() -> None:
    import json

    schema = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "schemas" / "cell-spec.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$defs"]["Handle"]["pattern"] == HANDLE_PATTERN
    assert schema["$defs"]["Handle"]["maxLength"] == HANDLE_MAX_LENGTH


def test_title_lowercase_method_is_upper_cased_and_sample_keeps_its_case() -> None:
    assert title_for("test", subject="lnmo", variant="LNMO-NMP-2", sample="A7b", method="p-ocv hold") == (
        "LNMO NMP-2 cell A7b P-OCV HOLD test"
    )


def test_title_tested_item_can_change_or_go() -> None:
    parts = {**GR_SAMPLE, "method": "gitt"}
    assert title_for("test", tested="electrode", **parts) == "Graphite AQ-1 electrode 063b77 GITT test"
    assert title_for("test", tested=None, **parts) == "Graphite AQ-1 063b77 GITT test"
    assert title_for("test", method="gitt") == "GITT test"


def test_title_without_subject_starts_with_a_capital() -> None:
    assert title_for("cell-spec") == "Cell spec"
    assert title_for("test-spec") == "Test spec"


def test_title_kind_words_are_plain_english() -> None:
    assert title_for("current-collector-spec") == "Current collector spec"
    assert title_for("parameter-set", subject="graphite") == "Graphite parameter set"
    assert title_for("material-lot", subject="nmc532") == "NMC532 material lot"


def test_collection_title_needs_a_label_and_does_not_double_the_word() -> None:
    assert title_for("collection", label="Flores OCV collection") == "Flores OCV collection"
    with pytest.raises(ValueError, match="label"):
        title_for("collection")
    with pytest.raises(ValueError, match="only used for collections"):
        title_for("cell", label="Graphite")


def test_title_keeps_a_capitalised_method_as_written() -> None:
    assert title_for("test-spec", method="p-OCV hold") == "p-OCV hold test spec"
    assert (
        title_for("dataset", subject="graphite", variant="Gr-AQ-1", sample="063b77", method="p-OCV")
        == "Graphite AQ-1 cell 063b77 p-OCV dataset"
    )


# ── Products and organizations ────────────────────────────────────────────────


@pytest.mark.parametrize(("manufacturer", "model", "handle", "title"), [
    ("Saft", "VL 5U", "saft/vl-5u-cell-spec", "Saft VL 5U"),
    ("SAMSUNG", "INR18650-35E", "samsung/inr18650-35e-cell-spec", "SAMSUNG INR18650-35E"),
    ("Samsung SDI", "Samsung SDI INR21700-50E", "samsung-sdi/inr21700-50e-cell-spec", "Samsung SDI INR21700-50E"),
    ("Wuhan Lisun Power Corp. Ltd", "IMP225069S", "wuhan-lisun-power-corp-ltd/imp225069s-cell-spec",
     "Wuhan Lisun Power Corp. Ltd IMP225069S"),
])
def test_a_product_is_named_by_its_manufacturer_and_model(manufacturer, model, handle, title) -> None:
    assert handle_for("cell-spec", manufacturer=manufacturer, model=model) == handle
    assert title_for("cell-spec", manufacturer=manufacturer, model=model) == title
    assert is_valid_handle(handle)


def test_an_organization_reference_with_a_handle_sets_the_group() -> None:
    # Two spellings of one company resolve to one group once its record has a handle.
    for spelling in ("EVE", "EVE Energy"):
        ref = {"name": spelling, "id": "https://w3id.org/battinfo/organization/xxxx-xxxx-xxxx-xxxx",
               "handle": "eve-energy"}
        assert handle_for("cell-spec", manufacturer=ref, model="LF280K") == "eve-energy/lf280k-cell-spec"
    record = {"organization": {"name": "EVE Energy", "handle": "eve-energy"}}
    assert title_for("cell-spec", manufacturer=record, model="LF280K") == "EVE Energy LF280K"


def test_every_product_kind_takes_the_product_rule() -> None:
    for kind in PRODUCT_KINDS:
        handle = handle_for(kind, manufacturer="Gelon LIB", model="LFP 1")
        assert handle.startswith("gelon-lib/lfp-1-")
        assert handle.endswith(KIND_WORDS[kind])


@pytest.mark.parametrize("kind", ["cell", "test", "dataset", "material", "collection"])
def test_the_product_rule_is_only_for_spec_kinds(kind) -> None:
    with pytest.raises(ValueError):
        handle_for(kind, manufacturer="Saft", model="VL 5U")


def test_a_product_needs_both_parts_and_nothing_else() -> None:
    with pytest.raises(ValueError):
        handle_for("cell-spec", manufacturer="Saft")
    with pytest.raises(ValueError):
        title_for("cell-spec", model="VL 5U")
    with pytest.raises(ValueError):
        handle_for("cell-spec", manufacturer="Saft", model="VL 5U", group="flores-ocv")
    with pytest.raises(ValueError):
        title_for("cell-spec", manufacturer={"handle": "saft"}, model="VL 5U")


def test_organization_handles_are_one_bare_segment() -> None:
    assert organization_handle("Samsung SDI") == "samsung-sdi"
    assert organization_handle({"organization": {"name": "Haldor Topsøe A/S"}}) == "haldor-topsoe-a-s"
    assert handle_for("organization", group="Topsoe") == "topsoe"
    with pytest.raises(ValueError):
        organization_handle({"name": "Topsoe", "handle": "nordic/topsoe"})


# ── Source-first titles ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("kind", "parts", "title"), [
    ("material-spec", {"subject": "graphite"}, "Flores 2026 graphite material spec"),
    ("material", {"subject": "graphite"}, "Flores 2026 graphite material lot"),
    ("electrode-spec", {"subject": "graphite", "variant": "Gr-AQ-1"}, "Flores 2026 graphite AQ-1 electrode spec"),
    ("electrode", {"subject": "graphite", "variant": "Gr-AQ-1", "sample": "063b77"},
     "Flores 2026 graphite AQ-1 electrode 063b77"),
    ("cell-spec", {"subject": "lnmo", "variant": "LNMO-NMP-1"}, "Flores 2026 LNMO NMP-1 cell spec"),
    ("cell", {"subject": "silicon_graphite", "variant": "SiGr-AQ-2", "sample": "61a57a"},
     "Flores 2026 silicon-graphite AQ-2 cell 61a57a"),
    ("test-protocol", {"method": "GITT"}, "Flores 2026 GITT test spec"),
    ("test-protocol", {"method": "p-OCV hold"}, "Flores 2026 p-OCV hold test spec"),
    ("dataset", {"subject": "graphite", "variant": "Gr-AQ-1", "sample": "063b77", "method": "GITT"},
     "Flores 2026 graphite AQ-1 cell 063b77 GITT dataset"),
])
def test_a_source_leads_the_title(kind, parts, title) -> None:
    assert title_for(kind, source="Flores 2026", **parts) == title


def test_source_is_not_for_products_or_collections() -> None:
    with pytest.raises(ValueError):
        title_for("cell-spec", source="Flores 2026", manufacturer="Saft", model="VL 5U")
    with pytest.raises(ValueError):
        title_for("collection", source="Flores 2026", label="half-cell OCP")
    with pytest.raises(ValueError):
        title_for("material-spec", source="  ", subject="graphite")
