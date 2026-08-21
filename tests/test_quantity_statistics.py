"""A quantity can state the spread of the sample it summarises (gap E7).

A lab number is often a batch average. The Flores corpus wrote one as
*"Active-mass loading: 3.6472 +/- 0.3017 mg/cm2 (mean +/- sample standard
deviation, n = 8 cells)"* — in a free-text ``notes`` string, because ``Quantity``
had a slot for the mean and none for the spread. A structured key would have been
dropped by the emitter and warned about by the save gate, and a second property
key mapping to ``ActiveMassLoading`` would have collided with the first. So the
number that says how much the batch varied was published as prose: unqueryable,
unaggregatable, and invisible to the EES crosswalk that asks for exactly it.

``standard_deviation`` and ``sample_count`` sit alongside ``value`` and ``unit``,
which keeps the three numbers one quantity instead of three competing properties.

On the emission side there is no EMMO class to type them with. The pinned closure
has no ``StandardDeviation``, ``Variance`` or ``SampleCount``; it does have
``MetrologicalUncertainty``, and using that would say something false — a sample
standard deviation over eight discs is the spread of a population of distinct
objects, not the uncertainty attributed to one measurand. So they ride
``schema:valueReference`` as named ``schema:PropertyValue`` qualifiers on the same
property node: exactly what is there, nothing more, attached to the number it
describes, and ready to flip to an EMMO class the day one is published (tracked
in docs/internal/ontology-additions-needed.md).

The prose form stays valid. Records that already say it in ``notes`` keep
validating; they simply no longer have to.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import create_electrode, create_electrode_spec  # noqa: E402
from battinfo.bundle import CellSpec, ProvenanceInfo  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402

ELECTRODE_SPEC_IRI = "https://w3id.org/battinfo/spec/d7qr-n581-74c3-7g7r"
CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"

# The real corpus number, verbatim: LNMO-AQ-1, eight cells.
LOADING = {
    "value": 3.6472,
    "unit": "mg/cm2",
    "standard_deviation": 0.3017,
    "sample_count": 8,
    "min_value": 3.2844,
    "max_value": 4.0667,
}


def _electrode(**property_overrides) -> dict:
    prop = {"loading": dict(LOADING)}
    prop.update(property_overrides)
    record = create_electrode(
        validate=False, uid="k81p-5wxb-gaph-z6ee", name="LNMO-AQ-1 discs",
        electrode_spec_id=ELECTRODE_SPEC_IRI, batch="LNMO-AQ-1",
    )
    record["electrode"]["property"] = prop
    return record


def _electrode_property_nodes(record: dict) -> dict[str, dict]:
    node = to_jsonld(record, target="domain-battery")["@graph"][0]
    properties = node.get("hasProperty") or []
    if isinstance(properties, dict):
        properties = [properties]
    return {prop["skos:prefLabel"]: prop for prop in properties}


def _qualifiers(node: dict) -> dict[str, dict]:
    """``propertyID -> qualifier node`` for one property's valueReference."""
    reference = node.get("schema:valueReference")
    if reference is None:
        return {}
    if isinstance(reference, dict):
        reference = [reference]
    return {item["schema:propertyID"]: item for item in reference}


# ── The record ────────────────────────────────────────────────────────────────

def test_a_component_property_accepts_the_statistics() -> None:
    report = validate_record_report(_electrode())
    assert list(report.errors) == [], report.errors


def test_a_cell_spec_property_accepts_the_statistics() -> None:
    """The SpecItem shape too, so a cell-level measured value can carry them."""
    spec = CellSpec(
        id=CELL_SPEC_IRI, name="Demo", manufacturer="Lab", model="D-1",
        format="coin", chemistry="li-ion", source=ProvenanceInfo(type="lab"),
        properties={"mass": {"value": 2.31, "unit": "g",
                             "standard_deviation": 0.04, "sample_count": 12}},
    )
    assert list(validate_record_report(spec.to_record()).errors) == []


def test_the_statistics_are_optional() -> None:
    """Nothing changes for a quantity that summarises nothing."""
    record = _electrode(loading={"value": 3.6472, "unit": "mg/cm2"})
    assert list(validate_record_report(record).errors) == []
    assert "schema:valueReference" not in _electrode_property_nodes(record)["ActiveMassLoading"]


