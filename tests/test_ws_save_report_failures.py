"""ws.save() reports records the index rejected (evaluation finding E-09).

With a reference that does not resolve, ws.save() printed every record as
"[created]" and ended with "Next: ... ws.publish() to publish"; the rejection
was only in summary["index"]["failures"]. Such a record is now listed as
failed with its error, and the closing line counts the failures and says what
to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import battinfo

REGISTRY_CELL = "https://w3id.org/battinfo/cell/epb7-1s8v-p342-469z"
REMOTE_PROTOCOL = "https://w3id.org/battinfo/spec/v4sk-j357-5jda-jreq"
SPEC = dict(manufacturer="Example Lab", model="R2032 half cell", format="coin", chemistry="li-ion")


def test_a_test_on_an_unresolved_cell_is_reported_failed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("test", type="cycling", cell=REGISTRY_CELL, name="Relinked cycling test")
    summary = ws.save()
    out = capsys.readouterr().out

    test_line = next(line for line in out.splitlines() if "Relinked cycling test" in line)
    assert "[failed]" in test_line and "[created]" not in test_line
    assert "Referenced cell not found" in out
    assert "1 record(s) failed validation" in out
    assert "ws.save() again" in out
    assert "Next: ws.list(verbose=True)" not in out

    item = summary["tests"][0]
    assert item["failed"] is True
    assert "Referenced cell not found" in item["error"]
    assert summary["index"]["failed"] == 1


def test_a_test_on_a_protocol_iri_outside_the_workspace_is_reported_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", spec=REMOTE_PROTOCOL)
    summary = ws.save()
    out = capsys.readouterr().out
    assert "Referenced test protocol not found" in out
    assert [item.get("failed", False) for item in summary["tests"]] == [True]
    # The records that did validate keep their own status.
    assert all(not item.get("failed") for item in summary["cell_instances"] + summary["cell_specs"])
    assert "[created]" in next(line for line in out.splitlines() if "C01" in line and "cell " in line)


def test_a_clean_save_still_points_at_the_next_step(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01")
    summary = ws.save()
    out = capsys.readouterr().out
    assert "[failed]" not in out and "failed validation" not in out
    assert "Next: ws.list(verbose=True)" in out
    assert summary["index"]["failed"] == 0
