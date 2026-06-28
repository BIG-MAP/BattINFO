"""Regression tests for atomic durable writes (hardening plan Phase 3.3 / review R-5).

These pin the contract that an interrupted write never destroys a prior good
record: ``_jsonio.write_json`` is atomic (temp + fsync + ``os.replace``), and
``WorkspaceStateStore._write_workspace`` stages-then-swaps instead of
rmtree-before-write.

The failure modes are injected *after* the code commits to writing (during the
flush or the atomic commit), not before serialization — a test that only makes
``json.dumps`` raise would pass even against the old, non-atomic implementation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Workspace, _jsonio, quantity, workspace_state
from battinfo._jsonio import read_json, write_json
from battinfo.workspace_state import _swap_dir

# ── _jsonio.write_json atomicity ──────────────────────────────────────────────

def test_write_json_roundtrips_and_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "rec.json"
    write_json(path, {"a": 1, "b": "x"})
    assert read_json(path) == {"a": 1, "b": "x"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.json"]


def test_write_json_preserves_prior_record_when_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rec.json"
    write_json(path, {"original": True})

    def boom(*args, **kwargs):
        raise OSError("simulated crash at the atomic commit")

    monkeypatch.setattr(_jsonio.os, "replace", boom)
    with pytest.raises(OSError):
        write_json(path, {"original": False})

    # The prior good record survives a failed write, and the temp is cleaned up.
    assert read_json(path) == {"original": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.json"]


def test_write_json_preserves_prior_record_when_flush_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rec.json"
    write_json(path, {"original": True})

    def boom(_fd):
        raise OSError("simulated interruption during flush")

    monkeypatch.setattr(_jsonio.os, "fsync", boom)
    with pytest.raises(OSError):
        write_json(path, {"original": False})

    assert read_json(path) == {"original": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.json"]


# ── _swap_dir atomic directory replacement ────────────────────────────────────

def test_swap_dir_replaces_contents_with_no_residue(tmp_path: Path) -> None:
    target = tmp_path / "records"
    target.mkdir()
    (target / "old.json").write_text("OLD", encoding="utf-8")
    staging = tmp_path / ".records.staging"
    staging.mkdir()
    (staging / "new.json").write_text("NEW", encoding="utf-8")

    _swap_dir(staging, target)

    assert {p.name for p in target.iterdir()} == {"new.json"}
    assert not staging.exists()
    assert not any(p.name.endswith(".bak") for p in tmp_path.iterdir())


def test_swap_dir_restores_target_when_swap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "records"
    target.mkdir()
    (target / "old.json").write_text("OLD", encoding="utf-8")
    staging = tmp_path / ".records.staging"
    staging.mkdir()
    (staging / "new.json").write_text("NEW", encoding="utf-8")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # the staging -> target move fails mid-swap
            raise OSError("simulated crash mid-swap")
        return real_replace(src, dst)

    monkeypatch.setattr(workspace_state.os, "replace", flaky_replace)
    with pytest.raises(OSError):
        _swap_dir(staging, target)

    # The rollback restores the original target content.
    assert {p.name for p in target.iterdir()} == {"old.json"}
    assert (target / "old.json").read_text(encoding="utf-8") == "OLD"


# ── WorkspaceStateStore._write_workspace stages-then-swaps (no rmtree-first) ───

def _build_workspace(workspace_root: Path, tmp_path: Path) -> Workspace:
    dataset = tmp_path / "inputs" / "cyc.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")
    ws = Workspace(
        workspace_root,
        name="interrupt-demo",
        title="Interrupt Demo",
        description="durable-write regression",
        tenant="t",
        publisher="p",
        version="0.1.0",
    )
    spec = ws.cell_spec(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_voltage": quantity(3.3, "V")},
        source_file="a123-anr26650m1-b.manual.json",
    )
    cell = ws.cell(spec, serial_number="interrupt-001", batch_id="B1", source_type="lab")
    test = ws.test(cell, kind="cycling", protocol="1C", instrument="VSP-300", status="completed")
    ws.dataset(cell, title="Cycle life", description="d", test=test, path=dataset, license="CC-BY-4.0")
    return ws


def test_interrupted_save_preserves_existing_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspace"
    ws = _build_workspace(workspace_root, tmp_path)
    assert ws.save_workspace()["status"] == "ok"

    before = {
        p.relative_to(workspace_root).as_posix(): p.read_text(encoding="utf-8")
        for p in workspace_root.rglob("*.json")
    }
    assert before, "expected the first save to persist record files"

    # Simulate a crash during the second save's directory swap. The old
    # rmtree-before-write would have wiped the record directories here.
    def boom(_staging, _target):
        raise OSError("simulated crash during swap")

    monkeypatch.setattr(workspace_state, "_swap_dir", boom)
    with pytest.raises(OSError):
        ws.save_workspace()

    after = {
        p.relative_to(workspace_root).as_posix(): p.read_text(encoding="utf-8")
        for p in workspace_root.rglob("*.json")
    }
    for rel, content in before.items():
        assert rel in after, f"record {rel} was destroyed by an interrupted save"
        assert after[rel] == content
    # No staging directory leaked onto disk.
    assert not any(".staging-" in p.name for p in workspace_root.rglob("*"))


def test_atomic_write_text_bytes_match_legacy(tmp_path: Path) -> None:
    # atomic_write_text must produce byte-identical output to the previous
    # Path.write_text(text, encoding="utf-8") so there is zero line-ending churn.
    from battinfo._jsonio import atomic_write_text

    text = json.dumps({"a": 1, "nested": {"b": [1, 2, 3]}, "s": "café"}, indent=2, ensure_ascii=False) + "\n"
    atomic_path = tmp_path / "atomic.json"
    legacy_path = tmp_path / "legacy.json"
    atomic_write_text(atomic_path, text)
    legacy_path.write_text(text, encoding="utf-8")  # the previous, non-atomic implementation
    assert atomic_path.read_bytes() == legacy_path.read_bytes()


def test_write_json_cleans_up_when_fdopen_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If os.fdopen fails after mkstemp, the raw fd must be closed and the temp
    # removed — no orphaned .tmp and no leaked fd (else Windows unlink hits WinError 32).
    path = tmp_path / "rec.json"
    write_json(path, {"original": True})

    def boom(*args, **kwargs):
        raise OSError("simulated fdopen failure")

    monkeypatch.setattr(_jsonio.os, "fdopen", boom)
    with pytest.raises(OSError):
        write_json(path, {"original": False})

    assert read_json(path) == {"original": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.json"]