def test_a_negative_standard_deviation_is_refused() -> None:
    """A dispersion is a magnitude; a negative one is a data-entry error."""
    record = _electrode(loading={**LOADING, "standard_deviation": -0.1})
    codes = {issue.code for issue in validate_record_report(record).errors}
    assert any(code.startswith("schema.") for code in codes), codes


@pytest.mark.parametrize("count", [0, -3])
def test_a_non_positive_sample_count_is_refused(count: int) -> None:
    """A statistic over zero members is not a statistic."""
    record = _electrode(loading={**LOADING, "sample_count": count})
    codes = {issue.code for issue in validate_record_report(record).errors}
    assert any(code.startswith("schema.") for code in codes), codes


def test_a_fractional_sample_count_is_refused() -> None:
    record = _electrode(loading={**LOADING, "sample_count": 8.5})
    codes = {issue.code for issue in validate_record_report(record).errors}
    assert any(code.startswith("schema.") for code in codes), codes


# ── Emission ──────────────────────────────────────────────────────────────────

def test_the_statistics_ride_the_same_node_as_the_value() -> None:
    """One quantity, not three properties.

    Emitting the spread as its own ``hasProperty`` entry would need a second EMMO
    class for the same measurand, which is the collision that pushed the number
    into prose in the first place.
    """
    node = _electrode_property_nodes(_electrode())["ActiveMassLoading"]

    assert node["hasNumericalPart"] == {"@type": "RealData", "hasNumberValue": 3.6472}
    assert node["hasMeasurementUnit"].endswith("MilliGramPerSquareCentiMetre")

    qualifiers = _qualifiers(node)
    assert qualifiers["standard_deviation"] == {
        "@type": "schema:PropertyValue",
        "schema:propertyID": "standard_deviation",
        "schema:value": 0.3017,
        "schema:unitText": "mg/cm2",
    }
    assert qualifiers["sample_count"] == {
        "@type": "schema:PropertyValue",
        "schema:propertyID": "sample_count",
        "schema:value": 8,
    }


def test_the_spread_carries_the_unit_and_the_count_does_not() -> None:
    """A standard deviation is in the unit of the value; a count is a count."""
    qualifiers = _qualifiers(_electrode_property_nodes(_electrode())["ActiveMassLoading"])
    assert "schema:unitText" in qualifiers["standard_deviation"]
    assert "schema:unitText" not in qualifiers["sample_count"]


def test_a_zero_standard_deviation_is_published_not_dropped() -> None:
    """Zero is a finding, not a missing value.

    Three of the corpus's twelve batches repeat one declared number on every cell
    row, so the spread is 0 by construction. Suppressing it would make a declared
    value indistinguishable from an unmeasured one.
    """
    record = _electrode(dry_thickness={"value": 42.0, "unit": "um",
                                       "standard_deviation": 0.0, "sample_count": 8})
    node = _electrode_property_nodes(record)["DryCoatingThickness"]
    assert _qualifiers(node)["standard_deviation"]["schema:value"] == 0.0


def test_a_count_without_a_spread_still_emits() -> None:
    """How many cells a mean was taken over is worth stating on its own."""
    record = _electrode(loading={"value": 3.6472, "unit": "mg/cm2", "sample_count": 8})
    qualifiers = _qualifiers(_electrode_property_nodes(record)["ActiveMassLoading"])
    assert set(qualifiers) == {"sample_count"}


def test_a_non_numeric_statistic_is_ignored_by_the_emitter() -> None:
    """The emitter never crashes a whole document on one bad cell of a table."""
    record = _electrode(loading={**LOADING, "standard_deviation": "unknown"})
    qualifiers = _qualifiers(_electrode_property_nodes(record)["ActiveMassLoading"])
    assert "standard_deviation" not in qualifiers
    assert "sample_count" in qualifiers


def test_a_percentage_spread_rescales_with_its_value() -> None:
    """Fractions are emitted on [0, 1]; a spread stated in % has to follow.

    Otherwise the node pairs a 0.043 mean with a 1.2 deviation and says the batch
    varies by more than it contains.
    """
    spec_record = create_electrode_spec(
        validate=False, uid="d7qr-n581-74c3-7g7r", name="LNMO cathode", kind="lnmo",
        coating={"component": {"active_material": [{"name": "LNMO"}]},
                 "property": {"porosity": {"value": 4.3, "unit": "%",
                                           "standard_deviation": 1.2, "sample_count": 8}}},
    )
    node = to_jsonld(spec_record, target="domain-battery")["@graph"][0]
    porosity = json.dumps(node)
    assert '"hasNumberValue": 0.043' in porosity
    assert '"schema:value": 0.012' in porosity


