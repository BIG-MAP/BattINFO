"""A BPX file published to the genome is addressed by its content.

The contract pinned here (IDENTIFIER_POLICY 6.3, file-backed parameter sets):

- records imported from a BPX file mint their uids from the file's canonical
  JSON digest, so the same file always lands on the same IRIs and a changed
  value mints new ones; names and targets never enter the identity;
- the set record carries the file itself (``distributions``): the source bytes
  as published and, optionally, a declared runnable conversion, each with a
  sha256 a downloader verifies;
- ``upgrade_bpx`` moves exactly the fields BPX 1.1 relocated and nothing else,
  and the official parser accepts the result where it rejected the source;
- the Validation section is named, never dropped in silence.

The fixture is the synthetic structural twin of the Schmitt et al. 2026 BattMo
export (BPX 1.0 layout, Validation section included).
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop import (  # noqa: E402
    bpx_content_digest,
    bpx_file_distribution,
    check_bpx,
    from_bpx_parameters,
    upgrade_bpx,
)
from battinfo.validate import validate_record_report  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
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


def test_reindented_copy_mints_the_same_iris(tmp_path: Path) -> None:
    # A CRLF checkout or a re-indented copy is the same file to the genome.
    copy_path = tmp_path / "reindented.bpx.json"
    copy_path.write_text(json.dumps(_doc(), indent=4).replace("\n", "\r\n"), encoding="utf-8")
    first = {block: r["parameter_set"]["id"] for block, r in _records().items()}
    second = {block: r["parameter_set"]["id"] for block, r in _records(copy_path).items()}
    assert first == second


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

    legacy = _doc()
    legacy["Header"]["BPX"] = "0.5.0"
    with pytest.raises(ValueError, match="0.x"):
        upgrade_bpx(legacy)


def test_official_parser_rejects_the_source_and_accepts_the_upgrade() -> None:
    pytest.importorskip("bpx")
    source_check = check_bpx(FIXTURE)
    assert source_check["check"] == "bpx_parse"
    assert source_check["tool"].startswith("bpx ")
    assert source_check["passed"] is False
    assert "moved" in source_check["detail"]

    upgraded_check = check_bpx(upgrade_bpx(FIXTURE).document)
    assert upgraded_check["passed"] is True, upgraded_check["detail"]


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
