"""The BPX golden-fixture contract: one file, one record, nothing silently lost.

The fixture is a synthetic structural twin of a published full-DFN BattMo
export (Schmitt et al. 2026 — GPL-3.0, so the real file cannot be vendored):
Header lineage, all five Parameterisation blocks, curve-valued parameters, a
populated User-defined block, and a Validation section. The contract pinned
here: every value in the file is a claim in one part of one record, the
record's annex, or a NAMED warning, and ``to_bpx`` rebuilds the file's
Parameterisation and State exactly from that record.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop import from_bpx, from_bpx_parameters, upgrade_bpx  # noqa: E402
from battinfo.interop.bpx import to_bpx  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/0000-0000-0000-0000"
MATERIALS = {"negative": "graphite", "positive": "nmc811"}


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _record(source=FIXTURE, **kwargs) -> dict:
    kwargs.setdefault("cell_spec_id", CELL_SPEC_IRI)
    kwargs.setdefault("materials", MATERIALS)
    return from_bpx_parameters(source).to_parameter_set(**kwargs)


def _parts(record: dict) -> dict[str, list[dict]]:
    return {part["part"]: part["claims"] for part in record["parameter_set"]["parts"]}


def _as_v1(doc: dict) -> dict:
    """The same document in the BPX v1 layout (State block, BPX 1.1)."""
    out = upgrade_bpx(doc).document
    out["Header"]["BPX"] = "1.1.0"
    return out


def test_one_record_holds_every_part() -> None:
    record = _record()
    body = record["parameter_set"]
    assert [p["part"] for p in body["parts"]] == [
        "cell",
        "negative_material", "negative_electrode",
        "positive_material", "positive_electrode",
        "separator", "electrolyte", "state",
    ]
    assert {part: len(claims) for part, claims in _parts(record).items()} == {
        "cell": 8,
        "negative_material": 9,
        "negative_electrode": 5,
        "positive_material": 10,
        "positive_electrode": 5,
        "separator": 3,
        "electrolyte": 3,
        "state": 3,
    }
    by_part = {p["part"]: p for p in body["parts"]}
    assert by_part["negative_material"]["material_kind"] == "graphite"
    assert by_part["positive_material"]["material_kind"] == "nmc811"
    assert body["cell_spec_id"] == CELL_SPEC_IRI
    # Curves stay curves: both OCPs and both electrolyte transport tables.
    curves = {
        c["parameter"] for claims in _parts(record).values() for c in claims if "curve" in c
    }
    assert curves == {"ocp", "electrolyte_diffusivity", "ionic_conductivity"}
    # The Cell and State blocks are claims now, in the units BPX states them in.
    cell = {c["parameter"]: c["quantity"] for c in _parts(record)["cell"]}
    assert cell["electrode_area"]["unit"] == "m2"
    assert cell["electrode_pair_count"] == {"value": 20, "unit": "1"}
    state = {c["parameter"] for c in _parts(record)["state"]}
    assert state == {"initial_temperature", "ambient_temperature", "initial_concentration"}


def test_nothing_in_the_file_is_silently_dropped() -> None:
    """Every value is a claim, the annex, or a warning that NAMES it."""
    doc = _doc()
    res = from_bpx_parameters(FIXTURE)
    record = res.to_parameter_set(cell_spec_id=CELL_SPEC_IRI)
    warnings = " | ".join(res.warnings)
    claimed = sum(len(c) for c in _parts(record).values())
    read_as_claims = sum(
        len(doc["Parameterisation"][block])
        for block in ("Cell", "Negative electrode", "Positive electrode", "Separator", "Electrolyte")
    )
    assert claimed == read_as_claims
    assert not any("no parameter mapping" in w for w in res.warnings), res.warnings
    assert record["parameter_set"]["annex"] == doc["Parameterisation"]["User-defined"]
    for key in doc["Parameterisation"]["User-defined"]:
        assert key in warnings, f"User-defined key {key!r} not named"
    for series in doc["Validation"]:
        assert series in warnings, f"Validation series {series!r} not named"


def test_blended_hysteresis_and_degradation_are_named_not_dropped() -> None:
    doc = _as_v1(_doc())
    negative = doc["Parameterisation"]["Negative electrode"]
    negative["Particle"] = {
        "Primary": {"Particle radius [m]": 1e-5, "OCP [V]": "0.1 + 0 * x"},
        "Secondary": {"Particle radius [m]": 2e-6},
    }
    doc["State"]["Initial conditions"]["Initial hysteresis state: Negative electrode"] = 1.0
    doc["State"]["Degradation"] = {"LLI": 0.01, "LAM: Negative electrode": 0.02}
    doc["State"]["Magic"] = {"x": 1}
    warnings = "\n".join(from_bpx_parameters(doc).warnings)
    assert "Negative electrode Particle block" in warnings
    assert "Primary: Particle radius [m], OCP [V]" in warnings
    assert "Secondary: Particle radius [m]" in warnings
    for name in (
        "Initial conditions.Initial hysteresis state: Negative electrode",
        "Degradation.LLI",
        "Degradation.LAM: Negative electrode",
        "Magic.x",
    ):
        assert name in warnings, name


def test_every_unknown_field_is_named() -> None:
    doc = _doc()
    extra = [f"Mystery field {i} [X]" for i in range(12)]
    for name in extra:
        doc["Parameterisation"]["Separator"][name] = 1.0
    warning = next(w for w in from_bpx_parameters(doc).warnings if "Separator fields" in w)
    for name in extra:
        assert name in warning
    assert "…" not in warning and "..." not in warning


def test_editing_the_import_cannot_change_the_record() -> None:
    res = from_bpx_parameters(FIXTURE)
    before = res.to_parameter_set(virtual_cell=True)
    res.parts[1]["claims"][0]["quantity"]["value"] = 123.0
    res.parts.pop()
    res.annex["Injected"] = 1.0
    after = res.to_parameter_set(virtual_cell=True)
    assert after["parameter_set"]["parts"] == before["parameter_set"]["parts"]
    assert after["parameter_set"]["annex"] == before["parameter_set"]["annex"]
    assert after["parameter_set"]["id"] == before["parameter_set"]["id"]


def test_the_cell_link_is_stated_never_guessed() -> None:
    res = from_bpx_parameters(FIXTURE)
    with pytest.raises(ValueError, match="exactly one of cell_spec_id"):
        res.to_parameter_set()
    with pytest.raises(ValueError, match="exactly one of cell_spec_id"):
        res.to_parameter_set(cell_spec_id=CELL_SPEC_IRI, virtual_cell=True)
    instance = res.to_parameter_set(cell_instance_id="https://w3id.org/battinfo/cell/0000-0000-0000-0001")
    assert instance["parameter_set"]["cell_instance_id"].endswith("0000-0000-0000-0001")
    virtual = res.to_parameter_set(virtual_cell=True)
    assert virtual["parameter_set"]["virtual_cell"] is True
    assert "cell_spec_id" not in virtual["parameter_set"]


def test_an_unnamed_material_is_said_not_skipped() -> None:
    res = from_bpx_parameters(FIXTURE)
    record = res.to_parameter_set(virtual_cell=True, materials={"negative": "graphite"})
    by_part = {p["part"]: p for p in record["parameter_set"]["parts"]}
    assert "material_kind" not in by_part["positive_material"]
    assert by_part["positive_material"]["claims"]
    assert any("positive electrode material part names no material" in w for w in res.warnings)
    with pytest.raises(ValueError, match="'negative' and 'positive'"):
        res.to_parameter_set(virtual_cell=True, materials={"separator": "graphite"})


def test_header_lineage_lands_on_the_record() -> None:
    record = _record()
    body = record["parameter_set"]
    assert body["name"] == "Synthetic DFN parameter set (golden fixture)"
    assert body["description"].startswith("Structural twin")
    assert body["model_context"] == {
        "tool": "BPX",
        "name": "Synthetic DFN parameter set (golden fixture)",
        "model": "DFN",
        "version": "1.0",
        "layout": "v0",  # declares 1.0, keeps the v0.x layout
    }
    # Header.References is free text here (not a URL/DOI), so it rides a
    # note verbatim — provenance.citation is URI-typed by the schema.
    assert any("Schmitt et al. 2026" in n for n in record.get("notes", []))


def test_caller_supplied_lineage_wins_over_the_header() -> None:
    record = _record(
        description="Curated re-description.",
        citation="10.5281/zenodo.0000000",
        name="A curated name",
        license="cc-by-4.0",
    )
    assert record["parameter_set"]["description"] == "Curated re-description."
    assert record["parameter_set"]["name"] == "A curated name"
    assert record["provenance"]["citation"] == "https://doi.org/10.5281/zenodo.0000000"
    assert record["license"] == "cc-by-4.0"


def test_round_trip_export_is_exact() -> None:
    """to_bpx(record) gives back the file's Parameterisation and State, value for value."""
    out = to_bpx(_record())
    # The fixture, like the BattMo export it mirrors, declares BPX 1.0 but
    # keeps the v0.x layout. The export declares the same version and follows
    # that version's real layout, so the reference is the fixture moved into it.
    reference = upgrade_bpx(_doc()).document
    assert json.dumps(out.bpx["Parameterisation"], sort_keys=True) == json.dumps(
        reference["Parameterisation"], sort_keys=True
    )
    assert out.bpx["State"] == reference["State"]
    header = out.bpx["Header"]
    assert header["Model"] == "DFN"
    assert header["BPX"] == "1.0"  # Header.BPX is always written as a string
    assert header["Title"] == _doc()["Header"]["Title"]
    assert "Schmitt et al. 2026" in header["References"]
    assert not out.missing_required


