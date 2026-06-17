"""Tests for the actionable-artifact layer (Layer B): linking runnable protocol
files on test specs and tests, round-tripping records, and emitting them as
dcat:Distribution nodes in the published JSON-LD."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import Artifact, Test, TestSpec  # noqa: E402
from battinfo.validate import validate_json  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

SPEC_ID = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
CELL_ID = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
TEST_ID = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-dddd"


def test_test_spec_artifact_roundtrip_and_validates() -> None:
    spec = TestSpec(
        id=SPEC_ID, name="CC discharge", test_kind="capacity_check",
        experiment=["Discharge at C/10 until 2.5 V"],
        artifacts=[Artifact(
            role="source_protocol", format="aurora-unicycler-json",
            locator="files/cc.unicycler.json",
            conforms_to="https://github.com/EmpaEconversion/aurora-unicycler",
            sha256="a" * 64, byte_size=1024, generated=["biologic-mps"],
        )],
        source={"type": "manual", "retrieved_at": 1781589239},
    )
    record = spec.to_record()
    assert record["artifacts"][0]["role"] == "source_protocol"
    assert record["artifacts"][0]["format"] == "aurora-unicycler-json"
    assert validate_json(record, profile="test-protocol").ok

    back = TestSpec.from_record(record)
    assert back.artifacts[0].locator == "files/cc.unicycler.json"
    assert back.artifacts[0].generated == ["biologic-mps"]


def test_test_artifact_roundtrip_and_validates() -> None:
    test = Test(
        id=TEST_ID, name="cc run", test_kind="capacity_check",
        cell_instance_id=CELL_ID,
        artifacts=[Artifact(role="executed_protocol", format="biologic-mps",
                            locator="files/run.mps")],
        source={"type": "measurement", "retrieved_at": 1781589239},
    )
    record = test.to_record()
    assert record["artifacts"][0]["role"] == "executed_protocol"
    assert validate_json(record, profile="test").ok
    assert Test.from_record(record).artifacts[0].format == "biologic-mps"


def test_plan_artifact_inclusion_only_includes_workspace_files(tmp_path) -> None:
    from battinfo.publication import plan_artifact_inclusion

    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "in.unicycler.json").write_text("{}", encoding="utf-8")
    records = [{
        "artifacts": [
            {"role": "source_protocol", "format": "aurora-unicycler-json",
             "locator": "files/in.unicycler.json"},                      # in workspace → include
            {"role": "executed_protocol", "format": "biologic-mps",
             "locator": "/somewhere/else/run.mps"},                      # absolute, elsewhere → warn
            {"role": "source_protocol", "format": "pybamm-experiment",
             "locator": "files/missing.py"},                            # relative, missing → warn
            {"role": "vendor_export", "format": "neware-xml",
             "locator": "https://example.org/remote.xml"},               # remote → no upload, no warn
        ]
    }]
    included, warnings = plan_artifact_inclusion(records, tmp_path)

    assert [p.name for p in included] == ["in.unicycler.json"]
    assert len(warnings) == 2
    assert any("run.mps" in w for w in warnings)
    assert any("missing.py" in w for w in warnings)
    assert all("remote.xml" not in w for w in warnings)


def test_check_artifact_conformance_warns_on_divergence(tmp_path) -> None:
    import json

    from battinfo.publication import check_artifact_conformance

    # An aurora-unicycler file describing a CC charge + CV hold + CC discharge.
    aurora = {
        "method": [
            {"step": "constant_current", "rate_C": "1", "until_voltage_V": "4.2"},
            {"step": "constant_voltage", "voltage_V": "4.2", "until_rate_C": "0.05"},
            {"step": "constant_current", "rate_C": "-1", "until_voltage_V": "2.5"},
        ]
    }
    (tmp_path / "cc.unicycler.json").write_text(json.dumps(aurora), encoding="utf-8")

    artifact = {"role": "source_protocol", "format": "aurora-unicycler-json",
                "locator": "cc.unicycler.json"}

    # Spec facets that LIE about the method (claim no CV hold) → divergence warning.
    diverging = {"facets": {"has_cv_hold": False, "modes": ["cc"]}, "artifacts": [artifact]}
    warnings = check_artifact_conformance(diverging, tmp_path)
    assert warnings and "has_cv_hold" in warnings[0]

    # Facets consistent with the artifact → no warning.
    consistent = {"facets": {"has_cv_hold": True}, "artifacts": [artifact]}
    assert check_artifact_conformance(consistent, tmp_path) == []

    # Artifact outside the workspace is skipped (not a conformance failure).
    external = {"facets": {"has_cv_hold": False},
                "artifacts": [{"role": "source_protocol", "format": "aurora-unicycler-json",
                               "locator": "/elsewhere/cc.unicycler.json"}]}
    assert check_artifact_conformance(external, tmp_path) == []


def test_artifacts_emit_dcat_distributions_in_jsonld() -> None:
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        {
            "cell-spec": [], "cell-instance": [], "test": [],
            "test-protocol": [{
                "test_spec": {"id": SPEC_ID, "name": "CC discharge", "kind": "capacity_check"},
                "method": [{"mode": "cc", "direction": "discharge",
                            "setpoints": {"c_rate": {"value": 0.1, "unit": "A/Ah"}},
                            "termination": [{"quantity": "voltage", "direction": "below",
                                             "value": 2.5, "unit": "V"}]}],
                "artifacts": [{"role": "source_protocol", "format": "aurora-unicycler-json",
                               "locator": "files/cc.unicycler.json",
                               "media_type": "application/json",
                               "conforms_to": "https://github.com/EmpaEconversion/aurora-unicycler"}],
            }],
            "dataset": [],
        },
        zenodo_record_id=0, prereserved_doi="", record_url="https://example.org/records/0",
        data_filenames=[], title="t", description="d",
    )
    plan = next(n for n in doc["@graph"] if "prov:Plan" in (n.get("@type") or []))
    dist = plan["dcat:distribution"][0]
    assert dist["@type"] == "dcat:Distribution"
    # Standard vocabulary only — no custom battinfo: artifact terms.
    assert dist["dcterms:type"] == "source_protocol"
    assert dist["dcterms:format"] == "aurora-unicycler-json"
    # Not uploaded (no data_filenames) → keep the relative locator literal.
    assert dist["dcat:downloadURL"] == "files/cc.unicycler.json"
    assert dist["dcterms:conformsTo"] == {"@id": "https://github.com/EmpaEconversion/aurora-unicycler"}
    assert not any(k.startswith("battinfo:") for k in dist)
    # The descriptive method still emits alongside the actionable link.
    assert plan["hasTask"][0]["@type"] == "ConstantCurrentDischarging"


def test_artifact_download_url_resolves_to_hosted_when_uploaded() -> None:
    from battinfo.ws import AuthoringWorkspace

    record = {
        "test_spec": {"id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                      "name": "CC", "kind": "capacity_check"},
        "artifacts": [{"role": "source_protocol", "format": "aurora-unicycler-json",
                       "locator": "files/cc.unicycler.json"}],
    }
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        {"cell-spec": [], "cell-instance": [], "test": [],
         "test-protocol": [record], "dataset": []},
        zenodo_record_id=42, prereserved_doi="", record_url="https://zenodo.org/records/42",
        data_filenames=["cc.unicycler.json"],            # the file IS being uploaded
        files_base_url="https://zenodo.org/records/42/files",
        title="t", description="d",
    )
    plan = next(n for n in doc["@graph"] if "prov:Plan" in (n.get("@type") or []))
    dist = plan["dcat:distribution"][0]
    # Uploaded → download URL points at the hosted file, as a resolvable IRI.
    assert dist["dcat:downloadURL"] == {"@id": "https://zenodo.org/records/42/files/cc.unicycler.json"}
