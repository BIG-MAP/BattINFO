"""
Tests for staging dataset promotion (api.promote_staging_dataset and helpers).

Validation is monkeypatched so these tests exercise the promotion mechanics
(record-id resolution, curated path, citation pass-through, dry-run) without
depending on the full dataset schema being satisfied.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo.api import (
    _dataset_record_id,
    _staging_dataset_identity,
    promote_staging_dataset,
    validate_staging_dataset,
)


class _FakeReport:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.issues: list = []

    def render_errors(self) -> list[str]:
        return ["boom"]


def _dataset_record(identifier: str | None = "bdc:bdc_000001") -> dict:
    dataset = {
        "id": "https://w3id.org/battinfo/dataset/zhft-sytr-hpk5-6630",
        "short_id": "zhftsy",
        "name": "Test dataset",
        "citations": [
            {"kind": "dataset", "url": "https://doi.org/10.5281/zenodo.1", "doi": "10.5281/zenodo.1"},
            {"kind": "article", "url": "https://doi.org/10.1/x", "doi": "10.1/x"},
        ],
    }
    if identifier is not None:
        dataset["identifier"] = identifier
    return {"schema_version": "0.2.0", "dataset": dataset, "provenance": {}}


class TestRecordId:
    def test_preserves_bdc_scheme(self) -> None:
        assert _dataset_record_id("bdc:bdc_000001") == "bdc_000001"
        assert _dataset_record_id("bdc_000001") == "bdc_000001"
        assert _dataset_record_id("BDC_000002") == "bdc_000002"


class TestIdentity:
    def test_prefers_identifier(self) -> None:
        ident = _staging_dataset_identity(_dataset_record(), None)
        assert ident["record_id"] == "bdc_000001"
        assert ident["record_id_basis"] == "identifier"
        assert ident["requires_record_id"] is False

    def test_falls_back_to_short_id(self) -> None:
        ident = _staging_dataset_identity(_dataset_record(identifier=None), None)
        assert ident["record_id"] == "zhftsy"
        assert ident["record_id_basis"] == "short_id"

    def test_falls_back_to_filename(self, tmp_path: Path) -> None:
        record = _dataset_record(identifier=None)
        record["dataset"].pop("short_id")
        ident = _staging_dataset_identity(record, tmp_path / "bdc_000009.json")
        assert ident["record_id"] == "bdc_000009"
        assert ident["record_id_basis"] == "filename"


class TestPromote:
    @patch("battinfo.api.validate_record_report", return_value=_FakeReport(ok=True))
    def test_writes_curated_record_with_citations(self, _mock, tmp_path: Path) -> None:
        curated = tmp_path / "records" / "dataset"
        out = promote_staging_dataset(_dataset_record(), curated_root=curated)
        target = curated / "bdc_000001" / "record.json"
        assert out["status"] == "ok"
        assert out["record_id"] == "bdc_000001"
        assert Path(out["target_path"]) == target
        assert target.exists()
        written = json.loads(target.read_text(encoding="utf-8"))
        dois = [c["doi"] for c in written["dataset"]["citations"]]
        assert "10.1/x" in dois  # article citation (the publication link) preserved

    @patch("battinfo.api.validate_record_report", return_value=_FakeReport(ok=True))
    def test_record_id_override(self, _mock, tmp_path: Path) -> None:
        out = promote_staging_dataset(_dataset_record(), curated_root=tmp_path, record_id="bdc_999999")
        assert out["record_id"] == "bdc_999999"
        assert out["record_id_basis"] == "manual"

    @patch("battinfo.api.validate_record_report", return_value=_FakeReport(ok=True))
    def test_dry_run_writes_nothing(self, _mock, tmp_path: Path) -> None:
        curated = tmp_path / "records" / "dataset"
        out = promote_staging_dataset(_dataset_record(), curated_root=curated, dry_run=True)
        assert out["dry_run"] is True
        assert not (curated / "bdc_000001" / "record.json").exists()

    @patch("battinfo.api.validate_record_report", return_value=_FakeReport(ok=False))
    def test_raises_on_invalid(self, _mock, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="validation failed"):
            promote_staging_dataset(_dataset_record(), curated_root=tmp_path)

    @patch("battinfo.api.validate_record_report", return_value=_FakeReport(ok=True))
    def test_validate_only_does_not_write(self, _mock, tmp_path: Path) -> None:
        out = validate_staging_dataset(_dataset_record())
        assert out["ok"] is True
        assert out["record_id"] == "bdc_000001"
