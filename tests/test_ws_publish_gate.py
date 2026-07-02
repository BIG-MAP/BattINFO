"""R-7: publishing to Zenodo is irreversible, so the workspace must fail closed BEFORE minting a
DOI when (a) a file-scheme distribution's local data file is missing (the deposit would be
incomplete) or (b) the record has validation errors. The check must pass for a clean record."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.ws import AuthoringWorkspace


def _issue(severity: str, message: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(severity=severity, message=message)


def _fake_report(*issues: types.SimpleNamespace) -> types.SimpleNamespace:
    return types.SimpleNamespace(issues=list(issues))


def _patch_validator(monkeypatch: pytest.MonkeyPatch, report: types.SimpleNamespace) -> None:
    import battinfo.validate as v

    monkeypatch.setattr(v, "validate_publication_report", lambda *a, **k: report)


def test_publish_refused_when_data_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_validator(monkeypatch, _fake_report())  # no validation errors
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws._missing_data_files = ["/data/run_042.csv"]
    with pytest.raises(RuntimeError, match="missing"):
        ws._assert_publishable({"@graph": []})


def test_publish_refused_when_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_validator(monkeypatch, _fake_report(_issue("error", "missing dataset license")))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws._missing_data_files = []
    with pytest.raises(RuntimeError, match="validation error"):
        ws._assert_publishable({"@graph": []})


def test_publish_allowed_for_clean_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # warnings alone must not block publishing — only errors do.
    _patch_validator(monkeypatch, _fake_report(_issue("warning", "consider adding keywords")))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws._missing_data_files = []
    ws._assert_publishable({"@graph": []})  # must not raise


def test_assert_publishable_fails_closed_if_validator_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import battinfo.validate as v

    def _boom(*a: object, **k: object) -> None:
        raise ImportError("validator broke")

    monkeypatch.setattr(v, "validate_publication_report", _boom)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws._missing_data_files = []
    with pytest.raises(RuntimeError, match="Could not validate"):
        ws._assert_publishable({"@graph": []})
