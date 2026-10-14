"""Optional-dependency extras: teaching errors name the exact install fix.

pandas/pyarrow/openpyxl ship in the [tabular] extra and rocrate in the [publish]
extra; feature code imports them lazily through battinfo._util.require_extra so
the error message cannot drift between call sites. The BDF converter ships in
the [processing] extra, and its hint is battinfo._util.CONVERTER_INSTALL_HINT.

Absence is simulated by poisoning sys.modules with None: both the import
statement and importlib.import_module raise ImportError when a module's
sys.modules entry is None, and monkeypatch restores the real entries afterwards.

The last tests run the [publish] and [processing] features with the packages
installed. CI also runs them in the job that installs the lowest version of
each dependency pyproject.toml allows, so they check the declared floors of
rocrate, batterydf, matplotlib and plotly.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from battinfo._util import require_extra

if TYPE_CHECKING:
    from battinfo.ws import AuthoringWorkspace


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
        "This feature reads tabular data files and needs the [tabular] extra: pip install battinfo[tabular]"
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


def test_convert_without_converter_names_processing_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import battinfo

    _poison(monkeypatch, "bdf")
    ws = battinfo.workspace(tmp_path, registry_url=None)
    with pytest.raises(ImportError) as excinfo:
        ws.convert()
    message = str(excinfo.value)
    assert message.endswith('Run: pip install "battinfo[processing]"')
    assert "git+" not in message


def _small_workspace(root: Path) -> AuthoringWorkspace:
    import battinfo

    ws = battinfo.workspace(root, registry_url=None)
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032 half cell", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    return ws


def test_validate_rocrate_accepts_the_crate_preview_rocrate_writes(tmp_path: Path) -> None:
    pytest.importorskip("rocrate")
    ws = _small_workspace(tmp_path)
    ws.add("test", type="cycling", cell="C01")
    ws.save()
    crate = ws.preview_rocrate()
    assert ws.validate_rocrate(crate) is True


def test_process_draws_the_dataset_previews(tmp_path: Path) -> None:
    # ws.convert() needs batterydf, and ws.process() draws the static preview
    # with matplotlib and the interactive one with plotly.
    for module in ("bdf", "matplotlib", "plotly"):
        pytest.importorskip(module)
    rows = [f"{60 * i},{3.0 + 0.01 * i:.2f},{1.0 if i < 10 else -1.0}" for i in range(20)]
    (tmp_path / "export.csv").write_text(
        "\n".join(["test_time_second,voltage_volt,current_ampere", *rows]) + "\n", encoding="utf-8"
    )
    ws = _small_workspace(tmp_path)
    (converted,) = ws.convert("*.csv")
    ws.add("test", type="cycling", cell="C01", data=str(converted))
    ws.save()

    written = ws.process()

    assert sorted(path.name for path in written) == ["export.plot.json", "export.png"]
    png = next(path for path in written if path.suffix == ".png")
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    figure = json.loads(next(path for path in written if path.suffix == ".json").read_text(encoding="utf-8"))
    assert figure["data"], "the Plotly figure has no traces"
    (record_path,) = (tmp_path / ".battinfo" / "records" / "dataset").glob("*.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    names = {entry.get("name") for entry in record["dataset"]["distributions"]}
    assert {"export.plot.json", "export.png"} <= names
