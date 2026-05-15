from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo.validate.jsonld as validate_jsonld_module
from battinfo.validate import (
    DEFAULT_POLICY,
    INGEST_POLICY,
    PUBLISHER_POLICY,
    STRICT_POLICY,
    ValidationPolicy,
    get_validation_policy,
    validate_json,
    validate_json_report,
    validate_jsonld,
    validate_jsonld_report,
    validate_publication_report,
    validate_references_report,
)


def test_validate_json_report_exposes_structured_schema_issue() -> None:
    doc = {
        "schema_version": "1.0.0",
        "product": {
            "id": "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5",
            "name": "A123 ANR26650M1-B",
            "manufacturer": {"type": "Organization", "name": "A123"},
            "model": "ANR26650M1-B",
            "cellFormat": "cylindrical",
            "chemistry": "Li-ion",
            "positiveElectrodeBasis": "LFP",
            "negativeElectrodeBasis": "graphite",
        },
        "provenance": {
            "source_type": "datasheet",
            "source_file": "A123__ANR26650M1-B.pdf",
            "retrieved_at": "not-an-integer",
        },
    }
    report = validate_json_report(doc, profile="cell-type")
    assert not report.ok
    assert report.policy.name == "default"
    assert report.errors
    issue = report.errors[0]
    assert issue.code == "schema.type"
    assert issue.path == "provenance.retrieved_at"
    assert issue.profile == "cell-type"
    assert issue.validator == "type"


def test_validate_json_result_preserves_structured_issues() -> None:
    doc = {
        "schema_version": "1.0.0",
        "product": {
            "id": "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5",
            "name": "A123 ANR26650M1-B",
            "manufacturer": {"type": "Organization", "name": "A123"},
            "model": "ANR26650M1-B",
            "cellFormat": "cylindrical",
            "chemistry": "Li-ion",
            "positiveElectrodeBasis": "LFP",
            "negativeElectrodeBasis": "graphite",
        },
        "provenance": {
            "source_type": "datasheet",
            "source_file": "A123__ANR26650M1-B.pdf",
            "retrieved_at": "not-an-integer",
        },
    }
    result = validate_json(doc, profile="cell-type")
    assert not result.ok
    assert result.policy == "default"
    assert result.issues
    assert result.issues[0].code == "schema.type"
    assert any("retrieved_at" in err for err in result.errors)


def test_validate_json_report_unknown_profile_has_stable_issue_code() -> None:
    report = validate_json_report({}, profile="not-a-profile", policy=ValidationPolicy(name="strict"))
    assert not report.ok
    assert report.policy.name == "strict"
    assert report.errors[0].code == "schema.profile_unknown"


def test_validate_jsonld_report_exposes_structured_issue() -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [{"@id": "https://example.org/x", "@type": "Real"}],
    }
    report = validate_jsonld_report(payload)
    assert not report.ok
    assert report.errors[0].code == "jsonld.type_term_unknown"
    assert report.errors[0].path == "@graph[0].@type"


def test_validate_jsonld_result_preserves_issue_metadata() -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [{"@id": "https://example.org/x", "@type": "Real"}],
    }
    result = validate_jsonld(payload)
    assert not result.ok
    assert result.issues[0].code == "jsonld.type_term_unknown"
    assert "relative @type reference 'Real'" in result.errors[0]


def test_validate_jsonld_report_detects_rdf_parse_failure() -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [{"@id": "https://example.org/x", "@reverse": "not-an-object"}],
    }
    report = validate_jsonld_report(payload)
    assert not report.ok
    assert any(issue.code == "jsonld.parse_error" for issue in report.errors)


def test_validate_jsonld_report_accepts_valid_payload_with_urdna2015() -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [
            {
                "@id": "https://example.org/x",
                "@type": ["BatteryCell", "schema:ProductModel"],
                "schema:name": "Example battery",
            }
        ],
    }
    report = validate_jsonld_report(payload)
    assert report.ok


