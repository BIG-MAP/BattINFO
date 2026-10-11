"""A BPX file published to the genome is addressed by its parameters.

The contract pinned here (IDENTIFIER_POLICY 6.3, file-backed parameter sets):

- records imported from a BPX file mint their uids from the digest of the
  file's RFC 8785 canonical JSON, so the IRI names the parameters: the same
  parameters land on the same IRIs however the file is formatted or its
  numbers spelled, and a changed value mints new ones; names and targets
  never enter the identity;
- the set record carries the file itself (``distributions``): the source bytes
  as published and, optionally, a declared runnable conversion, each with a
  sha256 a downloader verifies;
- ``upgrade_bpx`` moves exactly the fields BPX 1.0 relocated and nothing else,
  and the official parser accepts the result where it rejected the source;
- ``check_bpx`` reports every warning the parser raises;
- the Validation section is named, never dropped in silence.

The fixture is the synthetic structural twin of the Schmitt et al. 2026 BattMo
export (the v0.x layout declared as BPX 1.0, Validation section included).
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop import (  # noqa: E402
    bpx_content_digest,
    bpx_file_distribution,
    check_bpx,
    from_bpx,
    from_bpx_parameters,
    upgrade_bpx,
)
from battinfo.interop.bpx import to_bpx  # noqa: E402
from battinfo.validate import validate_record_report  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
# The fixture passed through Node.js, JSON.stringify(JSON.parse(text), null, 2):
# what any other JSON library does to a file. Same parameters, other bytes, and
# the numbers respelled (1.0 -> 1, 9e-06 -> 0.000009).
NODE_COPY = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.node.bpx.json"
# sha256 of the fixture's RFC 8785 form, computed independently with a
# JavaScript JCS (JSON.stringify on values, keys sorted by UTF-16 code units).
# If this moves, every file-backed IRI moves with it.
FIXTURE_DIGEST = "37f1c8a5ac35e5faf22a5297c0c1a8c871fa219750a597f68542666beafe27df"
THERMAL_CONDUCTIVITY = "Thermal conductivity [W.m-1.K-1]"
CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/0000-0000-0000-0000"
MATERIALS = {"negative": "graphite", "positive": "nmc811"}
SOURCE_URL = "https://files.example.org/parameter_sets/x/source.bpx.json"
RUNNABLE_URL = "https://files.example.org/parameter_sets/x/runnable.bpx.json"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _records(source=FIXTURE, **kwargs) -> dict[str, dict]:
    return from_bpx_parameters(source).to_records(
        materials=MATERIALS, cell_spec_id=CELL_SPEC_IRI, by_block=True, **kwargs
    )


# ── Identity ─────────────────────────────────────────────────────────────────


def test_digest_ignores_layout_but_not_values() -> None:
    doc = _doc()
    reordered = dict(reversed(list(doc.items())))
    assert bpx_content_digest(reordered) == bpx_content_digest(doc)
    assert bpx_content_digest(FIXTURE) == bpx_content_digest(doc)

    changed = copy.deepcopy(doc)
    changed["Parameterisation"]["Separator"]["Porosity"] = 0.4321
    assert bpx_content_digest(changed) != bpx_content_digest(doc)


def test_digest_is_the_rfc8785_digest() -> None:
    assert bpx_content_digest(FIXTURE) == FIXTURE_DIGEST


def test_reindented_copy_mints_the_same_iris(tmp_path: Path) -> None:
    # A CRLF checkout or a re-indented copy is the same file to the genome.
    copy_path = tmp_path / "reindented.bpx.json"
    copy_path.write_text(json.dumps(_doc(), indent=4).replace("\n", "\r\n"), encoding="utf-8")
    first = {block: r["parameter_set"]["id"] for block, r in _records().items()}
    second = {block: r["parameter_set"]["id"] for block, r in _records(copy_path).items()}
    assert first == second


def test_a_copy_rewritten_by_another_json_library_keeps_its_iris() -> None:
    # The IRI names the parameters, not the bytes: Node writes 1.0 as 1 and
    # 9e-06 as 0.000009, and the file still means the same simulation.
    node_text = NODE_COPY.read_text(encoding="utf-8")
    assert NODE_COPY.read_bytes() != FIXTURE.read_bytes()
    assert '"Nominal cell capacity [A.h]": 1,' in node_text
    assert '"Volume [m3]": 0.000009,' in node_text
    assert bpx_content_digest(NODE_COPY) == FIXTURE_DIGEST
    original = {block: r["parameter_set"]["id"] for block, r in _records().items()}
    rewritten = {block: r["parameter_set"]["id"] for block, r in _records(NODE_COPY).items()}
    assert rewritten == original


def test_number_spelling_does_not_enter_the_identity(tmp_path: Path) -> None:
    respelled = FIXTURE.read_text(encoding="utf-8")
    for key, before, after in (
        ("Nominal cell capacity [A.h]", "1.0", "1"),
        ("Particle radius [m]", "1e-05", "0.00001"),
        ("Entropic change coefficient [V.K-1]", "0.0", "-0.0"),
        ("Number of electrode pairs connected in parallel to make a cell", "20", "2e1"),
    ):
        assert f'"{key}": {before},' in respelled, key
        respelled = respelled.replace(f'"{key}": {before},', f'"{key}": {after},')
    path = tmp_path / "respelled.bpx.json"
    path.write_text(respelled, encoding="utf-8")
    assert from_bpx_parameters(path).file_uid() == from_bpx_parameters(FIXTURE).file_uid()


def test_numpy_values_in_a_dict_import_like_their_json() -> None:
    np = pytest.importorskip("numpy")
    doc = _doc()
    doc["Parameterisation"]["Separator"]["Porosity"] = np.float64(doc["Parameterisation"]["Separator"]["Porosity"])
    doc["Parameterisation"]["Cell"]["Number of electrode pairs connected in parallel to make a cell"] = np.int64(20)
    ocp = doc["Parameterisation"]["Negative electrode"]["OCP [V]"]
    ocp["x"], ocp["y"] = np.array(ocp["x"]), np.array(ocp["y"])
    assert from_bpx_parameters(doc).file_uid() == from_bpx_parameters(FIXTURE).file_uid()

    # A float32 holds a different double from the decimal it was made from;
    # it imports as the value it holds.
    doc["Parameterisation"]["Separator"]["Porosity"] = np.float32(0.47)
    plain = _doc()
    plain["Parameterisation"]["Separator"]["Porosity"] = float(np.float32(0.47))
    assert bpx_content_digest(doc) == bpx_content_digest(plain)


def test_nan_has_no_identity() -> None:
    doc = _doc()
    doc["Parameterisation"]["Separator"]["Porosity"] = float("nan")
    with pytest.raises(ValueError, match=r"\['Parameterisation'\]\['Separator'\]\['Porosity'\]"):
        bpx_content_digest(doc)
    with pytest.raises(ValueError, match="NaN"):
        from_bpx_parameters(doc)


def test_every_record_is_addressed_by_the_file() -> None:
    res = from_bpx_parameters(FIXTURE)
    by_block = res.to_records(materials=MATERIALS, cell_spec_id=CELL_SPEC_IRI, by_block=True)
    assert by_block["set"]["parameter_set"]["id"].endswith("/" + res.file_uid())
    for block, record in by_block.items():
        if block == "set":
            continue
        assert record["parameter_set"]["id"].endswith("/" + res.file_uid(block)), block


def test_names_and_targets_do_not_enter_the_identity() -> None:
    # The IRI is the file; which cell spec or material a curator maps it to is
    # description that can be corrected without changing the bytes it serves.
    base = {block: r["parameter_set"]["id"] for block, r in _records().items()}
    renamed = from_bpx_parameters(FIXTURE).to_records(
        materials={"negative": "graphite", "positive": "nmc622"},
        cell_spec_id="https://w3id.org/battinfo/spec/1111-1111-1111-1111",
        name="A curator's better name",
        by_block=True,
    )
    assert {block: r["parameter_set"]["id"] for block, r in renamed.items()} == base


def test_a_changed_value_mints_new_iris() -> None:
    changed = _doc()
    changed["Parameterisation"]["Separator"]["Porosity"] = 0.4321
    old = {block: r["parameter_set"]["id"] for block, r in _records().items()}
    new = {block: r["parameter_set"]["id"] for block, r in _records(changed).items()}
    assert set(old) == set(new)
    assert not set(old.values()) & set(new.values())


# ── The file rides the set ───────────────────────────────────────────────────


def test_source_distribution_hashes_the_exact_bytes() -> None:
    entry = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    raw = FIXTURE.read_bytes()
    assert entry["checksum"] == {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()}
    assert entry["byte_size"] == len(raw)
    assert entry["role"] == "source"
    assert entry["conforms_to"] == "BPX 1.0"
    assert entry["encoding_format"] == "application/json"
    assert entry["name"] == FIXTURE.name


def test_runnable_distribution_names_its_source_and_conversion() -> None:
    source = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    upgraded = upgrade_bpx(FIXTURE)
    runnable = bpx_file_distribution(
        upgraded.to_json().encode("utf-8"),
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion=upgraded.conversion_note("battinfo test"),
    )
    assert runnable["conforms_to"] == "BPX 1.1.0"
    assert runnable["derived_from"] == "sha256:" + source["checksum"]["value"]
    assert "Initial temperature" in runnable["conversion"]

    with pytest.raises(ValueError, match="derived_from"):
        bpx_file_distribution(FIXTURE, content_url=RUNNABLE_URL, role="runnable")
    with pytest.raises(ValueError, match="only apply"):
        bpx_file_distribution(FIXTURE, content_url=SOURCE_URL, conversion="x")


def test_distributions_ride_the_set_and_validate() -> None:
    source = bpx_file_distribution(
        FIXTURE,
        content_url=SOURCE_URL,
        checks=[check_bpx(FIXTURE)] if _has_bpx() else None,
    )
    by_block = _records(distributions=[source])
    assert by_block["set"]["parameter_set"]["distributions"] == [source]
    for block, record in by_block.items():
        if block != "set":
            assert "distributions" not in record["parameter_set"], block
        report = validate_record_report(record)
        assert report.ok, (block, report.errors)


def test_schema_rejects_a_runnable_file_without_its_source() -> None:
    by_block = _records(distributions=[bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)])
    record = copy.deepcopy(by_block["set"])
    record["parameter_set"]["distributions"].append(
        {**record["parameter_set"]["distributions"][0], "role": "runnable"}
    )
    report = validate_record_report(record)
    assert not report.ok


def test_distributions_need_the_set() -> None:
    res = from_bpx_parameters(FIXTURE)
    with pytest.raises(ValueError, match="cell_spec_id"):
        res.to_records(
            materials=MATERIALS,
            distributions=[bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)],
        )


# ── Layout upgrade and checks ────────────────────────────────────────────────


def _has_bpx() -> bool:
    try:
        import bpx  # noqa: F401
    except ImportError:
        return False
    return True


def test_upgrade_moves_exactly_the_relocated_fields() -> None:
    doc = _doc()
    result = upgrade_bpx(doc)
    out = result.document
    assert result.source_version == "1.0"
    assert out["Header"]["BPX"] == "1.1.0"
    cell, electrolyte = doc["Parameterisation"]["Cell"], doc["Parameterisation"]["Electrolyte"]
    assert out["State"] == {
        "Initial conditions": {
            "Initial temperature [K]": cell["Initial temperature [K]"],
            "Initial electrolyte concentration [mol.m-3]": electrolyte["Initial concentration [mol.m-3]"],
        },
        "Thermal environment": {"Ambient temperature [K]": cell["Ambient temperature [K]"]},
    }
    # Everything else is byte-for-byte the same value.
    moved = {"Initial temperature [K]", "Ambient temperature [K]", "Initial concentration [mol.m-3]"}
    for block, fields in doc["Parameterisation"].items():
        expected = {k: v for k, v in fields.items() if k not in moved}
        assert out["Parameterisation"][block] == expected, block
    assert out["Validation"] == doc["Validation"]
    assert len(result.changes) == 4
    # The input is never mutated.
    assert doc == _doc()


def test_upgrade_leaves_current_files_alone_and_refuses_0x() -> None:
    current = upgrade_bpx(_doc()).document
    again = upgrade_bpx(current)
    assert not again.changed
    assert again.document == current

    # A file already in the v1 layout keeps the version it declares.
    declared_1_0 = copy.deepcopy(current)
    declared_1_0["Header"]["BPX"] = "1.0.0"
    untouched = upgrade_bpx(declared_1_0)
    assert not untouched.changed
    assert untouched.document == declared_1_0

    legacy = _doc()
    legacy["Header"]["BPX"] = "0.5.0"
    with pytest.raises(ValueError, match="0.x"):
        upgrade_bpx(legacy)


def test_upgrade_goes_by_the_fields_not_the_declared_version() -> None:
    # Declaring 1.1 does not make the v0.x layout current.
    doc = _doc()
    doc["Header"]["BPX"] = "1.1.0"
    result = upgrade_bpx(doc)
    assert result.changed
    assert "Initial temperature [K]" not in result.document["Parameterisation"]["Cell"]
    assert result.document["State"]["Thermal environment"] == {"Ambient temperature [K]": 298.15}
    assert result.document["Header"]["BPX"] == "1.1.0"
    assert not any(change.startswith("Header.BPX") for change in result.changes)


def test_conversion_note_says_what_happened() -> None:
    note = upgrade_bpx(FIXTURE).conversion_note("battinfo test")
    assert note.startswith(
        "BPX v0.x layout declared as BPX 1.0, rewritten in the BPX v1 layout as BPX 1.1.0 by battinfo test: "
    )
    assert note.endswith("No values changed.")
    assert "Cell.Initial temperature [K] -> State.Initial conditions.Initial temperature [K]" in note


def test_upgrade_moves_cell_thermal_conductivity_to_user_defined() -> None:
    # bpx >= 1.0 rejects it in Cell and asks for it in User-defined.
    doc = _doc()
    doc["Parameterisation"]["Cell"][THERMAL_CONDUCTIVITY] = 1.48
    result = upgrade_bpx(doc)
    parameterisation = result.document["Parameterisation"]
    assert THERMAL_CONDUCTIVITY not in parameterisation["Cell"]
    assert parameterisation["User-defined"][THERMAL_CONDUCTIVITY] == 1.48
    assert f"Cell.{THERMAL_CONDUCTIVITY} -> User-defined.{THERMAL_CONDUCTIVITY}" in result.changes
    if _has_bpx():
        assert check_bpx(result.document)["passed"]

    # The same value already in User-defined is not a conflict...
    doc["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] = 1.48
    same = upgrade_bpx(doc)
    assert same.document["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] == 1.48
    assert any("already holds the same value" in change for change in same.changes)
    # ...a different one is.
    doc["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] = 2.0
    with pytest.raises(ValueError, match="refusing to choose"):
        upgrade_bpx(doc)


def test_upgrade_says_what_is_wrong_with_a_null_state() -> None:
    doc = _doc()
    doc["State"] = None
    with pytest.raises(ValueError, match="BPX State is null, not an object"):
        upgrade_bpx(doc)
    doc["State"] = {"Initial conditions": None}
    with pytest.raises(ValueError, match="BPX State.Initial conditions is null, not an object"):
        upgrade_bpx(doc)


@pytest.mark.parametrize("bpx_version", ["1.0", "1.0.0", "1.1.0"])
def test_export_at_any_v1_version_uses_the_v1_layout(bpx_version: str) -> None:
    # BPX 1.0, not 1.1, introduced the State block: an export declaring 1.0
    # in the old layout is a file every current parser rejects.
    by_block = _records()
    extras = {**from_bpx(FIXTURE).extras, THERMAL_CONDUCTIVITY: 1.48}
    out = to_bpx({"properties": from_bpx(FIXTURE).specs}, parameter_sets=by_block,
                 cell_extras=extras, bpx_version=bpx_version)
    cell = out.bpx["Parameterisation"]["Cell"]
    assert not {"Initial temperature [K]", "Ambient temperature [K]", THERMAL_CONDUCTIVITY} & set(cell)
    assert out.bpx["State"]["Initial conditions"]["Initial temperature [K]"] == 298.15
    assert out.bpx["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] == 1.48
    assert any(THERMAL_CONDUCTIVITY in warning for warning in out.warnings)
    if _has_bpx():
        check = check_bpx(out.bpx)
        assert check["passed"], check["detail"]

    # 0.x keeps the old layout.
    legacy = to_bpx({"properties": from_bpx(FIXTURE).specs}, parameter_sets=by_block,
                    cell_extras=extras, bpx_version="0.4.0")
    assert "State" not in legacy.bpx
    assert legacy.bpx["Parameterisation"]["Cell"][THERMAL_CONDUCTIVITY] == 1.48


def test_export_refuses_two_thermal_conductivities() -> None:
    by_block = _records()
    by_block["set"]["parameter_set"]["annex"][THERMAL_CONDUCTIVITY] = 2.0
    extras = {**from_bpx(FIXTURE).extras, THERMAL_CONDUCTIVITY: 1.48}
    with pytest.raises(ValueError, match="refusing to choose"):
        to_bpx({"properties": from_bpx(FIXTURE).specs}, parameter_sets=by_block,
               cell_extras=extras, bpx_version="1.1.0")


def test_official_parser_rejects_the_source_and_accepts_the_upgrade() -> None:
    pytest.importorskip("bpx")
    source_check = check_bpx(FIXTURE)
    assert source_check["check"] == "bpx_parse"
    assert source_check["tool"].startswith("bpx ")
    assert source_check["passed"] is False
    assert "moved" in source_check["detail"]

    upgraded_check = check_bpx(upgrade_bpx(FIXTURE).document)
    assert upgraded_check["passed"] is True, upgraded_check["detail"]


def test_check_reports_the_parser_consistency_warnings() -> None:
    # The review's reproduction: OCPs as functions, so the parser checks the
    # voltage the stoichiometry limits imply against the cut-offs, and an
    # upper cut-off below that voltage. The parser warns and still parses;
    # the check must say so (the warning text never mentions "bpx").
    pytest.importorskip("bpx")
    doc = upgrade_bpx(FIXTURE).document
    parameterisation = doc["Parameterisation"]
    parameterisation["Negative electrode"]["OCP [V]"] = "0.1 - 0.05 * x"
    parameterisation["Positive electrode"]["OCP [V]"] = "4.4 - 0.5 * x"
    clean = check_bpx(doc)
    assert clean["passed"] and "Warnings" not in clean["detail"], clean["detail"]

    parameterisation["Cell"]["Upper voltage cut-off [V]"] = 3.9
    check = check_bpx(doc)
    assert check["passed"] is True
    assert "The maximum voltage computed from the STO limits" in check["detail"]
    assert "upper voltage cut-off (3.9 V)" in check["detail"]


def test_check_leaves_out_third_party_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    # bpx builds its expression grammar with deprecated pyparsing names, and
    # pyparsing's warnings point their filename at bpx's own module. They say
    # nothing about the file being checked.
    bpx = pytest.importorskip("bpx")
    bpx_dir = Path(bpx.__file__).resolve().parent
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bpx.ExpressionParser()
    if not any(Path(w.filename).resolve().is_relative_to(bpx_dir) for w in caught):
        pytest.skip("this bpx and pyparsing pair raises no deprecation warnings")

    real_parse = bpx.parse_bpx_obj

    def parse_with_noise(obj: dict, *args: object, **kwargs: object) -> object:
        bpx.ExpressionParser()
        return real_parse(obj, *args, **kwargs)

    monkeypatch.setattr(bpx, "parse_bpx_obj", parse_with_noise)
    check = check_bpx(upgrade_bpx(FIXTURE).document)
    assert check["passed"] is True
    assert "Warnings" not in check["detail"], check["detail"]


def test_check_reports_a_float_version_and_a_legacy_conversion() -> None:
    # Both come from bpx, though the warnings point their filename elsewhere
    # (pydantic, and the caller of parse_bpx_obj).
    pytest.importorskip("bpx")
    assert "semantic version as a string" in check_bpx(FIXTURE)["detail"]
    legacy = upgrade_bpx(FIXTURE).document
    legacy["Header"]["BPX"] = "0.4.0"
    assert "legacy BPX v0.x" in check_bpx(legacy)["detail"]


def test_validation_section_is_named_not_dropped() -> None:
    res = from_bpx_parameters(FIXTURE)
    series = list(_doc()["Validation"])
    warning = next(w for w in res.warnings if w.startswith("BPX Validation block"))
    for name in series:
        assert name in warning


# ── JSON-LD ──────────────────────────────────────────────────────────────────


def test_jsonld_describes_the_files() -> None:
    from battinfo.jsonld import record_to_jsonld

    source = bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)
    upgraded = upgrade_bpx(FIXTURE)
    runnable = bpx_file_distribution(
        upgraded.to_json().encode("utf-8"),
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion=upgraded.conversion_note("battinfo test"),
        software_requirements=["pybamm>=26.7"],
        checks=[{"check": "bpx_parse", "tool": "bpx 1.1.1", "passed": True, "checked_at": "2026-10-07"}],
    )
    record = _records(distributions=[source, runnable])["set"]
    node = record_to_jsonld(record, "parameter-set")
    node = node.get("@graph", [node])[0] if "@graph" in node else node
    files = node["schema:distribution"]
    assert [f["dcterms:type"] for f in files] == ["source", "runnable"]
    assert files[0]["schema:contentUrl"] == SOURCE_URL
    assert files[0]["schema:sha256"] == source["checksum"]["value"]
    assert files[0]["dcterms:conformsTo"] == "BPX 1.0"
    assert files[1]["prov:wasDerivedFrom"]["schema:sha256"] == source["checksum"]["value"]
    assert "Initial temperature" in files[1]["prov:wasGeneratedBy"]["dcterms:description"]
    assert files[1]["schema:softwareRequirements"] == "pybamm>=26.7"
    assert files[1]["schema:additionalProperty"]["schema:value"] is True
