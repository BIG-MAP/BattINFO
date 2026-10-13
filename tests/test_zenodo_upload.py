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
    Cell,
    CellSpec,
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
from battinfo.ws import _plan_zenodo_deposit
from battinfo.zenodo import (
    ZenodoClient,
    _build_zenodo_metadata,
    _file_md5,
    _zenodo_checksum_matches,
    upload_zenodo_package,
)


class TestChecksumMatch:
    def test_matches_bare_md5(self, tmp_path: Path) -> None:
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello world")
        assert _zenodo_checksum_matches(f, _file_md5(f)) is True

    def test_matches_prefixed_md5(self, tmp_path: Path) -> None:
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello world")
        assert _zenodo_checksum_matches(f, f"md5:{_file_md5(f)}") is True

    def test_mismatch_and_missing_are_false(self, tmp_path: Path) -> None:
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello world")
        assert _zenodo_checksum_matches(f, "deadbeef") is False
        assert _zenodo_checksum_matches(f, None) is False
        assert _zenodo_checksum_matches(f, "sha256:" + _file_md5(f)) is False  # non-md5 → re-upload


class TestSyncFiles:
    def test_keeps_unchanged_uploads_changed_removes_gone(self, tmp_path: Path) -> None:
        keep = tmp_path / "data.csv"
        keep.write_bytes(b"UNCHANGED-DATA")
        changed = tmp_path / "battinfo.json"
        changed.write_bytes(b"NEW-CONTENT")
        added = tmp_path / "ro-crate-metadata.json"
        added.write_bytes(b"BRAND-NEW")
        files = {keep: "data.csv", changed: "battinfo.json", added: "ro-crate-metadata.json"}

        c = ZenodoClient(token="t", sandbox=True)
        existing = [
            {"id": "f1", "filename": "data.csv", "checksum": _file_md5(keep)},   # unchanged
            {"id": "f2", "filename": "battinfo.json", "checksum": "deadbeef"},    # changed
            {"id": "f3", "filename": "old.txt", "checksum": "whatever"},          # removed
        ]
        deleted: list[str] = []
        uploaded: dict = {}
        c.list_files = lambda dep: existing                       # type: ignore[assignment]
        c.delete_file = lambda dep, fid: deleted.append(fid)      # type: ignore[assignment]
        c.upload_files = lambda dep, mp: (uploaded.update(mp), {})[1]  # type: ignore[assignment]

        out = c.sync_files(1, files)

        assert out["kept"] == ["data.csv"]                        # unchanged → not uploaded
        assert set(out["uploaded"]) == {"battinfo.json", "ro-crate-metadata.json"}
        assert out["removed"] == ["old.txt"]
        assert "f1" not in deleted                                # kept file never deleted
        assert "f2" in deleted and "f3" in deleted                # changed + removed deleted
        assert set(uploaded.values()) == {"battinfo.json", "ro-crate-metadata.json"}


class TestPlanZenodoDeposit:
    """Re-running ws.zenodo() never errors on an existing record — it warns and
    moves the workflow forward."""

    def test_first_run_creates_new_record(self) -> None:
        assert _plan_zenodo_deposit(None, False, None) == (None, None, None)

    def test_explicit_record_id_passes_through_without_warning(self) -> None:
        assert _plan_zenodo_deposit("123", True, "456") == ("456", None, None)

    def test_existing_published_forks_new_version_with_warning(self) -> None:
        record_id, reuse, warn = _plan_zenodo_deposit("123", True, None)
        assert record_id == "123" and reuse is None
        assert warn and "NEW VERSION" in warn

    def test_existing_draft_is_updated_in_place_with_warning(self) -> None:
        record_id, reuse, warn = _plan_zenodo_deposit("513896", False, None)
        assert record_id is None and reuse == "513896"
        assert warn and "draft" in warn.lower()


# ── helpers ────────────────────────────────────────────────────────────────────

CELL_TYPE_ID = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
CREATORS = [{"name": "Clark, Simon", "affiliation": "SINTEF"}]


