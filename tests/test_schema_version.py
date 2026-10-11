"""Every record emitter stamps the single battinfo.bundle.SCHEMA_VERSION constant.

Records originally said "0.1.0"; the 2026-07 input-model consolidation accidentally
forked dataset records to "1.0.0". "0.2.0" deliberately supersedes both — this test
pins the constant and checks the model layer, the dict-builder layer, and an interop
emitter all agree, so a future fork cannot happen silently again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import template_material_spec
from battinfo.bundle import (
    SCHEMA_VERSION,
    SUPERSEDED_SCHEMA_VERSIONS,
    Cell,
    CellSpec,
    Dataset,
    ProvenanceInfo,
    Test,
    TestSpec,
    _stored_schema_version,
    load_cell_specification,
)
from battinfo.validate.record import validate_record_report

# A packaged cell spec that validates clean under the strict policy.
_CELL_SPEC_EXAMPLE = ROOT / "src" / "battinfo" / "data" / "examples" / "cell-spec" / "cell-spec-0hpw-gkhk-gcg8-23x1.json"


def test_schema_version_value() -> None:
    assert SCHEMA_VERSION == "0.2.0"


def test_bundle_models_default_to_the_constant() -> None:
    spec = CellSpec(manufacturer="Acme", model_name="X1", chemistry="LFP", format="cylindrical")
    assert spec.schema_version == SCHEMA_VERSION


def test_dataset_record_carries_the_constant() -> None:
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        name="Version-stamp dataset",
        access_url="https://example.org/datasets/version-stamp",
        created_at=1771804803,
        source=ProvenanceInfo(type="measurement", retrieved_at=1771805001),
    )
    assert dataset.to_record()["schema_version"] == SCHEMA_VERSION


def test_dict_builders_carry_the_constant() -> None:
    assert template_material_spec()["schema_version"] == SCHEMA_VERSION


def test_read_records_keep_their_stored_version() -> None:
    # An existing record's declared version is provenance — loading must not rewrite it.
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        name="Version-stamp dataset",
        access_url="https://example.org/datasets/version-stamp",
        created_at=1771804803,
        source=ProvenanceInfo(type="measurement", retrieved_at=1771805001),
    )
    record = dataset.to_record()
    record["schema_version"] = "0.1.0"
    assert Dataset.from_record(record).schema_version == "0.1.0"


# ── Validation names a schema_version this release did not write ──────────────

def _cell_spec_stamped(version: str) -> dict:
    record = json.loads(_CELL_SPEC_EXAMPLE.read_text(encoding="utf-8"))
    record["schema_version"] = version
    return record


def _version_issues(record: dict, policy: str = "strict") -> list[tuple[str, str]]:
    report = validate_record_report(record, policy=policy)
    return [(issue.code, issue.severity) for issue in report.issues if issue.path == "schema_version"]


def test_the_current_version_draws_no_issue() -> None:
    assert _version_issues(_cell_spec_stamped(SCHEMA_VERSION)) == []


def test_the_superseded_versions_are_the_ones_earlier_releases_stamped() -> None:
    # 0.1.0 from the dict builders, 1.0.0 from the pydantic models (see the module docstring).
    assert set(SUPERSEDED_SCHEMA_VERSIONS) == {"0.1.0", "1.0.0"}
    assert SCHEMA_VERSION not in SUPERSEDED_SCHEMA_VERSIONS


@pytest.mark.parametrize("version", SUPERSEDED_SCHEMA_VERSIONS)
def test_a_version_an_earlier_release_wrote_is_a_superseded_warning(version: str) -> None:
    record = _cell_spec_stamped(version)
    assert _version_issues(record) == [("semantic.schema_version_superseded", "warning")]
    assert validate_record_report(record, policy="strict").ok  # it still reads


@pytest.mark.parametrize("version", ["9.9.9", "0.2.1", "0.3.0-rc1"])
@pytest.mark.parametrize("policy", ["default", "strict", "publisher", "ingest"])
def test_any_other_version_is_an_unknown_version_warning(version: str, policy: str) -> None:
    record = _cell_spec_stamped(version)
    assert _version_issues(record, policy) == [("semantic.schema_version_unknown", "warning")]
    assert validate_record_report(record, policy=policy).ok


def test_strict_cli_validation_reports_an_unknown_version(tmp_path: Path) -> None:
    """The consumer evaluation's A-14: ``battinfo validate --policy strict`` passed a
    record claiming schema_version 9.9.9 and said nothing about it."""
    from typer.testing import CliRunner

    from battinfo.cli import app

    path = tmp_path / "cell_spec-schema999.json"
    path.write_text(json.dumps(_cell_spec_stamped("9.9.9")), encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(path), "--policy", "strict", "--format", "json"])
    assert result.exit_code == 0, result.stdout  # a warning, not a failure
    payload = json.loads(result.stdout)
    issues = [issue for issue in payload["issues"] if issue["path"] == "schema_version"]
    assert [(issue["code"], issue["severity"]) for issue in issues] == [("semantic.schema_version_unknown", "warning")]
    assert "9.9.9" in issues[0]["message"]


# ── Records built from another format carry the current version ───────────────
# A canonical record the code builds from a datasheet library file or a
# converter import is written by this release, so it carries SCHEMA_VERSION; only
# a canonical record read back with from_record keeps the version it states.

_EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
_LIBRARY_CR2032 = ROOT / "src" / "battinfo" / "data" / "library" / "cell-spec" / "ENERGIZER__CR2032.json"


def _library_doc() -> dict:
    """The packaged CR2032 library record, stamped 1.0.0 as the packaged library files are."""
    doc = json.loads(_LIBRARY_CR2032.read_text(encoding="utf-8"))
    doc["schema_version"] = "1.0.0"
    return doc


def test_a_cell_spec_built_from_a_library_record_carries_the_current_version(tmp_path: Path) -> None:
    """Red-team finding on the schema_version warning: from_library_record copied the
    library file's 1.0.0 into the canonical cell spec, which then drew
    semantic.schema_version_superseded although this release had just written it."""
    record = CellSpec.from_library_record(_library_doc()).to_record()
    assert record["schema_version"] == SCHEMA_VERSION
    assert _version_issues(record) == []

    path = tmp_path / "ENERGIZER__CR2032.json"
    path.write_text(json.dumps(_library_doc()), encoding="utf-8")
    assert CellSpec.from_path(path).to_record()["schema_version"] == SCHEMA_VERSION
    assert load_cell_specification(path).to_record()["schema_version"] == SCHEMA_VERSION


def test_library_records_written_now_carry_the_current_version() -> None:
    from battinfo.api import template_library_cell_spec
    from battinfo.api._records import _cell_spec_record_to_library_format, _library_record_from_input

    assert template_library_cell_spec()["schema_version"] == SCHEMA_VERSION
    flat = {"uid": "1f8r-6v2k-9p4m-3t7x", "manufacturer": "Acme", "model": "X1", "format": "coin", "chemistry": "li-ion"}
    assert _library_record_from_input(flat)["schema_version"] == SCHEMA_VERSION

    unstamped = json.loads(_CELL_SPEC_EXAMPLE.read_text(encoding="utf-8"))
    del unstamped["schema_version"]
    assert _cell_spec_record_to_library_format(unstamped)["schema_version"] == SCHEMA_VERSION
    assert CellSpec.from_library_record(_library_doc()).to_library_record()["schema_version"] == SCHEMA_VERSION


def test_the_batch_and_publication_routes_build_library_specs_at_the_current_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battinfo.contribution import _load_cell_spec_for_batch
    from battinfo.publication import _normalize_cell_specification, derive_cell_spec

    monkeypatch.chdir(tmp_path)  # the batch path also searches ./.battinfo/library
    cell_spec, specification = _load_cell_spec_for_batch(_library_doc()["specification"]["id"])
    assert specification is not None
    assert (cell_spec.schema_version, specification.schema_version) == (SCHEMA_VERSION, SCHEMA_VERSION)

    path = tmp_path / "ENERGIZER__CR2032.json"
    path.write_text(json.dumps(_library_doc()), encoding="utf-8")
    assert _normalize_cell_specification(path).to_record()["schema_version"] == SCHEMA_VERSION
    assert derive_cell_spec(path).to_record()["schema_version"] == SCHEMA_VERSION


def test_the_converter_stamps_the_current_version_unless_asked_for_another() -> None:
    from battinfo.interop.converter import import_converter_jsonld_record

    sample = ROOT / "tests" / "fixtures" / "converter" / "coin-cell.converter.sample.jsonld"
    assert import_converter_jsonld_record(sample).specification.to_record()["schema_version"] == SCHEMA_VERSION
    asked = import_converter_jsonld_record(sample, schema_version="0.1.0")
    assert asked.specification.schema_version == "0.1.0"


_READ_BACK_EXAMPLES = [
    (CellSpec, "cell-spec/cell-spec-0hpw-gkhk-gcg8-23x1.json"),
    (Cell, "cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json"),
    (TestSpec, "test-protocol/test-protocol-13rn-1rjs-m94s-m7cq.json"),
    (Test, "test/test-1n7q-5r3k-8x4p-6m2t.json"),
    (Dataset, "dataset/dataset-1f8r-6v2k-9p4m-3t7x.json"),
]


@pytest.mark.parametrize(("model", "example"), _READ_BACK_EXAMPLES, ids=[m.__name__ for m, _ in _READ_BACK_EXAMPLES])
def test_a_record_read_back_keeps_its_version_and_one_stating_none_gets_the_current(model, example: str) -> None:
    record = json.loads((_EXAMPLES / example).read_text(encoding="utf-8"))
    stored = dict(record, schema_version="1.0.0")
    assert model.from_record(stored).to_record()["schema_version"] == "1.0.0"
    unstamped = {key: value for key, value in record.items() if key != "schema_version"}
    assert model.from_record(unstamped).to_record()["schema_version"] == SCHEMA_VERSION


def test_the_staging_loader_gives_an_unstamped_cell_spec_the_current_version() -> None:
    from battinfo.api._staging import _staging_cell_spec_input

    record = json.loads(_CELL_SPEC_EXAMPLE.read_text(encoding="utf-8"))
    del record["schema_version"]
    spec, _ = _staging_cell_spec_input(record)
    assert spec.schema_version == SCHEMA_VERSION


@pytest.mark.parametrize(("stated", "expected"), [
    ("1.0.0", "1.0.0"), ("0.1.0", "0.1.0"), ("9.9.9", "9.9.9"),
    (None, SCHEMA_VERSION), ("", SCHEMA_VERSION), ("  ", SCHEMA_VERSION),
])
def test_a_stored_version_is_kept_and_a_missing_one_is_the_current(stated: object, expected: str) -> None:
    record = {} if stated is None else {"schema_version": stated}
    assert _stored_schema_version(record) == expected
