"""The cell-instance template carries no placeholder IRI (evaluation finding C-01).

`battinfo template cell-instance` wrote `https://w3id.org/battinfo/cell/0000-0000-0000-0000`
as the record id; `battinfo save cell-instance` saved it as a real record and
strict and publisher validation passed it, so everyone following the
getting-started steps claimed the same IRI. The template now leaves the id out
so a save mints one, and validation rejects a record whose own IRI has the
all-zero uid under every policy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from battinfo import CellSpec
from battinfo.api import save_cell_spec, save_record, template_cell_instance
from battinfo.cli import app
from battinfo.validate import NAMED_POLICIES, validate_record_report

PLACEHOLDER_CELL = "https://w3id.org/battinfo/cell/0000-0000-0000-0000"
CELL_IRI = re.compile(r"^https://w3id\.org/battinfo/cell/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")


def _cli(*args: str) -> dict:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_template_save_validate_mints_a_real_iri(tmp_path: Path) -> None:
    """The reproduction from the evaluation: template, save, validate."""
    root = tmp_path / "examples"
    spec = save_cell_spec(
        CellSpec(manufacturer="Energizer", model="CR2032", format="coin", chemistry="li-metal",
                 properties={"nominal_capacity": {"value": 0.235, "unit": "Ah"}}),
        source_root=root, build_jsonld=False, build_html=False,
    )
    draft = tmp_path / "draft.json"
    _cli("template", "cell-instance", "--cell-spec-id", spec["id"], "--out", str(draft))
    body = json.loads(draft.read_text(encoding="utf-8"))["cell_instance"]
    assert "id" not in body and "short_id" not in body
    assert body["cell_spec_id"] == spec["id"]

    saved = _cli("save", "cell-instance", "--input", str(draft), "--source-root", str(root))
    assert saved["status"] == "created"
    assert CELL_IRI.fullmatch(saved["id"]) and saved["id"] != PLACEHOLDER_CELL

    for policy in ("strict", "publisher"):
        report = _cli("validate", saved["path"], "--source-root", str(root), "--policy", policy,
                      "--format", "json")
        assert report["ok"] is True, report


def test_template_still_pins_an_explicit_uid() -> None:
    record = template_cell_instance(cell_spec_id="https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0",
                                    uid="1f8r6v2k9p4m3t7x")
    assert record["cell_instance"]["id"] == "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x"
    assert "id" not in template_cell_instance()["cell_instance"]


def _placeholder_cell_record() -> dict:
    return {
        "schema_version": "0.2.0",
        "cell_instance": {
            "id": PLACEHOLDER_CELL,
            "short_id": "000000",
            "cell_spec_id": "https://w3id.org/battinfo/spec/8dzc-d9jz-12m6-cg03",
        },
        "provenance": {"source_type": "measurement", "retrieved_at": 1791730794},
    }


@pytest.mark.parametrize("policy", sorted(NAMED_POLICIES))
def test_validation_rejects_the_placeholder_uid_under_every_policy(policy: str) -> None:
    report = validate_record_report(_placeholder_cell_record(), policy=policy)
    assert not report.ok
    errors = [issue for issue in report.errors if issue.code == "identity.placeholder_iri"]
    assert len(errors) == 1
    assert errors[0].path == "cell_instance.id"
    assert "template placeholder" in errors[0].message


def test_placeholder_spec_iri_is_rejected_too() -> None:
    record = {
        "schema_version": "0.2.0",
        "cell_spec": {"id": "https://w3id.org/battinfo/spec/0000-0000-0000-0000", "name": "X Y",
                      "manufacturer": {"type": "Organization", "name": "X"}, "model": "Y",
                      "cell_format": "coin", "chemistry": "li-ion"},
        "provenance": {"source_type": "manual", "retrieved_at": 1791730794},
    }
    report = validate_record_report(record, policy="ingest")
    assert any(issue.code == "identity.placeholder_iri" for issue in report.errors)


def test_save_and_cli_validate_refuse_the_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="template placeholder"):
        save_record(_placeholder_cell_record(), source_root=tmp_path, resolve_references=False,
                    build_jsonld=False, build_html=False)
    path = tmp_path / "cell-0000-0000-0000-0000.json"
    path.write_text(json.dumps(_placeholder_cell_record()), encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(path), "--policy", "ingest", "--format", "json"])
    assert result.exit_code != 0
    assert "template placeholder" in result.stdout
