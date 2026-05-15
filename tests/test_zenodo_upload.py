"""
Tests for zenodo.py — ZenodoClient, patch_zenodo_urls, upload_zenodo_package.

Network calls are never made: ZenodoClient._request is monkey-patched or
upload_zenodo_package is tested via patch_zenodo_urls + metadata-building
only (no live deposits).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo import (
    CellInstance,
    CellType,
    Dataset,
    Test,
    ZenodoCellRecord,
    ZenodoDatasetEntry,
    ZenodoError,
    build_zenodo_package,
    patch_zenodo_urls,
)
from battinfo.bundle import ZENODO_CELL_RECORD_FILENAME, ProvenanceInfo
from battinfo.publication import DEFAULT_PUBLISH_FILENAME, DEFAULT_RO_CRATE_METADATA_FILENAME
from battinfo.zenodo import ZenodoClient, _build_zenodo_metadata, upload_zenodo_package

# ── helpers ────────────────────────────────────────────────────────────────────

CELL_TYPE_ID = "https://w3id.org/battinfo/cell-type/7r2m-4q8v-k6nt-c3pj"
CREATORS = [{"name": "Clark, Simon", "affiliation": "SINTEF"}]


def _make_record(n: int = 2) -> ZenodoCellRecord:
    ct = CellType(
        id=CELL_TYPE_ID,
        name="Energizer CR2032",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        iec_code="CR2032",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        source=ProvenanceInfo(type="datasheet"),
    )
    datasets = []
    for i in range(n):
        idx = f"{i + 1:03d}"
        ci_id = f"https://w3id.org/battinfo/cell/ci-{idx}"
        test_id = f"https://w3id.org/battinfo/test/t-{idx}"
        ds_id = f"https://w3id.org/battinfo/dataset/d-{idx}"
        ci = CellInstance(id=ci_id, name=f"sn-{idx}", cell_type_id=CELL_TYPE_ID,
                          serial_number=f"sn-{idx}", source=ProvenanceInfo(type="measurement"))
        test = Test(id=test_id, name=f"test {idx}", test_kind="capacity_check",
                    cell_instance_id=ci_id, source=ProvenanceInfo(type="measurement"))
        ds = Dataset(id=ds_id, name=f"dataset {idx}", cell_instance_id=ci_id,
                     test_id=test_id, source=ProvenanceInfo(type="measurement"))
        datasets.append(ZenodoDatasetEntry(cell_instances=[ci], test=test, dataset=ds))
    return ZenodoCellRecord(cell_type=ct, datasets=datasets)


def _staged_package(tmp_path: Path, n: int = 2) -> Path:
    """Build a real staged package in tmp_path/staging and return the staging dir."""
    record = _make_record(n)
    src = tmp_path / "src"
    src.mkdir()
    file_sets = []
    for i in range(1, n + 1):
        raw = src / f"raw_{i:03d}.csv"
        raw.write_text("t,V\n0,3.0\n", encoding="utf-8")
        bdf = src / f"bdf_{i:03d}.parquet"
        bdf.write_bytes(b"PAR1")
        file_sets.append((raw, bdf))
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, file_sets)
    return staging


# ── patch_zenodo_urls ─────────────────────────────────────────────────────────

class TestPatchZenodoUrls:
    def test_replaces_placeholder_in_all_files(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        counts = patch_zenodo_urls(staging, "12345678")

        assert counts[DEFAULT_PUBLISH_FILENAME] > 0
        assert counts[DEFAULT_RO_CRATE_METADATA_FILENAME] > 0
        assert counts[ZENODO_CELL_RECORD_FILENAME] >= 0

        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "12345678" in text
        assert "ZENODO_RECORD_ID" not in text

    def test_sandbox_domain_substituted(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        patch_zenodo_urls(staging, "99999", sandbox=True)

        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "sandbox.zenodo.org" in text
        assert "ZENODO_RECORD_ID" not in text

    def test_production_domain_kept(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        patch_zenodo_urls(staging, "77777", sandbox=False)

        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "https://zenodo.org/records/77777" in text

    def test_missing_file_skipped_gracefully(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        (staging / DEFAULT_RO_CRATE_METADATA_FILENAME).unlink()
        counts = patch_zenodo_urls(staging, "55555")
        assert DEFAULT_RO_CRATE_METADATA_FILENAME not in counts

    def test_custom_placeholder(self, tmp_path: Path) -> None:
        record = _make_record(1)
        src = tmp_path / "src"
        src.mkdir()
        raw = src / "raw.csv"
        raw.write_text("t,V\n", encoding="utf-8")
        staging = tmp_path / "staging"
        build_zenodo_package(
            record, staging, [(raw, None)],
            zenodo_record_id_placeholder="MY_PLACEHOLDER",
        )
        patch_zenodo_urls(staging, "12345", placeholder="MY_PLACEHOLDER")
        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "MY_PLACEHOLDER" not in text
        assert "12345" in text


# ── _build_zenodo_metadata ────────────────────────────────────────────────────

class TestBuildZenodoMetadata:
    def _meta(self, **kwargs) -> dict:
        record = _make_record(2)
        defaults = dict(
            creators=CREATORS,
            title=None,
            description=None,
            license="cc-by-4.0",
            community="battinfo-reference",
            extra_keywords=None,
        )
        defaults.update(kwargs)
        return _build_zenodo_metadata(record, **defaults)

    def test_required_fields_present(self) -> None:
        m = self._meta()
        assert m["upload_type"] == "dataset"
        assert m["access_right"] == "open"
        assert isinstance(m["title"], str)
        assert isinstance(m["description"], str)
        assert m["creators"] == CREATORS

    def test_auto_title_includes_cell_name(self) -> None:
        m = self._meta()
        assert "Energizer CR2032" in m["title"]

    def test_explicit_title_used(self) -> None:
        m = self._meta(title="My custom title")
        assert m["title"] == "My custom title"

    def test_keywords_include_cell_fields(self) -> None:
        m = self._meta()
        kw = m["keywords"]
        assert "Energizer" in kw
        assert "CR2032" in kw
        assert "coin" in kw
        assert "Li-primary" in kw
        assert "MnO2" in kw
        assert "Li-metal" in kw

    def test_extra_keywords_appended(self) -> None:
        m = self._meta(extra_keywords=["EMPA", "custom-tag"])
        assert "EMPA" in m["keywords"]
        assert "custom-tag" in m["keywords"]

    def test_community_included(self) -> None:
        m = self._meta()
        assert m["communities"] == [{"identifier": "battinfo-reference"}]

    def test_no_community(self) -> None:
        m = self._meta(community=None)
        assert "communities" not in m

    def test_license_passed_through(self) -> None:
        m = self._meta(license="cc0-1.0")
        assert m["license"] == "cc0-1.0"

    def test_description_mentions_dataset_count(self) -> None:
        m = self._meta()
        assert "2 datasets" in m["description"]


# ── ZenodoClient ──────────────────────────────────────────────────────────────

class TestZenodoClient:
    def _client(self) -> ZenodoClient:
        return ZenodoClient(token="test-token", sandbox=True)

    def test_sandbox_base_url(self) -> None:
        c = ZenodoClient(token="tok", sandbox=True)
        assert "sandbox.zenodo.org" in c._base

    def test_production_base_url(self) -> None:
        c = ZenodoClient(token="tok", sandbox=False)
        assert "zenodo.org" in c._base
        assert "sandbox" not in c._base

    def test_record_url_sandbox(self) -> None:
        c = ZenodoClient(token="tok", sandbox=True)
        assert c.record_url(12345) == "https://sandbox.zenodo.org/records/12345"

    def test_record_url_production(self) -> None:
        c = ZenodoClient(token="tok", sandbox=False)
        assert c.record_url(12345) == "https://zenodo.org/records/12345"

    def test_upload_files_uses_bucket_url(self, tmp_path: Path) -> None:
        c = self._client()
        csv = tmp_path / "data.csv"
        csv.write_text("t,V\n", encoding="utf-8")

        deposit_resp = {"links": {"bucket": "https://sandbox.zenodo.org/api/files/abc123"}}
        file_resp = json.dumps({"links": {"download": "https://sandbox.zenodo.org/api/files/abc123/data.csv"}}).encode()

        with patch.object(c, "get_deposit", return_value=deposit_resp), \
             patch("urllib.request.urlopen") as mock_open:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_resp)))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_cm

            result = c.upload_files(1, {csv: "data.csv"})

        assert csv in result
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://sandbox.zenodo.org/api/files/abc123/data.csv"
        assert req.get_method() == "PUT"

    def test_upload_files_no_double_request(self, tmp_path: Path) -> None:
        """Verify the old spurious self._request call is gone."""
        c = self._client()
        csv = tmp_path / "data.csv"
        csv.write_text("t,V\n", encoding="utf-8")

        deposit_resp = {"links": {"bucket": "https://sandbox.zenodo.org/api/files/abc"}}
        file_resp = json.dumps({"links": {"download": "https://x"}}).encode()

        request_call_count = 0
        original_request = c._request

        def counting_request(*args, **kwargs):
            nonlocal request_call_count
            request_call_count += 1
            return original_request(*args, **kwargs)

        with patch.object(c, "get_deposit", return_value=deposit_resp), \
             patch.object(c, "_request", side_effect=counting_request), \
             patch("urllib.request.urlopen") as mock_open:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=file_resp)))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_cm
            c.upload_files(1, {csv: "data.csv"})

        # _request should NOT be called during upload_files (only urlopen)
        assert request_call_count == 0


# ── upload_zenodo_package (mocked network) ────────────────────────────────────

class TestUploadZenodoPackage:
    def _mock_client(self, record_id: int = 12345) -> MagicMock:
        mock = MagicMock(spec=ZenodoClient)
        mock.create_empty_deposit.return_value = {
            "id": 99999,
            "record_id": record_id,
            "metadata": {"prereserve_doi": {"doi": f"10.5281/zenodo.{record_id}"}},
        }
        mock.upload_files.return_value = {}
        mock.update_metadata.return_value = {}
        return mock

    def test_full_workflow_mocked(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        mock_client = self._mock_client(12345)

        with patch("battinfo.zenodo.ZenodoClient", return_value=mock_client), \
             patch("battinfo.zenodo._resolve_token", return_value="tok"):
            result = upload_zenodo_package(staging, CREATORS, token="tok")

        assert result["deposit_id"] == 99999
        assert result["record_id"] == 12345
        assert "12345" in result["record_url"]
        assert result["doi"] == "10.5281/zenodo.12345"
        assert result["published"] is False
        mock_client.create_empty_deposit.assert_called_once()
        mock_client.upload_files.assert_called_once()
        mock_client.update_metadata.assert_called_once()
        mock_client.publish_deposit.assert_not_called()

    def test_publish_flag_calls_publish(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        mock_client = self._mock_client()

        with patch("battinfo.zenodo.ZenodoClient", return_value=mock_client), \
             patch("battinfo.zenodo._resolve_token", return_value="tok"):
            result = upload_zenodo_package(staging, CREATORS, token="tok", publish=True)

        assert result["published"] is True
        mock_client.publish_deposit.assert_called_once()

    def test_placeholder_replaced_before_upload(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        mock_client = self._mock_client(record_id=88888)

        with patch("battinfo.zenodo.ZenodoClient", return_value=mock_client), \
             patch("battinfo.zenodo._resolve_token", return_value="tok"):
            upload_zenodo_package(staging, CREATORS, token="tok")

        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "ZENODO_RECORD_ID" not in text
        assert "88888" in text

    def test_missing_bundle_raises(self, tmp_path: Path) -> None:
        staging = tmp_path / "empty_staging"
        staging.mkdir()
        with pytest.raises(FileNotFoundError, match="battinfo.bundle.json"):
            upload_zenodo_package(staging, CREATORS, token="tok")

    def test_empty_creators_raises(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        with pytest.raises(ValueError, match="creators"):
            upload_zenodo_package(staging, [], token="tok")

    def test_no_token_raises(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        import os
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ZENODO_API_TOKEN", None)
            with pytest.raises(ZenodoError, match="token"):
                upload_zenodo_package(staging, CREATORS)

    def test_sandbox_flag_passed_to_client(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path)
        mock_client = self._mock_client()

        with patch("battinfo.zenodo.ZenodoClient", return_value=mock_client) as MockCls, \
             patch("battinfo.zenodo._resolve_token", return_value="tok"):
            result = upload_zenodo_package(staging, CREATORS, token="tok", sandbox=True)

        MockCls.assert_called_once_with(token="tok", sandbox=True)
        assert result["sandbox"] is True

    def test_all_staged_files_uploaded(self, tmp_path: Path) -> None:
        staging = _staged_package(tmp_path, n=2)
        mock_client = self._mock_client()
        captured_files: dict = {}

        def capture_upload(deposit_id, files, **kwargs):
            captured_files.update(files)
            return {}

        mock_client.upload_files.side_effect = capture_upload

        with patch("battinfo.zenodo.ZenodoClient", return_value=mock_client), \
             patch("battinfo.zenodo._resolve_token", return_value="tok"):
            upload_zenodo_package(staging, CREATORS, token="tok")

        uploaded_names = {p.name for p in captured_files}
        assert DEFAULT_PUBLISH_FILENAME in uploaded_names
        assert ZENODO_CELL_RECORD_FILENAME in uploaded_names
        assert DEFAULT_RO_CRATE_METADATA_FILENAME in uploaded_names
        assert "dataset-001.csv" in uploaded_names
        assert "dataset-001.bdf.parquet" in uploaded_names
