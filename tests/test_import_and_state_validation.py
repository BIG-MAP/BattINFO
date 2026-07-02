"""D-6 / D-8: importer output and persisted state must be validated, not trusted blindly.

D-6 — import_converter_jsonld_record now schema-validates the cell-spec it emits (like every other
interop importer), and validate=False opts out. D-8 — WorkspaceStateStore.open() refuses a state
file written by a newer, incompatible schema version instead of silently loading it."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo.api as api_module
from battinfo.interop.converter import import_converter_jsonld_record
from battinfo.workspace_state import (
    WORKSPACE_STATE_SCHEMA_VERSION,
    _assert_compatible_state_version,
    _state_version_key,
)


def _minimal_converter_source() -> dict:
    return {
        "@type": "CoinCell",
        "schema:manufacturer": {"schema:name": "Acme"},
        "schema:productID": "R2032-TEST",
        "hasCase": {"@type": "R2032"},
    }


# ── D-6: converter import validates its output ────────────────────────────────
def test_converter_import_validates_output_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(api_module, "_validate_canonical_record", lambda doc, **k: calls.append(doc))
    import_converter_jsonld_record(_minimal_converter_source())
    assert len(calls) == 1  # the emitted cell-spec was validated
    assert isinstance(calls[0], dict) and "cell_spec" in calls[0]  # canonical projection, not library


def test_converter_import_propagates_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(doc, **k):  # noqa: ANN001, ANN002
        raise ValueError("Schema validation failed at 'cell_spec': bad")

    monkeypatch.setattr(api_module, "_validate_canonical_record", _boom)
    with pytest.raises(ValueError, match="Schema validation failed"):
        import_converter_jsonld_record(_minimal_converter_source())


def test_converter_import_validate_false_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(doc, **k):  # noqa: ANN001, ANN002
        raise AssertionError("validator must not run when validate=False")

    monkeypatch.setattr(api_module, "_validate_canonical_record", _boom)
    result = import_converter_jsonld_record(_minimal_converter_source(), validate=False)
    assert result.specification is not None  # imported without validating


# ── D-8: workspace state version compatibility ────────────────────────────────
def test_state_version_key_parses_major_minor() -> None:
    assert _state_version_key("0.1.0") == (0, 1)
    assert _state_version_key("2.5") == (2, 5)
    assert _state_version_key("garbage") == (-1, -1)


def test_open_rejects_newer_state_schema() -> None:
    with pytest.raises(ValueError, match="newer than this BattINFO supports"):
        _assert_compatible_state_version({"schema_version": "99.0.0"})


def test_open_accepts_current_and_older_state_schema() -> None:
    _assert_compatible_state_version({"schema_version": WORKSPACE_STATE_SCHEMA_VERSION})  # no raise
    _assert_compatible_state_version({"schema_version": "0.0.1"})  # older, readable
    _assert_compatible_state_version({})  # absent/legacy tolerated
    _assert_compatible_state_version({"schema_version": ""})  # blank tolerated
