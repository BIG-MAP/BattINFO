"""A BPX file published to the genome is one record, addressed by its parameters.

The contract pinned here (IDENTIFIER_POLICY 6.3, parameter files):

- the record a BPX file becomes mints its uid from the digest of the file's
  RFC 8785 canonical JSON, and stores that digest as ``parameters_sha256``,
  so the IRI names the parameters: the same parameters land on the same IRI
  however the file is formatted or its numbers spelled, a changed value mints
  a new one, and names, cell links and material targets never enter it;
- the record carries the file itself (``distributions``): exactly one source
  (the bytes the parameters were read from), at most one runnable conversion
  naming the source's checksum, mirrors of the same bytes, https only;
- ``upgrade_bpx`` moves exactly the fields BPX 1.0 relocated, adds the State
  values the bpx package's own migration adds (and names them), and the
  official parser accepts the result where it rejected the source;
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

from battinfo.entities import stable_uid  # noqa: E402
from battinfo.interop import (  # noqa: E402
    bpx_content_digest,
    bpx_file_distribution,
    check_bpx,
    from_bpx_parameters,
    import_bpx_parameters,
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
MIRROR_URL = "https://mirror.example.org/x/source.bpx.json"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _record(source=FIXTURE, **kwargs) -> dict:
    kwargs.setdefault("cell_spec_id", CELL_SPEC_IRI)
    kwargs.setdefault("materials", MATERIALS)
    return from_bpx_parameters(source).to_parameter_set(**kwargs)


def _iri(source=FIXTURE, **kwargs) -> str:
    return _record(source, **kwargs)["parameter_set"]["id"]


def _source() -> dict:
    return bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)


def _runnable_bytes() -> bytes:
    return upgrade_bpx(FIXTURE).to_json().encode("utf-8")


def _runnable(source: dict) -> dict:
    upgraded = upgrade_bpx(FIXTURE)
    return bpx_file_distribution(
        _runnable_bytes(),
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion=upgraded.conversion_note("battinfo test"),
    )


# ── Identity ─────────────────────────────────────────────────────────────────


def test_digest_ignores_layout_but_not_values() -> None:
    doc = _doc()
    reordered = dict(reversed(list(doc.items())))
    assert bpx_content_digest(reordered) == bpx_content_digest(doc)
    assert bpx_content_digest(FIXTURE) == bpx_content_digest(doc)
    assert bpx_content_digest(FIXTURE.read_bytes()) == bpx_content_digest(doc)

    changed = copy.deepcopy(doc)
    changed["Parameterisation"]["Separator"]["Porosity"] = 0.4321
    assert bpx_content_digest(changed) != bpx_content_digest(doc)


def test_digest_is_the_rfc8785_digest() -> None:
    assert bpx_content_digest(FIXTURE) == FIXTURE_DIGEST


def test_the_record_states_the_fingerprint_its_iri_derives_from() -> None:
    record = _record()
    body = record["parameter_set"]
    assert body["parameters_sha256"] == FIXTURE_DIGEST
    # Anyone holding the file can check it against the IRI. The seed and the
    # dataset/ namespace are the registry contract (IDENTIFIER_POLICY 6.3).
    uid = stable_uid(f"parameter-file:{bpx_content_digest(FIXTURE)}")
    assert uid == "94pv-g7vd-2e2r-0t34"
    assert body["id"] == f"https://w3id.org/battinfo/id/1001/dataset/{uid}"
    assert from_bpx_parameters(FIXTURE).file_uid() == uid


def test_the_schmitt_file_uid_is_pinned() -> None:
    # Schmitt et al. 2026 (BattMo export), republished under dataset/ to
    # supersede spec/szxp-xwnx-vhyf-rvm0, which the old seed gave.
    from battinfo.api._parameters import parameter_file_uid

    digest = "b29ec1fd8b0d5c160ffc12fcd39010484c654d3ed149d8a75081d4b49f2d1873"
    assert parameter_file_uid(digest) == "7jnc-cjtw-5h3a-5t52"
    assert stable_uid(f"parameter-set-file:{digest}") == "szxp-xwnx-vhyf-rvm0"


def test_reindented_copy_mints_the_same_iri(tmp_path: Path) -> None:
    # A CRLF checkout or a re-indented copy is the same file to the genome.
    copy_path = tmp_path / "reindented.bpx.json"
    copy_path.write_text(json.dumps(_doc(), indent=4).replace("\n", "\r\n"), encoding="utf-8")
    assert _iri(copy_path) == _iri()


def test_a_copy_rewritten_by_another_json_library_keeps_its_iri() -> None:
    # The IRI names the parameters, not the bytes: Node writes 1.0 as 1 and
    # 9e-06 as 0.000009, and the file still means the same simulation.
    node_text = NODE_COPY.read_text(encoding="utf-8")
    assert NODE_COPY.read_bytes() != FIXTURE.read_bytes()
    assert '"Nominal cell capacity [A.h]": 1,' in node_text
    assert '"Volume [m3]": 0.000009,' in node_text
    assert bpx_content_digest(NODE_COPY) == FIXTURE_DIGEST
    assert _iri(NODE_COPY) == _iri()


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
    res = from_bpx_parameters(doc)
    assert res.file_uid() == from_bpx_parameters(FIXTURE).file_uid()
    # The record holds plain numbers, so it serialises.
    record = res.to_parameter_set(virtual_cell=True)
    assert (
        record["parameter_set"]["parts"]
        == _record(virtual_cell=True, cell_spec_id=None, materials=None)["parameter_set"]["parts"]
    )
    json.dumps(record)

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


def test_names_links_and_targets_do_not_enter_the_identity() -> None:
    # The IRI is the file; which cell or material a curator maps it to is
    # description that can be corrected without changing the bytes it serves.
    base = _iri()
    assert _iri(materials={"negative": "graphite", "positive": "nmc622"}) == base
    assert _iri(cell_spec_id="https://w3id.org/battinfo/spec/1111-1111-1111-1111") == base
    assert _iri(cell_spec_id=None, virtual_cell=True) == base
    assert _iri(name="A curator's better name") == base


def test_a_changed_value_mints_a_new_iri() -> None:
    changed = _doc()
    changed["Parameterisation"]["Separator"]["Porosity"] = 0.4321
    assert _iri(changed) != _iri()


def test_the_builder_refuses_an_iri_the_fingerprint_does_not_give() -> None:
    from battinfo.api import create_parameter_set

    body = _record()["parameter_set"]
    with pytest.raises(ValueError, match="derives from its parameters_sha256"):
        create_parameter_set(
            name="x",
            parts=body["parts"],
            parameters_sha256=body["parameters_sha256"],
            virtual_cell=True,
            uid="0000-0000-0000-0000",
        )


def test_the_one_call_form_returns_the_record() -> None:
    record = import_bpx_parameters(FIXTURE, cell_spec_id=CELL_SPEC_IRI, materials=MATERIALS, retrieved_at=1789900000)
    assert record == _record(retrieved_at=1789900000)


# ── The file rides the record ────────────────────────────────────────────────


def test_source_distribution_hashes_the_exact_bytes() -> None:
    entry = _source()
    raw = FIXTURE.read_bytes()
    assert entry["checksum"] == {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()}
    assert entry["byte_size"] == len(raw)
    assert entry["role"] == "source"
    assert entry["conforms_to"] == "BPX 1.0"
    assert entry["encoding_format"] == "application/json"
    assert entry["name"] == FIXTURE.name


def test_runnable_distribution_names_its_source_and_conversion() -> None:
    source = _source()
    runnable = _runnable(source)
    assert runnable["conforms_to"] == "BPX 1.1.0"
    assert runnable["derived_from"] == "sha256:" + source["checksum"]["value"]
    assert "Initial temperature" in runnable["conversion"]

    with pytest.raises(ValueError, match="derived_from"):
        bpx_file_distribution(FIXTURE, content_url=RUNNABLE_URL, role="runnable")
    with pytest.raises(ValueError, match="only apply"):
        bpx_file_distribution(FIXTURE, content_url=SOURCE_URL, conversion="x")
    with pytest.raises(ValueError, match="only apply"):
        bpx_file_distribution(FIXTURE, content_url=MIRROR_URL, role="mirror", conversion="x")


def test_links_are_https_only() -> None:
    with pytest.raises(ValueError, match="https"):
        bpx_file_distribution(FIXTURE, content_url="http://files.example.org/x.json")
    record = _record(distributions=[_source()])
    record["parameter_set"]["distributions"][0]["content_url"] = "ftp://files.example.org/x.json"
    assert not validate_record_report(record).ok


def test_the_file_rides_the_record_and_validates() -> None:
    source = bpx_file_distribution(
        FIXTURE,
        content_url=SOURCE_URL,
        checks=[check_bpx(FIXTURE)] if _has_bpx() else None,
    )
    mirror = bpx_file_distribution(FIXTURE, content_url=MIRROR_URL, role="mirror")
    record = _record(distributions=[source, _runnable(source), mirror], runnable_file=_runnable_bytes())
    assert [d["role"] for d in record["parameter_set"]["distributions"]] == ["source", "runnable", "mirror"]
    report = validate_record_report(record)
    assert report.ok, report.errors


def test_the_attached_source_must_be_the_file_read() -> None:
    res = from_bpx_parameters(FIXTURE)
    other = bpx_file_distribution(NODE_COPY, content_url=SOURCE_URL)
    # The same parameters in other bytes: the message says so, and how to attach them.
    with pytest.raises(ValueError, match="same parameters as the file read, in other bytes") as caught:
        res.to_parameter_set(virtual_cell=True, distributions=[other])
    assert "source_file=" in str(caught.value)
    changed_doc = _doc()
    changed_doc["Parameterisation"]["Cell"]["Electrode area [m2]"] *= 10
    unrelated = bpx_file_distribution(json.dumps(changed_doc).encode("utf-8"), content_url=SOURCE_URL)
    with pytest.raises(ValueError, match="not the file these parameters were read from"):
        res.to_parameter_set(virtual_cell=True, distributions=[unrelated])
    with pytest.raises(ValueError, match="exactly one role='source'"):
        res.to_parameter_set(virtual_cell=True, distributions=[_source(), _source()])
    # Other bytes with the same parameters are fine when the caller hands
    # them over: the source entry must carry their checksum.
    record = res.to_parameter_set(virtual_cell=True, distributions=[other], source_file=NODE_COPY)
    assert record["parameter_set"]["distributions"] == [other]
    changed = _doc()
    changed["Parameterisation"]["Separator"]["Porosity"] = 0.4321
    changed_bytes = json.dumps(changed).encode("utf-8")
    with pytest.raises(ValueError, match="other parameters"):
        res.to_parameter_set(
            virtual_cell=True,
            distributions=[bpx_file_distribution(changed_bytes, content_url=SOURCE_URL)],
            source_file=changed_bytes,
        )


def test_a_dict_import_needs_the_source_bytes_to_attach_them() -> None:
    res = from_bpx_parameters(_doc())
    assert res.source_sha256 is None
    with pytest.raises(ValueError, match="pass source_file="):
        res.to_parameter_set(virtual_cell=True, distributions=[_source()])
    record = res.to_parameter_set(virtual_cell=True, distributions=[_source()], source_file=FIXTURE)
    assert record["parameter_set"]["distributions"][0]["checksum"]["value"] == (
        hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )


def test_a_bytes_import_knows_its_checksum() -> None:
    raw = FIXTURE.read_bytes()
    res = from_bpx_parameters(raw)
    assert res.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert res.content_digest == FIXTURE_DIGEST
    res.to_parameter_set(virtual_cell=True, distributions=[_source()])


def test_cross_entry_rules_hold() -> None:
    from battinfo.api import create_parameter_set

    source = _source()
    record = _record(distributions=[source])
    body = record["parameter_set"]
    base = {
        "name": body["name"],
        "parts": body["parts"],
        "parameters_sha256": body["parameters_sha256"],
        "virtual_cell": True,
    }
    wrong_runnable = {**_runnable(source), "derived_from": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="must name the source"):
        create_parameter_set(**base, distributions=[source, wrong_runnable])
    wrong_mirror = {**bpx_file_distribution(NODE_COPY, content_url=MIRROR_URL, role="mirror")}
    with pytest.raises(ValueError, match="mirror serves the source's exact bytes"):
        create_parameter_set(**base, distributions=[source, wrong_mirror])
    with pytest.raises(ValueError, match="exactly one source"):
        create_parameter_set(**base, distributions=[_runnable(source)], validate=False)

    # The record validator says the same about a record built elsewhere
    # (an error under the strict policy, like every semantic rule).
    bad = copy.deepcopy(record)
    bad["parameter_set"]["distributions"].append(wrong_runnable)
    codes = {issue.code for issue in validate_record_report(bad).issues}
    assert "semantic.parameter_file_runnable_not_from_source" in codes
    assert not validate_record_report(bad, policy="strict").ok
    bad_mirror = copy.deepcopy(record)
    bad_mirror["parameter_set"]["distributions"].append(wrong_mirror)
    assert "semantic.parameter_file_mirror_checksum_differs" in {
        issue.code for issue in validate_record_report(bad_mirror, policy="strict").errors
    }

    two_sources = copy.deepcopy(record)
    two_sources["parameter_set"]["distributions"].append(dict(source))
    assert not validate_record_report(two_sources).ok
    two_runnables = copy.deepcopy(record)
    two_runnables["parameter_set"]["distributions"] += [_runnable(source), _runnable(source)]
    assert not validate_record_report(two_runnables).ok


def test_a_runnable_next_to_a_source_that_parses_is_a_warning() -> None:
    source = {**_source(), "checks": [{"check": "bpx_parse", "passed": True}]}
    res = from_bpx_parameters(FIXTURE)
    record = res.to_parameter_set(
        virtual_cell=True, distributions=[source, _runnable(source)], runnable_file=_runnable_bytes()
    )
    assert any("a runnable copy is made only when the parser rejects" in w for w in res.warnings)
    report = validate_record_report(record)
    assert report.ok
    assert "semantic.parameter_file_runnable_not_needed" in {i.code for i in report.warnings}


def test_check_names_come_from_a_fixed_list() -> None:
    record = _record(distributions=[_source()])
    record["parameter_set"]["distributions"][0]["checks"] = [{"check": "vibes", "passed": True}]
    assert not validate_record_report(record).ok
    record["parameter_set"]["distributions"][0]["checks"] = [{"check": "simulation_smoke", "passed": True}]
    assert validate_record_report(record).ok


def test_a_part_appears_once() -> None:
    from battinfo.api import create_parameter_set

    body = _record()["parameter_set"]
    parts = body["parts"] + [copy.deepcopy(body["parts"][0])]
    with pytest.raises(ValueError, match="appears twice"):
        create_parameter_set(
            name="x",
            parts=parts,
            parameters_sha256=body["parameters_sha256"],
            virtual_cell=True,
        )
    record = _record()
    record["parameter_set"]["parts"].append(copy.deepcopy(record["parameter_set"]["parts"][0]))
    report = validate_record_report(record, policy="strict")
    assert "semantic.parameter_file_part_repeated" in {i.code for i in report.errors}
    # A phase names another part of the same kind (reserved for blends).
    phased = [*body["parts"], {**copy.deepcopy(body["parts"][1]), "phase": "Secondary"}]
    create_parameter_set(name="x", parts=phased, parameters_sha256=body["parameters_sha256"], virtual_cell=True)


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
    # The moved values, plus the initial state of charge the bpx package's
    # own v0-to-v1 migration adds when a file has none.
    assert out["State"] == {
        "Initial conditions": {
            "Initial state-of-charge": 1,
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
    assert len(result.changes) == 5
    assert result.added == ["State.Initial conditions.Initial state-of-charge = 1 (the v0.x layout states none)"]
    # The input is never mutated.
    assert doc == _doc()


def test_upgrade_leaves_current_files_alone_and_converts_0x() -> None:
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

    # A 0.x file is in the v0.x layout by its version: the same conversion,
    # with the State values the bpx package's migration adds.
    legacy = _doc()
    legacy["Header"]["BPX"] = "0.5.0"
    converted = upgrade_bpx(legacy)
    assert converted.changed and converted.document["Header"]["BPX"] == "1.1.0"
    assert converted.document["State"]["Initial conditions"]["Initial state-of-charge"] == 1


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
        "BPX 1.0 file in the v0.x layout, rewritten in the BPX v1 layout as BPX 1.1.0 by battinfo test: "
    )
    assert "Cell.Initial temperature [K] -> State.Initial conditions.Initial temperature [K]" in note
    # A value was added, so the note says which and does not claim nothing changed.
    assert "No values changed" not in note
    assert "Values added, which the file does not state: State.Initial conditions.Initial state-of-charge = 1" in note
    assert "bpx.convert_v0_to_v1" in note
    # With nothing to add, the note says no value changed.
    doc = _doc()
    doc["State"] = {"Initial conditions": {"Initial state-of-charge": 0.5}}
    assert upgrade_bpx(doc).conversion_note("battinfo test").endswith("No values changed.")


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
    doc = _doc()
    doc["Parameterisation"]["Cell"][THERMAL_CONDUCTIVITY] = 1.48
    record = _record(doc)
    out = to_bpx(record, bpx_version=bpx_version)
    cell = out.bpx["Parameterisation"]["Cell"]
    assert not {"Initial temperature [K]", "Ambient temperature [K]", THERMAL_CONDUCTIVITY} & set(cell)
    assert out.bpx["State"]["Initial conditions"]["Initial temperature [K]"] == 298.15
    assert out.bpx["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] == 1.48
    assert any(THERMAL_CONDUCTIVITY in warning for warning in out.warnings)
    if _has_bpx():
        check = check_bpx(out.bpx)
        assert check["passed"], check["detail"]

    # 0.x keeps the old layout.
    legacy = to_bpx(record, bpx_version="0.4.0")
    assert "State" not in legacy.bpx
    assert legacy.bpx["Parameterisation"]["Cell"][THERMAL_CONDUCTIVITY] == 1.48


def test_export_refuses_two_thermal_conductivities() -> None:
    doc = _doc()
    doc["Parameterisation"]["Cell"][THERMAL_CONDUCTIVITY] = 1.48
    doc["Parameterisation"]["User-defined"][THERMAL_CONDUCTIVITY] = 2.0
    with pytest.raises(ValueError, match="refusing to choose"):
        to_bpx(_record(doc), bpx_version="1.1.0")


def test_a_claim_batch_is_not_a_file() -> None:
    from battinfo.api import create_parameter_set

    batch = create_parameter_set(
        name="Chen 2020 - graphite",
        material_kind="graphite",
        claims=[{"parameter": "particle_radius", "quantity": {"value": 5.86e-6, "unit": "m"}}],
    )
    with pytest.raises(ValueError, match="claim batch"):
        to_bpx(batch)


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
    assert clean["passed"] and "Parser warnings" not in clean["detail"], clean["detail"]

    parameterisation["Cell"]["Upper voltage cut-off [V]"] = 3.9
    check = check_bpx(doc)
    assert check["passed"] is True
    assert check["detail"].startswith("Parser warnings: ")
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
    assert "Parser warnings" not in check["detail"], check["detail"]


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


def _node(record: dict, context: str = "url") -> dict:
    from battinfo.jsonld import record_to_jsonld

    doc = record_to_jsonld(record, "parameter-set", context=context)
    return doc.get("@graph", [doc])[0] if "@graph" in doc else doc


def test_jsonld_describes_the_files() -> None:
    source = _source()
    runnable = bpx_file_distribution(
        upgrade_bpx(FIXTURE).to_json().encode("utf-8"),
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion=upgrade_bpx(FIXTURE).conversion_note("battinfo test"),
        software_requirements=["pybamm>=26.7"],
        checks=[{"check": "bpx_parse", "tool": "bpx 1.1.1", "passed": True, "checked_at": "2026-10-07"}],
    )
    mirror = bpx_file_distribution(FIXTURE, content_url=MIRROR_URL, role="mirror")
    record = _record(distributions=[source, runnable, mirror], runnable_file=_runnable_bytes())
    files = _node(record)["schema:distribution"]
    assert [f["dcterms:type"] for f in files] == ["source", "runnable", "mirror"]
    assert files[0]["schema:contentUrl"] == SOURCE_URL
    assert files[0]["schema:sha256"] == source["checksum"]["value"]
    assert files[0]["dcterms:conformsTo"] == "BPX 1.0"
    assert files[1]["prov:wasDerivedFrom"]["schema:sha256"] == source["checksum"]["value"]
    assert "Initial temperature" in files[1]["prov:wasGeneratedBy"]["dcterms:description"]
    assert files[1]["schema:softwareRequirements"] == "pybamm>=26.7"
    assert files[1]["schema:additionalProperty"]["schema:value"] is True
    assert files[2]["schema:sha256"] == source["checksum"]["value"]


def test_jsonld_parts_are_datasets_with_their_claims() -> None:
    record = _record()
    node = _node(record)
    assert node["schema:about"] == {"@id": CELL_SPEC_IRI}
    assert node["schema:identifier"] == {
        "@type": "schema:PropertyValue",
        "schema:propertyID": "parameters-sha256-rfc8785",
        "schema:value": FIXTURE_DIGEST,
    }
    parts = node["schema:hasPart"]
    assert len(parts) == 8
    assert all(part["@type"] == "schema:Dataset" and "@id" not in part for part in parts)
    by_part = {part["schema:additionalProperty"]["schema:value"]: part for part in parts}
    negative = by_part["negative_material"]
    assert negative["schema:name"] == f"{record['parameter_set']['name']} - negative electrode material"
    assert negative["schema:about"]["@type"] == "Graphite"
    variables = negative["schema:variableMeasured"]
    variables = variables if isinstance(variables, list) else [variables]
    assert any(v["schema:name"] == "ocp" for v in variables)
    cell_types = {
        t for prop in by_part["cell"]["hasProperty"] for t in prop["@type"] if isinstance(prop["@type"], list)
    }
    assert {"NominalCapacity", "Area", "NumberOfElectrodePairs"} <= cell_types
    assert "schema:about" not in by_part["separator"]


@pytest.mark.parametrize("link", ["cell_spec_id", "cell_instance_id", "virtual_cell"])
@pytest.mark.parametrize("context", ["url", "inline"])
def test_jsonld_validates_for_every_cell_link(link: str, context: str) -> None:
    from battinfo.jsonld import record_to_jsonld
    from battinfo.validate.jsonld import validate_jsonld_report

    kwargs = {
        "cell_spec_id": {"cell_spec_id": CELL_SPEC_IRI},
        "cell_instance_id": {
            "cell_spec_id": None,
            "cell_instance_id": "https://w3id.org/battinfo/cell/0000-0000-0000-0001",
        },
        "virtual_cell": {"cell_spec_id": None, "virtual_cell": True},
    }[link]
    record = _record(distributions=[_source()], **kwargs)
    doc = record_to_jsonld(record, "parameter-set", context=context)
    report = validate_jsonld_report(doc)
    assert report.ok, report.errors
    node = _node(record, context)
    if link == "virtual_cell":
        assert "schema:about" not in node
        flags = node["schema:additionalProperty"]
        assert {"@type": "schema:PropertyValue", "schema:name": "virtual_cell", "schema:value": True} in flags
    else:
        assert node["schema:about"] == {"@id": record["parameter_set"][link]}