def test_validate_jsonld_report_falls_back_when_requests_loader_is_unavailable(monkeypatch) -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [
            {
                "@id": "https://example.org/x",
                "@type": ["BatteryCell", "schema:ProductModel"],
                "schema:name": "Example battery",
            }
        ],
    }

    class _FakeResponse:
        def __init__(self, document: dict[str, object]) -> None:
            self._document = document
            self.headers = self

        def get_content_charset(self) -> str:
            return "utf-8"

        def geturl(self) -> str:
            return "https://w3id.org/emmo/domain/battery/context"

        def read(self) -> bytes:
            return json.dumps(self._document).encode("utf-8")

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    validate_jsonld_module._pyld_base_document_loader.cache_clear()
    validate_jsonld_module._cached_pyld_document.cache_clear()

    def _broken_requests_loader(*, timeout: int = 10):
        raise ModuleNotFoundError("No module named 'requests'")

    monkeypatch.setattr(validate_jsonld_module.pyld_jsonld, "requests_document_loader", _broken_requests_loader)
    monkeypatch.setattr(
        validate_jsonld_module,
        "urlopen",
        lambda request, timeout=10: _FakeResponse(
            {
                "@context": {
                    "schema": "https://schema.org/",
                    "BatteryCell": "https://w3id.org/emmo/domain/battery#BatteryCell",
                }
            }
        ),
    )

    report = validate_jsonld_report(payload)

    assert report.ok


def test_validate_publication_report_detects_invalid_dataset_distribution() -> None:
    payload = {
        "@context": {
            "schema": "https://schema.org/",
        },
        "@graph": [
            {
                "@id": "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
                "@type": "schema:Dataset",
                "schema:about": [{"@id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"}],
                "schema:distribution": [
                    {
                        "@type": "schema:DataDownload",
                        "schema:contentUrl": "not-a-uri",
                        "schema:sha256": "1234",
                        "schema:isPartOf": {"@id": "not-a-uri"},
                    }
                ],
            }
        ],
    }
    report = validate_publication_report(payload, policy="publisher")
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "publication.reference_missing_node" in codes
    assert "publication.distribution_url_invalid" in codes
    assert "publication.distribution_checksum_invalid" in codes
    assert "publication.distribution_missing_field" in codes


def test_validate_publication_report_detects_invalid_distribution_shape() -> None:
    payload = {
        "@context": {
            "schema": "https://schema.org/",
        },
        "@id": "https://example.org/publication",
        "@type": "schema:Dataset",
        "schema:distribution": "not-a-list",
    }
    report = validate_publication_report(payload, policy="publisher")
    assert not report.ok
    assert any(issue.code == "publication.distribution_invalid" for issue in report.errors)


def test_get_validation_policy_returns_named_policies() -> None:
    assert get_validation_policy("default") is DEFAULT_POLICY
    assert get_validation_policy("strict") is STRICT_POLICY
    assert get_validation_policy("publisher") is PUBLISHER_POLICY
    assert get_validation_policy("ingest") is INGEST_POLICY


def test_get_validation_policy_rejects_unknown_name() -> None:
    try:
        get_validation_policy("unknown-policy")
    except ValueError as exc:
        assert "Unknown validation policy" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown validation policy")


def test_validate_references_report_detects_missing_reference(tmp_path: Path) -> None:
    report = validate_references_report(
        {
            "schema_version": "0.1.0",
            "cell_instance": {
                "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
                "identifier": "cell:1f8r-6v2k-9p4m-3t7x",
                "type_id": "https://w3id.org/battinfo/cell-type/eysh-4h5s-k4bx-zkgg",
            },
            "provenance": {
                "source_type": "measurement",
                "retrieved_at": 1771804800,
            },
        },
        tmp_path,
    )
    assert not report.ok
    assert report.errors[0].code == "reference.missing"
    assert report.errors[0].path == "cell_instance.type_id"


def test_validate_references_report_detects_wrong_reference_type(tmp_path: Path) -> None:
    datasets_dir = tmp_path / "dataset"
    datasets_dir.mkdir(parents=True)
    dataset_path = datasets_dir / "dataset-87fr-c4vr-wfyh-21td.json"
    dataset_path.write_text(
        """
{
  "schema_version": "0.1.0",
  "dataset": {
    "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
    "identifier": "dataset:87fr-c4vr-wfyh-21td",
    "name": "Wrong type target",
    "url": "https://example.org/dataset/87fr-c4vr-wfyh-21td"
  },
  "provenance": {
    "source_type": "other",
    "retrieved_at": 1771804800
  }
}
""".strip(),
        encoding="utf-8",
    )
    report = validate_references_report(
        {
            "schema_version": "0.1.0",
            "cell_instance": {
                "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
                "identifier": "cell:1f8r-6v2k-9p4m-3t7x",
                "type_id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
            },
            "provenance": {
                "source_type": "measurement",
                "retrieved_at": 1771804800,
            },
        },
        tmp_path,
    )
    assert not report.ok
    assert report.errors[0].code == "reference.type_mismatch"
    assert report.errors[0].path == "cell_instance.type_id"