@pytest.mark.parametrize("bpx_version", ["1.0", "1.1.0", "0.4.0"])
def test_exported_document_validates_with_the_bpx_package(bpx_version: str) -> None:
    """The export drives real tools: the official bpx parser accepts it."""
    bpx_lib = pytest.importorskip("bpx")
    out = to_bpx(_record(), bpx_version=bpx_version)
    assert ("State" in out.bpx) is (bpx_version != "0.4.0")
    parsed = bpx_lib.parse_bpx_obj(copy.deepcopy(out.bpx))
    assert parsed.header.model == "DFN"


def test_a_0x_export_keeps_the_0x_layout() -> None:
    doc = _doc()
    doc["Parameterisation"]["Cell"]["Thermal conductivity [W.m-1.K-1]"] = 1.48
    out = to_bpx(_record(doc), bpx_version="0.4.0").bpx
    assert "State" not in out
    assert out["Parameterisation"]["Cell"]["Initial temperature [K]"] == 298.15
    assert out["Parameterisation"]["Cell"]["Thermal conductivity [W.m-1.K-1]"] == 1.48
    assert out["Parameterisation"]["Electrolyte"]["Initial concentration [mol.m-3]"] == 1000.0
    # The same record at 1.1.0: the State block, and the conductivity where
    # the v1 parser asks for it.
    v1 = to_bpx(_record(doc), bpx_version="1.1.0").bpx
    assert "Thermal conductivity [W.m-1.K-1]" not in v1["Parameterisation"]["Cell"]
    assert v1["Parameterisation"]["User-defined"]["Thermal conductivity [W.m-1.K-1]"] == 1.48


