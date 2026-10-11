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
from battinfo.bundle import SCHEMA_VERSION, SUPERSEDED_SCHEMA_VERSIONS, CellSpec, Dataset, ProvenanceInfo
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
