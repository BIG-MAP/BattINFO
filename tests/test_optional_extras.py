"""Optional-dependency extras: teaching errors name the exact install fix.

pandas/pyarrow/openpyxl ship in the [tabular] extra and rocrate in the [publish]
extra; feature code imports them lazily through battinfo._util.require_extra so
the error message cannot drift between call sites.

Absence is simulated by poisoning sys.modules with None: both the import
statement and importlib.import_module raise ImportError when a module's
sys.modules entry is None, and monkeypatch restores the real entries afterwards.
"""
from __future__ import annotations

import sys
import types

import pytest

from battinfo._util import require_extra


def _poison(monkeypatch: pytest.MonkeyPatch, *roots: str) -> None:
    """Make ``import <root>`` (and any submodule) fail even if already imported."""
    for name in list(sys.modules):
        for root in roots:
            if name == root or name.startswith(root + "."):
                monkeypatch.delitem(sys.modules, name, raising=False)
    for root in roots:
        monkeypatch.setitem(sys.modules, root, None)  # type: ignore[arg-type]


def test_require_extra_returns_module_when_available() -> None:
    module = require_extra("json", "tabular", "feature")
    assert isinstance(module, types.ModuleType)
    assert module.__name__ == "json"


def test_require_extra_pandas_names_tabular_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _poison(monkeypatch, "pandas")
    with pytest.raises(ImportError) as excinfo:
        require_extra("pandas", "tabular", "This feature reads tabular data files")
    message = str(excinfo.value)
    assert message == (
        "This feature reads tabular data files and needs the [tabular] extra: "
        "pip install battinfo[tabular]"
    )
    assert excinfo.value.__cause__ is not None  # original ImportError is chained


def test_require_extra_rocrate_names_publish_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _poison(monkeypatch, "rocrate")
    with pytest.raises(ImportError, match=r"pip install battinfo\[publish\]"):
        require_extra("rocrate.rocrate", "publish", "validate_rocrate() checks RO-Crate metadata")


def test_from_battdat_reader_names_tabular_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    from battinfo.interop import battdat

    _poison(monkeypatch, "pandas")
    with pytest.raises(ImportError, match=r"pip install battinfo\[tabular\]"):
        battdat._read_df("does-not-matter.csv", [])


def test_import_discovery_xlsx_names_tabular_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    from battinfo.interop.discovery import import_discovery_xlsx

    _poison(monkeypatch, "openpyxl")
    with pytest.raises(ImportError, match=r"pip install battinfo\[tabular\]"):
        import_discovery_xlsx("does-not-matter.xlsx")