def test_state_values_with_no_0x_home_are_named_on_a_0x_export() -> None:
    doc = _as_v1(_doc())
    doc["State"]["Initial conditions"]["Initial state-of-charge"] = 0.5
    doc["State"]["Thermal environment"]["Heat transfer coefficient [W.m-2.K-1]"] = 10.0
    record = _record(doc)
    assert {c["parameter"] for c in _parts(record)["state"]} >= {"initial_soc", "heat_transfer_coefficient"}
    out = to_bpx(record, bpx_version="0.4.0")
    joined = " ".join(out.warnings)
    assert "Initial conditions.Initial state-of-charge" in joined
    assert "Thermal environment.Heat transfer coefficient [W.m-2.K-1]" in joined
    back = to_bpx(record)
    assert back.bpx["State"] == doc["State"]


def test_bpx_v1_state_round_trips() -> None:
    """A BPX v1 State block reads as the state part and comes back intact."""
    doc = _as_v1(_doc())
    record = _record(doc)
    state = {c["parameter"]: c["quantity"]["value"] for c in _parts(record)["state"]}
    assert state["initial_concentration"] == (
        doc["State"]["Initial conditions"]["Initial electrolyte concentration [mol.m-3]"]
    )
    out = to_bpx(record)
    assert out.bpx["State"] == doc["State"]
    assert out.bpx["Header"]["BPX"] == "1.1.0"
    # Either layout gives the same parts, except the initial state of charge
    # the v1 copy states (the conversion added it, as the bpx package does).
    v1_parts = _parts(record)
    v1_parts["state"] = [c for c in v1_parts["state"] if c["parameter"] != "initial_soc"]
    assert v1_parts == _parts(_record())


