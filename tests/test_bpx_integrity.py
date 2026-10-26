"""BPX parameter files: the integrity rules from the 2026-10-11 red team.

Each test reproduces one finding and pins its fix:

- a runnable copy is bound to its source: it must be the layout conversion of
  the file the parameters were read from, byte-checked (F1);
- the v0.x -> v1 layout conversion is one standard-library function, used by
  ``upgrade_bpx`` and by every v1 export of a v0.x-layout record, and adds the
  State values the bpx package's own migration adds (F2);
- ``to_bpx`` writes numbers in the units BPX states them in, or refuses (F3);
- nothing the import does not read is lost in silence (F4);
- two claims of one EMMO class stay apart in RDF (F5);
- the record validator holds the integrity rules under every policy (F6);
- a corrected file names the record it supersedes (F7);
- a file is parsed strictly (F8), errors say what to do (F9), and the
  parser's warnings are kept whole (F10).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo._bpx_layout import to_v1_layout  # noqa: E402
from battinfo.api import create_parameter_set  # noqa: E402
from battinfo.interop import (  # noqa: E402
    bpx_content_digest,
    bpx_file_distribution,
    check_bpx,
    from_bpx_parameters,
    upgrade_bpx,
)
from battinfo.interop.bpx import to_bpx  # noqa: E402
from battinfo.validate import validate_record_report  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples" / "parameter-set"
SOURCE_URL = "https://files.example.org/parameter_sets/x/source.bpx.json"
RUNNABLE_URL = "https://files.example.org/parameter_sets/x/runnable.bpx.json"
MIRROR_URL = "https://mirror.example.org/x/source.bpx.json"
OLD_IRI = "https://w3id.org/battinfo/spec/0000-0000-0000-0001"
NEWER_OLD_IRI = "https://w3id.org/battinfo/dataset/0000-0000-0000-0002"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _has_bpx() -> bool:
    try:
        import bpx  # noqa: F401
    except ImportError:
        return False
    return True


def _example(name: str) -> dict:
    for path in sorted(EXAMPLES.glob("parameter-set-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["parameter_set"].get("name") == name:
            return record
    raise AssertionError(f"no packaged example named {name!r}")


def _v1_doc() -> dict:
    """The fixture in the v1 layout, declaring BPX 1.1.0, Validation dropped."""
    doc = upgrade_bpx(_doc()).document
    doc.pop("Validation")
    return doc


def _parts(record: dict) -> dict[str, list[dict]]:
    return {part["part"]: part["claims"] for part in record["parameter_set"]["parts"]}


# ── F1: a runnable copy is the layout conversion of its source ───────────────


def _source_and_runnable(runnable_bytes: bytes) -> tuple[dict, dict]:
    source = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    runnable = bpx_file_distribution(
        runnable_bytes,
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion="layout only",
    )
    return source, runnable


def test_a_runnable_built_from_another_file_is_refused() -> None:
    # The red team's reproduction: a "runnable" that is the fixture with one
    # parameter changed tenfold, claiming to be a layout conversion.
    other = upgrade_bpx(_doc()).document
    other["Parameterisation"]["Cell"]["Electrode area [m2]"] *= 10
    other_bytes = json.dumps(other, indent=2).encode("utf-8")
    source, runnable = _source_and_runnable(other_bytes)
    res = from_bpx_parameters(FIXTURE)
    with pytest.raises(ValueError, match="not the layout conversion of this file") as caught:
        res.to_parameter_set(virtual_cell=True, distributions=[source, runnable], runnable_file=other_bytes)
    assert "Parameterisation.Cell.Electrode area [m2]" in str(caught.value)


def test_the_runnable_file_is_required_and_byte_checked() -> None:
    good = upgrade_bpx(FIXTURE).to_json().encode("utf-8")
    source, runnable = _source_and_runnable(good)
    res = from_bpx_parameters(FIXTURE)
    with pytest.raises(ValueError, match="pass runnable_file="):
        res.to_parameter_set(virtual_cell=True, distributions=[source, runnable])
    # The same parameters in other bytes are not the attached file.
    reindented = upgrade_bpx(FIXTURE).to_json(indent=4).encode("utf-8")
    with pytest.raises(ValueError, match="runnable_file is not the attached runnable copy"):
        res.to_parameter_set(virtual_cell=True, distributions=[source, runnable], runnable_file=reindented)
    with pytest.raises(ValueError, match="distributions has none"):
        res.to_parameter_set(virtual_cell=True, distributions=[source], runnable_file=good)
    record = res.to_parameter_set(virtual_cell=True, distributions=[source, runnable], runnable_file=good)
    assert [d["role"] for d in record["parameter_set"]["distributions"]] == ["source", "runnable"]


def test_a_runnable_must_use_the_default_target_version() -> None:
    # The check is against upgrade_bpx(source) as published; another header
    # version is other parameters (the header is part of the digest).
    other_version = upgrade_bpx(FIXTURE, target_version="1.0.0").to_json().encode("utf-8")
    source, runnable = _source_and_runnable(other_version)
    with pytest.raises(ValueError, match="Header.BPX"):
        from_bpx_parameters(FIXTURE).to_parameter_set(
            virtual_cell=True, distributions=[source, runnable], runnable_file=other_version
        )


# ── F2: one layout conversion, with the bpx package's State values ───────────


def test_the_layout_module_imports_only_the_standard_library() -> None:
    # The registry vendors both modules verbatim: they must not import battinfo
    # or any third-party package.
    for name in ("_bpx_layout.py", "_jcs.py"):
        tree = ast.parse((ROOT / "src" / "battinfo" / name).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{name} uses a relative import"
                imported.add((node.module or "").split(".")[0])
        assert imported <= set(sys.stdlib_module_names) | {"__future__"}, (name, imported)


def test_upgrade_adds_the_state_values_the_bpx_migration_adds() -> None:
    doc = _doc()
    del doc["Parameterisation"]["Cell"]["Ambient temperature [K]"]
    del doc["Parameterisation"]["Cell"]["Initial temperature [K]"]
    doc["Parameterisation"]["Cell"]["Reference temperature [K]"] = 303.15
    result = upgrade_bpx(doc)
    state = result.document["State"]
    assert state["Initial conditions"]["Initial state-of-charge"] == 1
    assert state["Thermal environment"]["Ambient temperature [K]"] == 303.15  # from the reference
    assert state["Initial conditions"]["Initial temperature [K]"] == 303.15  # the ambient one
    assert len(result.added) == 3
    assert any("Cell.Reference temperature [K]" in added for added in result.added)
    # Nothing is invented for the electrolyte concentration.
    no_electrolyte = _doc()
    del no_electrolyte["Parameterisation"]["Electrolyte"]["Initial concentration [mol.m-3]"]
    assert (
        "Initial electrolyte concentration [mol.m-3]"
        not in (upgrade_bpx(no_electrolyte).document["State"]["Initial conditions"])
    )
    # Without any temperature the bpx default, 298.15 K.
    bare = _doc()
    for key in ("Ambient temperature [K]", "Initial temperature [K]", "Reference temperature [K]"):
        del bare["Parameterisation"]["Cell"][key]
    assert upgrade_bpx(bare).document["State"]["Thermal environment"]["Ambient temperature [K]"] == 298.15


def test_the_conversion_matches_the_bpx_package_on_0x_files() -> None:
    bpx = pytest.importorskip("bpx")
    for name in ("BPX NMC111-Si pouch hysteresis", "BPX NMC111 pouch", "BPX LFP 18650"):
        own = to_bpx(_example(name)).bpx  # the 0.x file, as published
        ours, changes = to_v1_layout(own, "1.1.0")
        official = bpx.convert_v0_to_v1(copy.deepcopy(own))
        assert ours["State"] == official["State"], name
        # One difference, on purpose: the lumped thermal conductivity moves
        # to User-defined (the bpx parser asks for it there) instead of being dropped.
        conductivity = "Thermal conductivity [W.m-1.K-1]"
        held = ours["Parameterisation"].get("User-defined", {}).pop(conductivity, None)
        assert (held is not None) == (conductivity in own["Parameterisation"]["Cell"])
        if not ours["Parameterisation"].get("User-defined", True):
            del ours["Parameterisation"]["User-defined"]
        assert ours["Parameterisation"] == official["Parameterisation"], name
        assert all(change in json.dumps(changes) for change in ("Initial state-of-charge = 1",))


def test_a_v1_export_of_a_0x_record_is_the_upgraded_file() -> None:
    # The red team's reproduction: the FaradayInstitution hysteresis example
    # (BPX 0.4.0) exported at 1.1.0 lacked the initial state of charge the
    # official migration adds, and PyBaMM gave 13.1385 Ah at 1C instead of the
    # original's 12.2539 Ah. The export now carries the same State as the
    # bpx package's own conversion of the original file.
    record = _example("BPX NMC111-Si pouch hysteresis")
    original = to_bpx(record).bpx
    assert original["Header"]["BPX"] == "0.4.0" and "State" not in original
    exported = to_bpx(record, bpx_version="1.1.0")
    expected, _ = to_v1_layout(original, "1.1.0")
    assert exported.bpx == expected
    assert exported.bpx["State"]["Initial conditions"]["Initial state-of-charge"] == 1
    assert any("Initial state-of-charge = 1" in w and "v0-to-v1 migration" in w for w in exported.warnings)
    assert exported.complete


def test_a_record_of_a_v0_layout_v1_file_exports_like_its_runnable_copy() -> None:
    # The fixture declares BPX 1.0 but keeps the v0.x layout (as the Schmitt et
    # al. 2026 file does). model_context.layout says so, so the record's 1.x
    # export makes the same conversion as the runnable copy.
    res = from_bpx_parameters(FIXTURE)
    assert any("keeps the v0.x layout" in w for w in res.warnings)
    record = res.to_parameter_set(virtual_cell=True)
    context = record["parameter_set"]["model_context"]
    assert (context["version"], context["layout"]) == ("1.0", "v0")
    assert not any(note.startswith("BPX layout") for note in record.get("notes", []))
    exported = to_bpx(record, bpx_version="1.1.0").bpx
    runnable = upgrade_bpx(FIXTURE).document
    runnable.pop("Validation")
    assert exported == runnable


def test_the_layout_is_the_one_the_file_uses() -> None:
    assert _record()["parameter_set"]["model_context"]["layout"] == "v1"
    legacy = to_bpx(_example("BPX NMC111 pouch")).bpx  # a 0.1.0 file
    assert (
        from_bpx_parameters(legacy).to_parameter_set(virtual_cell=True)["parameter_set"]["model_context"]["layout"]
        == "v0"
    )
    # The field decides the export, not the version: the same record told
    # "v1" writes its State as it holds it, with nothing added.
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    record["parameter_set"]["model_context"]["layout"] = "v1"
    state = to_bpx(record, bpx_version="1.1.0").bpx["State"]
    assert "Initial state-of-charge" not in state["Initial conditions"]
    # A hand-built record without the field goes by its version.
    del record["parameter_set"]["model_context"]["layout"]
    assert "Initial state-of-charge" not in to_bpx(record, bpx_version="1.1.0").bpx["State"]["Initial conditions"]
    record["parameter_set"]["model_context"]["version"] = "0.4.0"
    assert to_bpx(record, bpx_version="1.1.0").bpx["State"]["Initial conditions"]["Initial state-of-charge"] == 1
    bad = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    bad["parameter_set"]["model_context"]["layout"] = "v2"
    assert not validate_record_report(bad).ok


# ── F3: numbers in the units BPX states ──────────────────────────────────────


def _with_claim(record: dict, part: str, parameter: str, body: dict) -> dict:
    out = copy.deepcopy(record)
    for p in out["parameter_set"]["parts"]:
        if p["part"] != part:
            continue
        for claim in p["claims"]:
            if claim["parameter"] == parameter:
                for key in ("quantity", "curve", "expression"):
                    claim.pop(key, None)
                claim.update(body)
                return out
        p["claims"].append({"parameter": parameter, **body})
        return out
    raise KeyError(part)


def _record() -> dict:
    return from_bpx_parameters(_v1_doc()).to_parameter_set(virtual_cell=True)


def test_a_curve_x_axis_is_converted_or_refused() -> None:
    concentrations = [0.0, 0.5, 1.0, 2.0]
    conductivity = [0.0, 0.8, 1.0, 0.7]
    mol_per_litre = _with_claim(
        _record(),
        "electrolyte",
        "ionic_conductivity",
        {
            "curve": {
                "x_quantity": "concentration",
                "x_unit": "mol/L",
                "x": concentrations,
                "y": conductivity,
                "y_unit": "S/m",
            }
        },
    )
    table = to_bpx(mol_per_litre, bpx_version="1.1.0").bpx["Parameterisation"]["Electrolyte"]["Conductivity [S.m-1]"]
    assert table == {"x": [0.0, 500.0, 1000.0, 2000.0], "y": conductivity}

    unknown = _with_claim(
        _record(),
        "electrolyte",
        "ionic_conductivity",
        {
            "curve": {
                "x_quantity": "concentration",
                "x_unit": "furlongs",
                "x": concentrations,
                "y": conductivity,
                "y_unit": "S/m",
            }
        },
    )
    with pytest.raises(ValueError, match="claim 'ionic_conductivity' \\(electrolyte\\) x axis is in 'furlongs'"):
        to_bpx(unknown, bpx_version="1.1.0")
    unstated = _with_claim(
        _record(),
        "electrolyte",
        "ionic_conductivity",
        {
            "curve": {
                "x_quantity": "concentration",
                "x": concentrations,
                "y": conductivity,
                "y_unit": "S/m",
            }
        },
    )
    with pytest.raises(ValueError, match="no x_unit"):
        to_bpx(unstated, bpx_version="1.1.0")


def test_a_curve_against_another_quantity_is_refused() -> None:
    record = _with_claim(
        _record(),
        "negative_material",
        "solid_diffusivity",
        {
            "curve": {
                "x_quantity": "temperature",
                "x_unit": "K",
                "x": [273.0, 298.0],
                "y": [1e-15, 3e-15],
                "y_unit": "m2/s",
            }
        },
    )
    with pytest.raises(ValueError, match="against 'temperature'.*tabulates against 'stoichiometry'"):
        to_bpx(record, bpx_version="1.1.0")


@pytest.mark.parametrize(
    ("part", "parameter", "quantity", "field", "expected"),
    [
        (
            "state",
            "initial_temperature",
            {"value": 25, "unit": "degC"},
            ("State", "Initial conditions", "Initial temperature [K]"),
            298.15,
        ),
        (
            "negative_electrode",
            "porosity",
            {"value": 33, "unit": "%"},
            ("Parameterisation", "Negative electrode", "Porosity"),
            0.33,
        ),
        ("cell", "density", {"value": 1.847}, ("Parameterisation", "Cell", "Density [kg.m-3]"), 1847.0),
        (
            "cell",
            "nominal_capacity",
            {"value": 12500, "unit": "mAh"},
            ("Parameterisation", "Cell", "Nominal cell capacity [A.h]"),
            12.5,
        ),
        (
            "state",
            "initial_concentration",
            {"value": 1.0, "unit": "mol/L"},
            ("State", "Initial conditions", "Initial electrolyte concentration [mol.m-3]"),
            1000.0,
        ),
    ],
)
def test_a_quantity_is_converted_to_the_bpx_unit(part, parameter, quantity, field, expected) -> None:
    record = _with_claim(_record(), part, parameter, {"quantity": quantity})
    out = to_bpx(record, bpx_version="1.1.0").bpx
    value = out[field[0]][field[1]][field[2]]
    assert value == pytest.approx(expected)


def test_a_quantity_with_no_known_conversion_is_refused() -> None:
    record = _with_claim(_record(), "cell", "nominal_capacity", {"quantity": {"value": 1.0, "unit": "coulomb-ish"}})
    with pytest.raises(ValueError, match="claim 'nominal_capacity' \\(cell\\) is in 'coulomb-ish'"):
        to_bpx(record)


def test_ocp_branches_go_to_their_v1_fields_and_not_to_0x() -> None:
    curve = {"x_quantity": "stoichiometry", "x": [0.0, 0.5, 1.0], "y": [1.0, 0.2, 0.05], "y_unit": "V"}
    record = copy.deepcopy(_record())
    negative = next(p for p in record["parameter_set"]["parts"] if p["part"] == "negative_material")
    negative["claims"].append({"parameter": "ocp", "curve": {**curve, "branch": "delithiation"}})
    negative["claims"].append({"parameter": "ocp", "curve": {**curve, "branch": "lithiation"}})
    block = to_bpx(record, bpx_version="1.1.0").bpx["Parameterisation"]["Negative electrode"]
    assert block["OCP (delithiation) [V]"] == {"x": curve["x"], "y": curve["y"]}
    assert block["OCP (lithiation) [V]"] == {"x": curve["x"], "y": curve["y"]}
    assert block["OCP [V]"] == _v1_doc()["Parameterisation"]["Negative electrode"]["OCP [V]"]
    with pytest.raises(ValueError, match="delithiation branch.*export at a 1.x version"):
        to_bpx(record, bpx_version="0.4.0")


def test_the_header_version_is_a_string() -> None:
    for version in (None, "1.0", "0.4.0"):
        assert isinstance(to_bpx(_record(), bpx_version=version).bpx["Header"]["BPX"], str)
    cell_spec = {"cell_spec": {"name": "x"}, "properties": {"nominal_capacity": {"value": 1.0, "unit": "Ah"}}}
    assert to_bpx(cell_spec, bpx_version="0.4").bpx["Header"]["BPX"] == "0.4"


# ── F4: nothing lost in silence ──────────────────────────────────────────────


def _hysteresis_doc() -> dict:
    doc = _v1_doc()
    negative = doc["Parameterisation"]["Negative electrode"]
    negative["OCP (lithiation) [V]"] = {"x": [0.0, 0.5, 1.0], "y": [0.9, 0.15, 0.04]}
    negative["OCP (delithiation) [V]"] = {"x": [0.0, 0.5, 1.0], "y": [1.0, 0.2, 0.05]}
    negative["OCP hysteresis decay constant"] = 0.1
    doc["State"]["Initial conditions"]["Initial hysteresis state: Negative electrode"] = 1.0
    doc["State"]["Degradation"] = {"LLI": 0.05, "LAM: Positive electrode": 0.02, "LAM: Negative electrode": 0.01}
    return doc


def test_hysteresis_values_are_claims_and_the_rest_is_recorded() -> None:
    doc = _hysteresis_doc()
    res = from_bpx_parameters(doc)
    record = res.to_parameter_set(virtual_cell=True)
    negative = _parts(record)["negative_material"]
    branches = sorted(c["curve"].get("branch", "") for c in negative if c["parameter"] == "ocp")
    assert branches == ["", "delithiation", "lithiation"]
    assert {
        "parameter": "ocp_hysteresis_decay_constant",
        "quantity": {"value": 0.1, "unit": "1"},
        "provenance_class": "fitted",
    } in negative
    assert record["parameter_set"]["not_imported"] == [
        "State/Initial conditions/Initial hysteresis state: Negative electrode",
        "State/Degradation",
    ]
    assert res.not_imported == record["parameter_set"]["not_imported"]
    assert validate_record_report(record).ok

    exported = to_bpx(record)
    assert exported.complete is False
    assert any("State/Degradation" in w and "does not hold" in w for w in exported.warnings)
    expected = copy.deepcopy(doc)
    del expected["State"]["Degradation"]
    del expected["State"]["Initial conditions"]["Initial hysteresis state: Negative electrode"]
    assert exported.bpx["Parameterisation"] == expected["Parameterisation"]
    assert exported.bpx["State"] == expected["State"]
    with pytest.raises(ValueError, match="strict=True.*not imported: State/Degradation"):
        to_bpx(record, strict=True)


def test_not_imported_names_every_kind_of_unread_value() -> None:
    doc = _doc()
    doc["Header"]["X-tool-note"] = "made by hand"
    doc["Parameterisation"]["Negative electrode"]["Particle"] = {"Primary": {"Particle radius [m]": 1e-5}}
    doc["Parameterisation"]["Separator"]["Mystery [X]"] = 1.0
    doc["Parameterisation"]["Thermal"] = {"k": 1.0}
    paths = from_bpx_parameters(doc).not_imported
    for expected in (
        "Header/X-tool-note",
        "Parameterisation/Negative electrode/Particle",
        "Parameterisation/Separator/Mystery [X]",
        "Parameterisation/Thermal",
        "Validation",
    ):
        assert expected in paths


def test_an_export_the_official_parser_rejects_says_so() -> None:
    pytest.importorskip("bpx")
    record = copy.deepcopy(_record())
    cell = next(p for p in record["parameter_set"]["parts"] if p["part"] == "cell")
    cell["claims"] = [c for c in cell["claims"] if c["parameter"] != "electrode_area"]
    out = to_bpx(record)
    assert any(w.startswith("The official bpx parser rejects this document") for w in out.warnings)
    assert not any("rejects" in w for w in to_bpx(_record()).warnings)


def test_to_bpx_takes_records_it_can_export_only() -> None:
    material = {"schema_version": "0.2.0", "material_spec": {"name": "x"}, "provenance": {}}
    with pytest.raises(TypeError, match="material-spec record"):
        to_bpx(material)
    with pytest.raises(TypeError, match="none of them"):
        to_bpx({"title": "not a record"})
    with pytest.raises(TypeError):
        to_bpx(["a list"])
    record = _record()
    resource = {"resource_type": "parameter_set", "semantic_payload": {"battinfo_records": {"parameter_set": record}}}
    assert to_bpx(resource).bpx == to_bpx(record).bpx
    assert to_bpx({"resource": resource}).bpx == to_bpx(record).bpx


# ── F5: claims of one EMMO class stay apart in RDF ───────────────────────────


def test_claims_name_their_parameter_in_rdf() -> None:
    pyld = pytest.importorskip("pyld")
    from battinfo.jsonld import record_to_jsonld

    doc = record_to_jsonld(_record(), "parameter-set", context="inline")
    quads = pyld.jsonld.to_rdf(doc, {"format": "application/n-quads"})
    property_id = "<https://schema.org/propertyID>"
    subjects: dict[str, str] = {}
    types: dict[str, set[str]] = {}
    for line in quads.splitlines():
        subject, predicate, rest = line.split(" ", 2)
        if predicate == property_id:
            subjects[rest.rsplit(" ", 1)[0].strip('"')] = subject
        elif predicate == "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>":
            types.setdefault(subject, set()).add(rest.rsplit(" ", 1)[0])
    area, surface = subjects["electrode_area"], subjects["external_surface_area"]
    assert area != surface
    assert types[area] & types[surface]  # same EMMO class (Area), told apart by propertyID
    assert "ocp" in subjects  # curve claims carry it too


# ── F6: integrity rules under every policy ───────────────────────────────────


def _file_record(**kwargs) -> dict:
    source = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    return from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, distributions=[source], **kwargs)


@pytest.mark.parametrize("policy", ["default", "strict", "publisher", "ingest"])
def test_an_iri_its_fingerprint_does_not_give_is_an_error(policy: str) -> None:
    record = _file_record()
    hand_built = copy.deepcopy(record)
    hand_built["parameter_set"]["parameters_sha256"] = "a" * 64
    report = validate_record_report(hand_built, policy=policy)
    assert "semantic.parameter_file_id_mismatch" in {i.code for i in report.errors}
    assert validate_record_report(record, policy=policy).ok


@pytest.mark.parametrize("policy", ["default", "strict", "publisher"])
def test_file_rules_are_errors_under_every_policy(policy: str) -> None:
    record = _file_record()
    source = record["parameter_set"]["distributions"][0]
    mirror = {
        **source,
        "role": "mirror",
        "content_url": MIRROR_URL,
        "checksum": {"algorithm": "sha256", "value": "f" * 64},
    }
    bad_mirror = copy.deepcopy(record)
    bad_mirror["parameter_set"]["distributions"].append(mirror)
    assert "semantic.parameter_file_mirror_checksum_differs" in {
        i.code for i in validate_record_report(bad_mirror, policy=policy).errors
    }
    repeated = copy.deepcopy(record)
    repeated["parameter_set"]["parts"].append(copy.deepcopy(repeated["parameter_set"]["parts"][0]))
    assert "semantic.parameter_file_part_repeated" in {
        i.code for i in validate_record_report(repeated, policy=policy).errors
    }


def test_a_missing_source_matters_only_for_publishing() -> None:
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    code = "semantic.parameter_file_no_source"
    default = validate_record_report(record)
    assert default.ok and code not in {i.code for i in default.issues}
    strict = validate_record_report(record, policy="strict")
    assert strict.ok and code in {i.code for i in strict.warnings}
    publisher = validate_record_report(record, policy="publisher")
    assert code in {i.code for i in publisher.errors}


def test_flavour_errors_say_what_is_wrong() -> None:
    record = _file_record()

    def messages(mutate) -> str:
        bad = copy.deepcopy(record)
        mutate(bad["parameter_set"])
        return " | ".join(i.message for i in validate_record_report(bad).errors)

    no_link = messages(lambda b: b.pop("virtual_cell"))
    assert "names no cell" in no_link and "'id'" not in no_link and len(no_link) < 400
    assert "more than one cell" in messages(lambda b: b.update(cell_spec_id=OLD_IRI))
    assert "never both" in messages(lambda b: b.update(claims=copy.deepcopy(b["parts"][0]["claims"])))
    assert "scope belongs to a claim batch" in messages(lambda b: b.update(scope="cell"))
    source = record["parameter_set"]["distributions"][0]
    assert "needs exactly 1 'source' entry; found 2" in messages(
        lambda b: b["distributions"].append({**source, "content_url": MIRROR_URL})
    )


# ── F7: a corrected file supersedes the old record ───────────────────────────


def test_a_corrected_file_names_the_record_it_supersedes() -> None:
    from battinfo.jsonld import record_to_jsonld

    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, supersedes=OLD_IRI)
    assert record["parameter_set"]["supersedes"] == OLD_IRI
    assert validate_record_report(record).ok
    doc = record_to_jsonld(record, "parameter-set")
    node = doc["@graph"][0] if "@graph" in doc else doc
    assert node["dcterms:replaces"] == {"@id": OLD_IRI}
    with pytest.raises(ValueError, match="cannot supersede itself"):
        from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, supersedes=record["parameter_set"]["id"])
    with pytest.raises(ValueError, match="parameter-set IRI"):
        from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, supersedes="not-an-iri")
    # A record of the dataset/ era supersedes as well as a spec/ one.
    newer = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, supersedes=NEWER_OLD_IRI)
    assert newer["parameter_set"]["supersedes"] == NEWER_OLD_IRI
    assert validate_record_report(newer).ok
    # Claim batches carry supersedes too (IDENTIFIER_POLICY 6.3).
    batch = create_parameter_set(
        name="Chen 2020 - graphite",
        material_kind="graphite",
        supersedes=OLD_IRI,
        claims=[{"parameter": "particle_radius", "quantity": {"value": 5.86e-6, "unit": "m"}}],
    )
    assert batch["parameter_set"]["supersedes"] == OLD_IRI
    assert batch["parameter_set"]["id"].startswith("https://w3id.org/battinfo/id/1001/dataset/")


# ── Publishing through the workspace ─────────────────────────────────────────


def test_the_workspace_takes_a_ready_built_record(tmp_path: Path) -> None:
    import battinfo
    from battinfo.ws import SubmitError

    ws = battinfo.workspace(tmp_path / "lab", registry_url=None)
    result = from_bpx_parameters(FIXTURE)
    draft = result.to_parameter_set(virtual_cell=True)
    ws.add("parameter_set", record=draft)
    batch = create_parameter_set(
        name="Chen 2020 - graphite",
        material_kind="graphite",
        claims=[{"parameter": "particle_radius", "quantity": {"value": 5.86e-6, "unit": "m"}}],
    )
    ws.add("parameter_set", record=batch)
    saved = ws.save()
    assert {item["id"] for item in saved["parameter_sets"]} == {
        draft["parameter_set"]["id"],
        batch["parameter_set"]["id"],
    }
    # ws.submit validates under the publisher policy before it sends
    # anything: a parameter file without its source file is refused.
    credentials = {
        "registry_url": "https://registry.example.org",
        "api_key": "k",
        "workspace_id": "w",
        "publisher_id": "p",
    }
    with pytest.raises(SubmitError) as caught:
        ws.submit(**credentials)
    assert [f["status"] for f in caught.value.failed] == ["invalid"]
    assert "a parameter file is published with its file" in caught.value.failed[0]["error"]
    # With the file attached, the same IRI is replaced and the check passes.
    source = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    ws.add("parameter_set", record=result.to_parameter_set(virtual_cell=True, distributions=[source]))
    ws.save()
    stored = json.loads(
        next((tmp_path / "lab").rglob(f"*{draft['parameter_set']['id'][-19:]}.json")).read_text(encoding="utf-8")
    )
    assert stored["parameter_set"]["distributions"][0]["role"] == "source"
    assert validate_record_report(stored, policy="publisher").ok


def test_a_ready_built_record_comes_alone(tmp_path: Path) -> None:
    import battinfo

    ws = battinfo.workspace(tmp_path / "lab", registry_url=None)
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    with pytest.raises(ValueError, match="takes the record alone"):
        ws.add("parameter_set", record=record, name="x")
    with pytest.raises(TypeError, match="'parameter_set' body"):
        ws.add("parameter_set", record={"cell_spec": {}})


# ── F8: strict parsing ───────────────────────────────────────────────────────


def test_a_repeated_key_is_refused_with_its_path() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    key = '"Electrode area [m2]":'
    duplicated = text.replace(key, f"{key} 999999, {key}", 1).encode("utf-8")
    with pytest.raises(ValueError, match=r"\['Parameterisation'\]\['Cell'\] repeats the key 'Electrode area \[m2\]'"):
        from_bpx_parameters(duplicated)
    with pytest.raises(ValueError, match="repeats the key"):
        bpx_file_distribution(duplicated, content_url=SOURCE_URL)


def test_a_byte_order_mark_is_read_and_still_checksummed() -> None:
    raw = FIXTURE.read_bytes()
    with_bom = b"\xef\xbb\xbf" + raw
    res = from_bpx_parameters(with_bom)
    assert res.content_digest == bpx_content_digest(FIXTURE)
    assert res.source_sha256 == hashlib.sha256(with_bom).hexdigest() != hashlib.sha256(raw).hexdigest()
    entry = bpx_file_distribution(with_bom, content_url=SOURCE_URL)
    assert entry["checksum"]["value"] == res.source_sha256
    res.to_parameter_set(virtual_cell=True, distributions=[entry])


def test_numbers_beyond_a_double_and_nan_are_refused_in_words() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    key = '"Electrode area [m2]":'
    for literal, words in (
        ("1E400", "too large for a JSON number"),
        ("1" + "0" * 400, "too large"),
        ("NaN", "not JSON"),
        ("-Infinity", "not JSON"),
    ):
        bad = text.replace(key, f'"X [m]": {literal}, {key}', 1).encode("utf-8")
        with pytest.raises(ValueError, match=words) as caught:
            from_bpx_parameters(bad)
        assert "inf" not in str(caught.value).replace("Infinity", "")


# ── F9: errors that say what to do ───────────────────────────────────────────


def test_naming_the_material_of_a_blended_electrode_says_so() -> None:
    doc = _v1_doc()
    negative = doc["Parameterisation"]["Negative electrode"]
    material_fields = [
        "Minimum stoichiometry",
        "Maximum stoichiometry",
        "Maximum concentration [mol.m-3]",
        "Particle radius [m]",
        "Diffusivity [m2.s-1]",
        "Diffusivity activation energy [J.mol-1]",
        "OCP [V]",
        "Entropic change coefficient [V.K-1]",
        "Reaction rate constant [mol.m-2.s-1]",
    ]
    negative["Particle"] = {"Graphite": {f: negative.pop(f) for f in material_fields}}
    res = from_bpx_parameters(doc)
    with pytest.raises(ValueError, match="negative electrode is blended \\(Graphite\\)"):
        res.to_parameter_set(virtual_cell=True, materials={"negative": "graphite"})


def test_a_bad_material_names_its_key_and_where_the_kinds_are() -> None:
    with pytest.raises(ValueError, match=r"materials\['positive'\].*material_kind_keys\(\)"):
        from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, materials={"positive": "unobtainium"})


def test_only_a_material_part_has_a_phase() -> None:
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    body = record["parameter_set"]
    with pytest.raises(ValueError, match="only a material part"):
        create_parameter_set(
            name="x",
            virtual_cell=True,
            parameters_sha256=body["parameters_sha256"],
            parts=[{**body["parts"][0], "phase": "Primary"}],
        )
    phased = copy.deepcopy(record)
    phased["parameter_set"]["parts"][0]["phase"] = "Primary"  # the cell part
    assert not validate_record_report(phased).ok
    phased["parameter_set"]["parts"][0].pop("phase")
    phased["parameter_set"]["parts"][1]["phase"] = "Primary"  # the negative material part
    assert validate_record_report(phased).ok


def test_distributions_must_be_a_list() -> None:
    entry = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    with pytest.raises(TypeError, match="wrap a single entry in a list"):
        from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, distributions=entry)


# ── F10: the parser's verdict, whole ─────────────────────────────────────────


def test_check_keeps_a_long_detail_whole() -> None:
    pytest.importorskip("bpx")
    doc = _v1_doc()
    for block in ("Negative electrode", "Positive electrode"):
        for key in list(doc["Parameterisation"][block])[:8]:
            del doc["Parameterisation"][block][key]
    detail = check_bpx(doc)["detail"]
    assert len(detail) > 900
    assert "Positive electrode" in detail[600:]