def _make_record(n: int = 2) -> ZenodoCellRecord:
    ct = CellSpec(
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
        ci = Cell(id=ci_id, name=f"sn-{idx}", cell_spec_id=CELL_TYPE_ID,
                          serial_number=f"sn-{idx}", source=ProvenanceInfo(type="measurement"))
        test = Test(id=test_id, name=f"test {idx}", test_kind="capacity_check",
                    cell_instance_id=ci_id, source=ProvenanceInfo(type="measurement"))
        ds = Dataset(id=ds_id, name=f"dataset {idx}", cell_instance_id=ci_id,
                     test_id=test_id, source=ProvenanceInfo(type="measurement"))
        datasets.append(ZenodoDatasetEntry(cell_instances=[ci], test=test, dataset=ds))
    return ZenodoCellRecord(cell_spec=ct, datasets=datasets)


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

    def test_no_related_identifiers_without_citations(self) -> None:
        # _make_record builds datasets with no citations → no related_identifiers key.
        m = self._meta()
        assert "related_identifiers" not in m

    def test_article_citations_become_related_identifiers(self) -> None:
        record = _make_record(2)
        # Self-citation (the dataset's own DOI) must be excluded; the article kept.
        record.datasets[0].dataset.citations = [
            {"kind": "dataset", "doi": "10.5281/zenodo.123"},
            {"kind": "article", "doi": "10.1038/s41467-020-15235-7"},
        ]
        # Same article on a second dataset (dedup) + a distinct article.
        record.datasets[1].dataset.citations = [
            {"kind": "article", "doi": "10.1038/s41467-020-15235-7"},
            {"kind": "article", "doi": "10.1016/j.ijepes.2018.12.016"},
        ]
        m = _build_zenodo_metadata(
            record,
            creators=CREATORS,
            title=None,
            description=None,
            license="cc-by-4.0",
            community=None,
            extra_keywords=None,
        )
        rels = m["related_identifiers"]
        dois = [r["identifier"] for r in rels]
        assert "10.5281/zenodo.123" not in dois            # self-citation excluded
        assert dois.count("10.1038/s41467-020-15235-7") == 1  # deduped across datasets
        assert "10.1016/j.ijepes.2018.12.016" in dois
        assert all(r["relation"] == "isSupplementTo" and r["scheme"] == "doi" for r in rels)
        assert all(r.get("resource_type") == "publication-article" for r in rels)


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


class TestTypedDate:
    """_typed_date wraps record date values for the publication JSON-LD.

    Records store manufactured_at/expires_at as Unix timestamps (int); the
    assembler used to crash on them (AttributeError: int has no strip) as soon
    as a cell carried a production date.
    """

    def test_unix_timestamp_becomes_utc_xsd_date(self) -> None:
        from battinfo.ws import _typed_date

        # 2026-01-15T00:00:00Z — must not shift with the local timezone.
        assert _typed_date(1768435200) == {"@value": "2026-01-15", "@type": "xsd:date"}

    def test_string_shapes_keep_their_datatypes(self) -> None:
        from battinfo.ws import _typed_date

        assert _typed_date("2026")["@type"] == "xsd:gYear"
        assert _typed_date("2026-01")["@type"] == "xsd:gYearMonth"
        assert _typed_date("2026-01-15")["@type"] == "xsd:date"
        assert _typed_date("2026-01-15T12:00:00Z")["@type"] == "xsd:dateTime"


class TestZenodoOnlyPublicPath:
    """Zenodo is the public publish path: no R2 required (red-team W1.2)."""

    def test_apply_zenodo_file_urls_patches_records(self, tmp_path: Path) -> None:
        from battinfo import workspace

        ws = workspace(root=tmp_path)
        data = tmp_path / "run1.csv"
        data.write_text("cycle,cap\n1,4.9\n", encoding="utf-8")
        ds_dir = ws._ws.source_root / "dataset"
        ds_dir.mkdir(parents=True)
        record = {
            "schema_version": "0.2.0",
            "dataset": {
                "id": "https://w3id.org/battinfo/dataset/7d9k-2m4p-8t3x-6nq5",
                "short_id": "7d9k2m",
                "access_url": data.as_uri(),
                "distributions": [
                    {"type": "DataDownload", "content_url": data.as_uri()}
                ],
            },
        }
        rec_path = ds_dir / "dataset-7d9k.json"
        rec_path.write_text(json.dumps(record), encoding="utf-8")

        n = ws._apply_zenodo_file_urls(
            "https://zenodo.org/records/12345", ws._deposit_file_plan(ws._ws.source_root)
        )
        assert n == 1
        patched = json.loads(rec_path.read_text(encoding="utf-8"))["dataset"]
        assert patched["access_url"] == "https://zenodo.org/records/12345/files/run1.csv"
        assert patched["distributions"][0]["content_url"].startswith("https://zenodo.org/")
        assert patched["distributions"][0]["checksum"]["algorithm"] == "sha256"

    def test_files_not_in_deposit_are_untouched(self, tmp_path: Path) -> None:
        from battinfo import workspace
        from battinfo._deposit_files import build_deposit_file_plan

        ws = workspace(root=tmp_path)
        (tmp_path / "run1.csv").write_text("cycle,cap\n1,4.9\n", encoding="utf-8")
        ds_dir = ws._ws.source_root / "dataset"
        ds_dir.mkdir(parents=True)
        record = {
            "schema_version": "0.2.0",
            "dataset": {
                "id": "https://w3id.org/battinfo/dataset/7d9k-2m4p-8t3x-6nq5",
                "distributions": [{"type": "DataDownload", "content_url": "file:///x/other.csv"}],
            },
        }
        (ds_dir / "d.json").write_text(json.dumps(record), encoding="utf-8")
        plan = build_deposit_file_plan([((tmp_path / "run1.csv").as_uri(), "other")], root=tmp_path)
        assert ws._apply_zenodo_file_urls("https://zenodo.org/records/1", plan) == 0

    def test_r2_configured_reads_env(self, tmp_path: Path, monkeypatch) -> None:
        from battinfo import workspace

        ws = workspace(root=tmp_path)
        monkeypatch.delenv("R2_ENDPOINT", raising=False)
        assert ws._r2_configured() is False
        monkeypatch.setenv("R2_ENDPOINT", "https://acc.eu.r2.cloudflarestorage.com")
        assert ws._r2_configured() is True


# ── A deposit made without a title names its catalog ──────────────────────────
#
# ws.zenodo() gave the Zenodo metadata an automatic title but built the deposit
# graph with an empty one, so its catalog node had no schema:name and, where
# pyshacl is installed, the publication check refused it: every
# ws.publish(zenodo=True), which passes no title, was refused. The graph, the
# RO-Crate and the metadata now take one title.

LAB_SPEC = CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
AUTO_TITLE = "Example Lab R2032 — BattINFO Battery Dataset"


def _titleless_workspace(root: Path):  # noqa: ANN202
    from battinfo.ws import AuthoringWorkspace

    root.mkdir(parents=True, exist_ok=True)
    (root / "run.bdf.csv").write_text(
        "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n", encoding="utf-8"
    )
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    ws.add("cell", spec=LAB_SPEC.model_copy(), serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="run.bdf.csv")
    ws.save()
    return ws


class _RecordingZenodo:
    """Stands in for ZenodoClient: keeps the uploaded files and the metadata."""

    def __init__(self) -> None:
        self.uploaded: dict[str, str] = {}
        self.metadata: dict = {}
        self.published = False

    def client(self, *args: object, **kwargs: object) -> "_RecordingZenodo":
        return self

    def create_empty_deposit(self) -> dict:
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict) -> dict:
        self.uploaded = {name: Path(path).read_text(encoding="utf-8") for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        self.metadata = metadata
        return {}

    def publish_deposit(self, deposit_id: int) -> dict:
        self.published = True
        return {"doi": "10.5281/zenodo.7"}


@pytest.fixture()
def recording_zenodo(monkeypatch: pytest.MonkeyPatch) -> _RecordingZenodo:
    fake = _RecordingZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


def _catalog(graph: dict) -> dict:
    return next(node for node in graph["@graph"] if "dcat:Catalog" in node["@type"])


def _publisher_errors(graph: dict) -> list[str]:
    from battinfo.validate import validate_publication_report

    report = validate_publication_report(graph, policy="publisher")
    return [issue.message for issue in report.issues if issue.severity == "error"]


class TestDepositTitle:
    def test_zenodo_without_a_title_names_the_catalog_as_the_metadata(
        self, tmp_path: Path, recording_zenodo: _RecordingZenodo
    ) -> None:
        pytest.importorskip("pyshacl")  # the catalog-name rule is a SHACL shape
        ws = _titleless_workspace(tmp_path)
        result = ws.zenodo(publish=True, token="placeholder", creators=CREATORS)

        assert result.published and recording_zenodo.published
        graph = json.loads(recording_zenodo.uploaded["battinfo.json"])
        assert recording_zenodo.metadata["title"] == AUTO_TITLE
        assert _catalog(graph)["schema:name"] == AUTO_TITLE
        assert _catalog(graph)["dcterms:title"] == AUTO_TITLE
        crate = json.loads(recording_zenodo.uploaded["ro-crate-metadata.json"])
        assert next(node for node in crate["@graph"] if node["@id"] == "./")["name"] == AUTO_TITLE
        assert _publisher_errors(graph) == []

        # The empty title the graph used to get is what the check refused.
        untitled = ws._build_zenodo_jsonld(
            zenodo_record_id=7, prereserved_doi="10.5281/zenodo.7",
            record_url="https://zenodo.org/records/7", data_filenames=["run.bdf.csv"],
            creators=CREATORS, license="cc-by-4.0",
        )
        assert "Catalog must carry a schema:name (human title)." in _publisher_errors(untitled)

    def test_publish_to_zenodo_without_a_title_is_not_refused(
        self, tmp_path: Path, recording_zenodo: _RecordingZenodo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("pyshacl")
        # ws.publish() takes no token; give it a placeholder so the test never
        # depends on (or reads) a real token in the developer's environment.
        monkeypatch.setenv("ZENODO_API_TOKEN", "placeholder")
        ws = _titleless_workspace(tmp_path)
        submitted: list[str | None] = []
        monkeypatch.setattr(ws, "submit", lambda **kwargs: submitted.append(kwargs.get("doi")) or [])
        ws.publish(zenodo=True, note="title check", creators=CREATORS)

        assert recording_zenodo.published and submitted == ["10.5281/zenodo.7"]
        graph = json.loads(recording_zenodo.uploaded["battinfo.json"])
        assert _catalog(graph)["schema:name"] == recording_zenodo.metadata["title"] == AUTO_TITLE

    def test_an_explicit_title_reaches_the_graph_and_the_metadata(
        self, tmp_path: Path, recording_zenodo: _RecordingZenodo
    ) -> None:
        ws = _titleless_workspace(tmp_path)
        ws.zenodo(token="placeholder", title="Coin cell cycling, 2026", creators=CREATORS)
        graph = json.loads(recording_zenodo.uploaded["battinfo.json"])
        assert _catalog(graph)["schema:name"] == recording_zenodo.metadata["title"] == "Coin cell cycling, 2026"

    def test_the_preview_without_a_title_shows_the_deposit_title(self, tmp_path: Path) -> None:
        ws = _titleless_workspace(tmp_path)
        graph = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
        metadata = ws._build_zenodo_metadata(
            title=None, description=None, creators=CREATORS, license="cc-by-4.0",
            community=None, extra_keywords=None,
        )
        assert _catalog(graph)["schema:name"] == metadata["title"] == AUTO_TITLE

    def test_a_workspace_without_cell_specs_gets_the_generic_title(
        self, tmp_path: Path, recording_zenodo: _RecordingZenodo
    ) -> None:
        ws = _titleless_workspace(tmp_path)
        for path in (ws._ws.source_root / "cell-spec").glob("*.json"):
            path.unlink()
        graph = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
        assert _catalog(graph)["schema:name"] == "Battery Dataset — BattINFO"

    def test_the_staged_package_names_its_catalog_as_the_metadata(self, tmp_path: Path) -> None:
        """The CLI batch path (build_zenodo_package, then upload_zenodo_package with no title)."""
        staging = _staged_package(tmp_path)
        record = ZenodoCellRecord.from_path(staging / ZENODO_CELL_RECORD_FILENAME)
        metadata = _build_zenodo_metadata(
            record, creators=CREATORS, title=None, description=None, license="cc-by-4.0",
            community=None, extra_keywords=None,
        )
        graph = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
        crate = json.loads((staging / DEFAULT_RO_CRATE_METADATA_FILENAME).read_text(encoding="utf-8"))
        assert metadata["title"] == "Energizer CR2032 — BattINFO Reference Datasets"
        assert _catalog(graph)["schema:name"] == metadata["title"]
        assert next(node for node in crate["@graph"] if node["@id"] == "./")["name"] == metadata["title"]

    @pytest.mark.parametrize("title", [None, "Explicit CLI title"])
    def test_a_title_given_at_upload_reaches_the_staged_files(self, tmp_path: Path, title: str | None) -> None:
        """upload_zenodo_package(title=...) renames the catalog and the RO-Crate root it uploads."""
        staging = _staged_package(tmp_path)
        client = MagicMock(spec=ZenodoClient)
        client.create_empty_deposit.return_value = {
            "id": 9, "record_id": 9, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.9"}},
        }
        with patch("battinfo.zenodo.ZenodoClient", return_value=client):
            upload_zenodo_package(staging, CREATORS, token="tok", title=title)

        [metadata] = [call.args[1] for call in client.update_metadata.call_args_list]
        expected = title or "Energizer CR2032 — BattINFO Reference Datasets"
        assert metadata["title"] == expected
        graph = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
        crate = json.loads((staging / DEFAULT_RO_CRATE_METADATA_FILENAME).read_text(encoding="utf-8"))
        assert _catalog(graph)["schema:name"] == _catalog(graph)["dcterms:title"] == expected
        assert next(node for node in crate["@graph"] if node["@id"] == "./")["name"] == expected
