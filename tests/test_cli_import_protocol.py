"""The one-liner protocol import: `battinfo import-protocol <file>`."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from battinfo.cli import app

UCP_YAML = """global:
  initial_state_type: soc_percentage
  initial_state_value: 100
  initial_temperature: 25.0
steps:
  - Discharge:
      mode: C-rate
      value: 0.5
      ends:
        - Voltage < 2.5
"""


def test_import_protocol_ucp_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "protocol.yaml"
    source.write_text(UCP_YAML, encoding="utf-8")
    out = tmp_path / "record.json"

    result = CliRunner().invoke(app, ["import-protocol", str(source), "--out", str(out)])
    assert result.exit_code == 0, result.output

    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["conditions"]["initial_state_of_charge"] == {"value": 1.0, "unit": "1"}
    step = record["method"][0]
    assert step["mode"] == "cc" and step["direction"] == "discharge"
    artifact = record["artifacts"][0]
    assert artifact["format"] == "ionworks-ucp"
    assert len(artifact["sha256"]) == 64

    # The same file imports to the same IRI - re-runs are no-ops, not duplicates.
    CliRunner().invoke(app, ["import-protocol", str(source), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["test_spec"]["id"] == record["test_spec"]["id"]


def test_import_protocol_sniffs_pybamm_text(tmp_path: Path) -> None:
    source = tmp_path / "experiment.txt"
    source.write_text(
        "Discharge at 0.5C until 2.5V\nCharge at 0.5C until 4.2V\nHold at 4.2V until C/50\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["import-protocol", str(source)])
    assert result.exit_code == 0, result.output
    record = json.loads(result.output[result.output.index("{"):])
    assert len(record["method"]) == 3
    assert record["artifacts"][0]["format"] == "pybamm-experiment"


def test_import_protocol_rejects_unknown_format(tmp_path: Path) -> None:
    source = tmp_path / "protocol.yaml"
    source.write_text(UCP_YAML, encoding="utf-8")
    result = CliRunner().invoke(app, ["import-protocol", str(source), "--format", "nope"])
    assert result.exit_code == 2
