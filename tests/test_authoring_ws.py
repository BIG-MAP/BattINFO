"""Tests for the AuthoringWorkspace UX surface (battinfo.ws).

These cover the workspace ergonomics added for the PhD-student/lab-engineer
experience: friendly test-kind validation, multi-format convert detection,
the login/credentials flow (with graceful degradation), and the one-call
publish/discovery helpers.  All tests run offline — any registry calls are
monkeypatched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.ws import (  # noqa: E402
    AuthoringWorkspace,
    _normalize_test_kind,
    _test_kind_values,
)


@pytest.fixture(autouse=True)
def _clean_battinfo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate BATTINFO_* env vars so login() tests don't leak identity across tests."""
    for var in ("BATTINFO_API_KEY", "BATTINFO_WORKSPACE_ID", "BATTINFO_PUBLISHER_ID",
                "BATTINFO_REGISTRY_URL", "BATTINFO_ADMIN_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# ── test-kind validation (T1.3) ───────────────────────────────────────────────

def test_normalize_test_kind_canonical() -> None:
    assert _normalize_test_kind("cycling") == "cycling"
    assert _normalize_test_kind("Cycling") == "cycling"
    assert _normalize_test_kind("EIS") == "eis"


def test_normalize_test_kind_separators() -> None:
    assert _normalize_test_kind("rate capability") == "rate_capability"
    assert _normalize_test_kind("rate-capability") == "rate_capability"


def test_normalize_test_kind_aliases() -> None:
    assert _normalize_test_kind("calendar_aging") == "calendar_ageing"   # American
    assert _normalize_test_kind("rate") == "rate_capability"
    assert _normalize_test_kind("cycle") == "cycling"


def test_normalize_test_kind_invalid_lists_values() -> None:
    with pytest.raises(ValueError) as exc:
        _normalize_test_kind("thermal")
    msg = str(exc.value)
    assert "not a valid test kind" in msg
    # Error must enumerate real values from the enum.
    assert "cycling" in msg and "calendar_ageing" in msg


def test_test_kind_values_match_enum() -> None:
    from battinfo.bundle import BatteryTestType
    assert set(_test_kind_values()) == {m.value for m in BatteryTestType}


def test_add_test_with_bad_kind_raises_before_touching_files(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="not a valid test kind"):
        ws.add("test", kind="bogus-kind", datasets="bdf/*.csv")


def test_add_test_without_kind_or_spec_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="requires kind"):
        ws.add("test", kind="", datasets="bdf/*.csv")


# ── credentials + login (T1.1) ────────────────────────────────────────────────

def test_setup_creates_credentials_and_gitignore(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    cred = ws.setup()
    assert cred.exists()
    assert "BATTINFO_API_KEY" in cred.read_text(encoding="utf-8")
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".battinfo/credentials" in gitignore


def test_set_credentials_merges_without_clobbering(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.setup()
    # Pre-seed an unrelated credential the merge must preserve.
    cred = ws._credentials_path()
    cred.write_text(cred.read_text(encoding="utf-8").replace(
        "R2_BUCKET              = battinfo-public",
        "R2_BUCKET              = my-private-bucket",
    ), encoding="utf-8")

    ws._set_credentials({"BATTINFO_API_KEY": "secret-key-123"})
    text = cred.read_text(encoding="utf-8")
    assert "secret-key-123" in text
    assert "my-private-bucket" in text  # untouched


def _fake_urlopen_returning(profile: dict):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(profile).encode("utf-8")

    def _open(req, timeout=0):  # noqa: ARG001
        return _Resp()

    return _open


def test_login_uses_registry_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _fake_urlopen_returning({
            "publisher_id": "alice-lab",
            "workspace_id": "alice-workspace",
            "display_name": "Alice Researcher",
        }),
    )
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    result = ws.login(api_key="key-abc")
    assert result["workspace_id"] == "alice-workspace"
    assert result["publisher_id"] == "alice-lab"
    cred = ws._credentials_path().read_text(encoding="utf-8")
    assert "alice-workspace" in cred and "key-abc" in cred


def test_login_degrades_gracefully_without_me_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    def _boom(req, timeout=0):  # noqa: ARG001
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    result = ws.login(api_key="key-xyz")
    # Falls back to defaults; key is still saved.
    assert result["workspace_id"] == "battinfo-records"
    assert result["publisher_id"] == "battinfo-authoring"
    assert "key-xyz" in ws._credentials_path().read_text(encoding="utf-8")


def test_login_rejects_empty_key(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="api_key is required"):
        ws.login(api_key="")


# ── discovery helpers (T5.2/T5.3) — must not raise ─────────────────────────────

def test_commands_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.commands()
    out = capsys.readouterr().out
    assert "ws.convert()" in out and "ws.publish" in out


def test_quickstart_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.quickstart()
    out = capsys.readouterr().out
    assert "ws.login" in out and "ws.convert()" in out and "ws.publish" in out


def test_bdf_columns_lists_canonical_names(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    cols = ws.bdf_columns()
    assert "voltage_volt" in cols and "current_ampere" in cols


# ── convert() guidance path (T1.2) ─────────────────────────────────────────────

def test_convert_no_files_prints_help(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("bdf")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    result = ws.convert()
    assert result == []
    out = capsys.readouterr().out
    assert "Auto-detected" in out and ".ndax" in out


def test_convert_flags_unsupported_arbin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("bdf")
    (tmp_path / "run1.res").write_text("dummy", encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.convert()
    out = capsys.readouterr().out
    assert "run1.res" in out and "Arbin" in out


# ── convert_csv() (T4.2) ───────────────────────────────────────────────────────

def test_convert_csv_remaps_columns(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    src = tmp_path / "maccor.csv"
    pd.DataFrame({"Cycle": [1, 2], "Voltage(V)": [3.7, 3.6]}).to_csv(src, index=False)

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    out = ws.convert_csv(
        src,
        hints={"Cycle": "cycle_count", "Voltage(V)": "voltage_volt"},
        validate=False,
    )
    assert out.exists()
    written = pd.read_csv(out)
    assert "cycle_count" in written.columns and "voltage_volt" in written.columns


# ── submit() _glob ordering regression (latent NameError) ──────────────────────

def test_submit_does_not_crash_on_cell_type_glob(tmp_path: Path) -> None:
    """Regression: `_glob` was referenced in the cell-spec loop before its
    definition, so ws.submit() raised NameError on the default publish path
    whenever the examples dir existed.  It must now return cleanly."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    # Make the examples dir exist so submit() proceeds past its early return,
    # but leave the per-type subdirs empty so no network call is attempted.
    (ws._records_root / "examples").mkdir(parents=True, exist_ok=True)
    result = ws.submit(
        registry_url="https://registry.example",
        api_key="k",
        workspace_id="w",
        publisher_id="p",
    )
    assert result == []
