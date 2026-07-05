"""Interop sharp edges (beta-hardening plan 2.5).

- ``import_discovery_eln`` accepts a real ``.eln`` ZIP archive, not just an unpacked crate.
- Importer JSON errors carry the offending file's path (shared ``load_json_source``).
- The aurora importer surfaces a present-but-unparseable numeric as a warning on the
  imported TestSpec instead of silently ignoring the field.
- A batch import that produces zero records from a real source says so in warnings.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import import_discovery_eln
from battinfo.interop._common import load_json_source
from battinfo.interop.battery_data_commons import batch_import_bdc
from battinfo.interop.protocols import import_aurora_unicycler

FX = ROOT / "tests" / "fixtures" / "interop" / "discovery"
ELN_JSON = FX / "ro-crate-metadata.sample.json"


def test_import_discovery_eln_reads_a_real_zip_archive(tmp_path: Path) -> None:
    archive = tmp_path / "export.eln"
    with zipfile.ZipFile(archive, "w") as zf:
        # Real .eln exports nest the crate in a top-level directory.
        zf.write(ELN_JSON, "my-export/ro-crate-metadata.json")
    package = import_discovery_eln(archive, validate=False)
    reference = import_discovery_eln(ELN_JSON, validate=False)
    assert len(package.cells) == len(reference.cells) > 0


def test_import_discovery_eln_zip_without_crate_names_the_problem(tmp_path: Path) -> None:
    archive = tmp_path / "not-a-crate.eln"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(ValueError, match="ro-crate-metadata.json"):
        import_discovery_eln(archive)


def test_load_json_source_errors_carry_the_file_path(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        load_json_source(bad)
    with pytest.raises(ValueError, match="missing.json"):
        load_json_source(tmp_path / "missing.json")


def test_aurora_unparseable_numeric_field_warns_on_the_record() -> None:
    spec = import_aurora_unicycler({
        "method": [
            {"step": "constant_current", "rate_C": "0.5", "until_voltage_V": "4..2"},
        ],
    })
    assert any("until_voltage_V" in w for w in spec.comment), spec.comment
    # The parseable setpoint still imports.
    assert spec.method and spec.method[0].setpoints["c_rate"].value == 0.5


def test_bdc_batch_zero_records_is_said_out_loud(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not a record", encoding="utf-8")
    package = batch_import_bdc(tmp_path)
    assert any("0 records imported" in w for w in package.warnings), package.warnings