def test_the_cell_spec_emitter_carries_them_too() -> None:
    spec = CellSpec(
        id=CELL_SPEC_IRI, name="Demo", manufacturer="Lab", model="D-1",
        format="coin", chemistry="li-ion", source=ProvenanceInfo(type="lab"),
        properties={"mass": {"value": 2.31, "unit": "g",
                             "standard_deviation": 0.04, "sample_count": 12}},
    )
    node = record_to_jsonld(spec.to_record(), "cell-spec")
    properties = node["hasProperty"]
    if isinstance(properties, dict):
        properties = [properties]
    mass = next(prop for prop in properties if prop["skos:prefLabel"] == "Mass")
    qualifiers = _qualifiers(mass)
    assert qualifiers["standard_deviation"]["schema:value"] == 0.04
    assert qualifiers["sample_count"]["schema:value"] == 12


def test_the_statistics_do_not_disturb_the_value_or_the_save_gate() -> None:
    """Adding a spread changes nothing about the number it qualifies.

    The save gate's property mapping reads ``value``/``unit``, so a quantity with
    statistics must still map to the same class with no new warning — the failure
    mode the notes workaround was avoiding.
    """
    plain = _electrode_property_nodes(_electrode(loading={"value": 3.6472, "unit": "mg/cm2"}))
    annotated = _electrode_property_nodes(_electrode())

    plain_node = plain["ActiveMassLoading"]
    annotated_node = dict(annotated["ActiveMassLoading"])
    annotated_node.pop("schema:valueReference")
    assert annotated_node == plain_node

    report = validate_record_report(_electrode())
    assert [issue for issue in report.warnings if "loading" in issue.message] == []


def test_the_qualifier_terms_resolve_offline() -> None:
    """The emitter's qualifier stays prefixed schema.org; no class token is minted.

    The EMITTER writes ``schema:PropertyValue`` qualifiers with prefixed keys,
    so no PascalCase class token needs a context term — that decision holds.
    The bare snake_case keys are a different surface: canonical record bodies
    (served by the registry) carry ``standard_deviation``/``sample_count``
    directly, and with the ns# catch-all retired those keys must ground
    somewhere. They map to battinfo: slash placeholders matching the standing
    upstream ask (ontology-additions-needed.md section 5), which the next EMMO
    release drains.
    """
    v1 = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json")
        .read_text(encoding="utf-8")
    )["@context"]
    assert v1["schema"] == "https://schema.org/"
    for minted in ("StandardDeviation", "SampleCount"):
        assert minted not in v1, f"{minted} should not be a minted class token"
    assert v1["standard_deviation"] == "battinfo:standardDeviation"
    assert v1["sample_count"] == "battinfo:sampleCount"


def test_no_emmo_uncertainty_class_is_claimed() -> None:
    """The honest-option check, pinned so a later refactor cannot quietly relabel.

    ``MetrologicalUncertainty`` exists in the closure and is deliberately unused:
    a batch's spread is not a measurement uncertainty. If a real
    ``StandardDeviation`` is published upstream, this test is what should be
    changed, on purpose, alongside the emitter.
    """
    emitted = json.dumps(to_jsonld(_electrode(), target="domain-battery"))
    assert "MetrologicalUncertainty" not in emitted
    assert "hasMetrologicalUncertainty" not in emitted


# ── The prose form it replaces ────────────────────────────────────────────────

def test_the_notes_workaround_remains_valid() -> None:
    """Published records that say it in prose are not invalidated.

    The corpus is already on Zenodo. The structured keys are the way forward, not
    a reason to break what is out there — and a record may legitimately carry both
    while the prose is still the human-readable summary.
    """
    record = _electrode()
    record["notes"] = [
        "Active-mass loading: 3.6472 +/- 0.3017 mg/cm2 (mean +/- sample standard "
        "deviation, n = 8 cells; range 3.2844-4.0667 mg/cm2)."
    ]
    assert list(validate_record_report(record).errors) == []
