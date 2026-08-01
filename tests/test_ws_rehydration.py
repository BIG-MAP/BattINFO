"""Day-2 rehydration: a fresh process must resolve records saved earlier.

Blind-review finding (Prompt C, finding 1): reopening a workspace in a NEW
Python process and calling ``ws.add("test", cell="S1")`` failed with
``Could not resolve cell 'S1' ...`` even though S1's record sat in
``.battinfo/records/cell-instance/``. The serial->record index was
session-memory only and the resolver's "locally" branch never scanned the saved
records. These tests reproduce the day-2 case with a genuinely cold subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from battinfo import workspace
from battinfo.ws import AuthoringWorkspace

_SPEC_JSON = (
    '{"manufacturer":"Duracell","model":"MN2400","format":"cylindrical",'
    '"chemistry":"Zn-MnO2","size_code":"R03","iec_code":"LR03",'
    '"properties":{"nominal_voltage":{"value":1.5,"unit":"V"}}}'
)


def _session_a(root: Path) -> None:
    """Author + save a cell with serial S1 in this process, then let it end."""
    (root / "d.cell-spec.json").write_text(_SPEC_JSON, encoding="utf-8")
    (root / "x.csv").write_text("unix_time_second,voltage\n0,1\n", encoding="utf-8")
    ws = workspace(root=root, registry_url=None)
    spec = ws.load(root / "d.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["S1"])
    ws.save()


def _run_cold(root: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Run *body* in a fresh interpreter with the workspace at *root* (cold state).

    *body* must be column-0 statements (no leading indentation)."""
    code = (
        "from pathlib import Path\n"
        "from battinfo import workspace\n"
        f"root = Path(r{str(root)!r})\n"
        "ws = workspace(root=root, registry_url=None)\n"
        + body + "\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(root)
    )


def test_cell_serial_resolves_in_a_fresh_process(tmp_path: Path) -> None:
    _session_a(tmp_path)
    # Session B: a brand-new interpreter, nothing in memory from session A.
    proc = _run_cold(
        tmp_path,
        'ws.add("test", type="capacity_check", cell="S1", data="x.csv")\n'
        'print("RESOLVED")',
    )
    assert proc.returncode == 0, proc.stderr
    assert "RESOLVED" in proc.stdout
    assert "Could not resolve cell" not in proc.stderr


def test_cell_serial_resolves_with_fresh_workspace_instance(tmp_path: Path) -> None:
    # A second AuthoringWorkspace over the same directory has its own empty
    # index, which is exactly the day-2 condition; rehydration must still work.
    _session_a(tmp_path)
    ws_b = AuthoringWorkspace(root=tmp_path, registry_url=None)
    cell = ws_b._resolve_cell("S1")
    assert getattr(cell, "serial_number", None) == "S1"


def test_error_text_is_truthful_when_serial_absent(tmp_path: Path) -> None:
    # No record for BOGUS exists on disk; the error must name what was actually
    # searched (the saved-records directory), not a false "locally".
    _session_a(tmp_path)
    ws_b = AuthoringWorkspace(root=tmp_path, registry_url=None)
    try:
        ws_b._resolve_cell("BOGUS")
    except ValueError as exc:
        msg = str(exc)
    else:  # pragma: no cover - the resolver must raise
        raise AssertionError("expected ValueError for an unknown serial")
    assert "records saved under" in msg
    assert str(ws_b._ws.source_root) in msg
    # registry_url=None, so the message must not claim the registry was searched.
    assert "registry not configured" in msg


def test_protocol_reference_resolves_in_a_fresh_process(tmp_path: Path) -> None:
    # The protocol path already scans disk (_resolve_test_protocol_ref), but pin it
    # so it never regresses to the session-only defect the cell path had.
    _session_a(tmp_path)
    # Session A': author a protocol via a saved test so a test-protocol record lands.
    ws_a = AuthoringWorkspace(root=tmp_path, registry_url=None)
    from battinfo import TestSpec

    proto = TestSpec(name="500-cycle CCCV", kind="cycling", cycles=500)
    ws_a.add("test", cell="S1", data="x.csv", spec=proto)
    ws_a.save()
    proto_iri = next(
        (ws_a._ws.source_root / "test-protocol").glob("*.json")
    )
    import json

    proto_id = json.loads(proto_iri.read_text(encoding="utf-8"))["test_spec"]["id"]

    # Session B: fresh process references the saved protocol by IRI; the resolver
    # must find its name/kind on disk, not treat it as an unknown external ref.
    proc = _run_cold(
        tmp_path,
        f'ts = ws.add("test", cell="S1", data="x.csv", spec={proto_id!r})\n'
        'print("PROTOCOL_NAME=" + (ts[0].protocol_name or ""))',
    )
    assert proc.returncode == 0, proc.stderr
    assert "PROTOCOL_NAME=500-cycle CCCV" in proc.stdout