def test_a_unit_other_than_bpx_states_is_converted_on_export() -> None:
    from battinfo.api import create_parameter_set

    record = _record()
    body = copy.deepcopy(record["parameter_set"])
    cell = next(p for p in body["parts"] if p["part"] == "cell")
    for claim in cell["claims"]:
        if claim["parameter"] == "nominal_capacity":
            claim["quantity"] = {"value": 1500.0, "unit": "mAh"}
    edited = create_parameter_set(
        name=body["name"], parts=body["parts"], parameters_sha256=body["parameters_sha256"],
        cell_spec_id=CELL_SPEC_IRI, model_context=body["model_context"],
    )
    out = to_bpx(edited)
    assert out.bpx["Parameterisation"]["Cell"]["Nominal cell capacity [A.h]"] == pytest.approx(1.5)


def test_emitted_jsonld_uses_the_records_context_and_absolute_license() -> None:
    """Parameter-set records are the BPX Metadata payload: they must expand
    against the hosted, versioned records context, and a license slug must
    never emit as a relative IRI."""
    from battinfo.jsonld import record_to_jsonld

    record = _record()
    record["license"] = "cc-by-sa-4.0"

    hosted = record_to_jsonld(record, "parameter-set")
    assert hosted["@context"] == "https://w3id.org/battinfo/context/records/v1.json"
    assert hosted["dcterms:license"] == {"@id": "https://spdx.org/licenses/CC-BY-SA-4.0.html"}

    inline = record_to_jsonld(record, "parameter-set", context="inline")
    context = inline["@context"]
    assert isinstance(context, dict)

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

    terms: set[str] = set()
    bare_terms({k: v for k, v in inline.items() if k != "@context"}, terms)
    unresolved = sorted(t for t in terms if t not in context)
    assert not unresolved, f"terms missing from the inline records context: {unresolved}"


def test_reference_temperature_survives_the_cell_spec_round_trip() -> None:
    """The cell-spec export keeps a file's own reference temperature: the
    298.15 K convention fills the field only when nothing carries it."""
    doc = _doc()
    doc["Parameterisation"]["Cell"]["Reference temperature [K]"] = 310.15
    cell = from_bpx(doc)
    spec_record = {
        "schema_version": "0.2.0",
        "cell_spec": {"name": "Golden fixture cell", "cell_format": "pouch"},
        "properties": cell.specs,
    }

    out = to_bpx(spec_record, cell_extras=cell.extras)
    assert out.bpx["Parameterisation"]["Cell"]["Reference temperature [K]"] == 310.15

    # The convention still fills the gap when nothing carries the field.
    out_default = to_bpx(spec_record)
    assert out_default.bpx["Parameterisation"]["Cell"]["Reference temperature [K]"] == 298.15

    # An explicit float forces the value over imported extras; None emits
    # none of our own (extras would still pass through verbatim).
    out_forced = to_bpx(spec_record, cell_extras=cell.extras, reference_temperature_k=305.0)
    assert out_forced.bpx["Parameterisation"]["Cell"]["Reference temperature [K]"] == 305.0
    out_none = to_bpx(spec_record, reference_temperature_k=None)
    assert "Reference temperature [K]" not in out_none.bpx["Parameterisation"]["Cell"]


def test_from_bpx_folds_a_v1_state_block_into_cell_extras() -> None:
    """The cell importer still reads v1 temperatures, and names what it skips."""
    doc = _as_v1(_doc())
    doc["State"]["Initial conditions"]["Initial state of charge"] = 0.5
    doc["State"]["Magic"] = {"x": 1}
    cell = from_bpx(doc)
    assert cell.extras["Initial temperature [K]"] == doc["State"]["Initial conditions"]["Initial temperature [K]"]
    assert cell.extras["Ambient temperature [K]"] == doc["State"]["Thermal environment"]["Ambient temperature [K]"]
    joined = "\n".join(cell.warnings)
    assert "Initial conditions.Initial state of charge" in joined
    assert "Magic" in joined
