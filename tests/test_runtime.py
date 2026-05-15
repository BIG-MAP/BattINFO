from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.runtime import recover_notebook_runtime


class _FakeProcess:
    def __init__(self, pid: int, exe: str, cmdline: list[str], children: list["_FakeProcess"] | None = None) -> None:
        self.pid = pid
        self.info = {"pid": pid, "exe": exe, "cmdline": cmdline}
        self._children = list(children or [])
        self.terminated = False
        self.killed = False

    def children(self, recursive: bool = False) -> list["_FakeProcess"]:
        if not recursive:
            return list(self._children)
        out: list[_FakeProcess] = []
        stack = list(self._children)
        while stack:
            item = stack.pop()
            out.append(item)
            stack.extend(item._children)
        return out

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class _FakePsutil:
    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    def __init__(self, processes: list[_FakeProcess], alive_after_terminate: list[_FakeProcess]) -> None:
        self._processes = processes
        self._alive_after_terminate = alive_after_terminate

    def process_iter(self, attrs: list[str]) -> list[_FakeProcess]:
        return list(self._processes)

    def wait_procs(self, processes: list[_FakeProcess], timeout: float) -> tuple[list[_FakeProcess], list[_FakeProcess]]:
        alive_ids = {proc.pid for proc in self._alive_after_terminate}
        alive = [proc for proc in processes if proc.pid in alive_ids and not proc.killed]
        gone = [proc for proc in processes if proc.pid not in alive_ids or proc.killed]
        return gone, alive


def test_recover_notebook_runtime_stops_repo_local_ipykernel_process_tree(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path
    venv_python = workspace_root / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    runtime_dir = workspace_root / ".jupyter-runtime-test"
    runtime_dir.mkdir()
    (runtime_dir / "kernel.json").write_text("{}", encoding="utf-8")

    child = _FakeProcess(102, str(venv_python), ["python", "worker.py"])
    kernel = _FakeProcess(101, str(venv_python), ["python", "-m", "ipykernel_launcher", "-f", "kernel-101.json"], [child])
    unrelated = _FakeProcess(201, str(venv_python), ["python", "-m", "pytest"])
    foreign = _FakeProcess(301, str(tmp_path / "other" / "python.exe"), ["python", "-m", "ipykernel_launcher"])

    fake_psutil = _FakePsutil([kernel, unrelated, foreign], alive_after_terminate=[kernel])
    monkeypatch.setattr("battinfo.runtime._load_psutil", lambda: fake_psutil)
    monkeypatch.setattr("battinfo.runtime.os.getpid", lambda: 99999)

    payload = recover_notebook_runtime(workspace_root=workspace_root)

    assert payload["kernel_process_count"] == 1
    assert payload["terminated_pid_count"] == 2
    assert payload["killed_pid_count"] == 1
    assert kernel.terminated is True
    assert child.terminated is True
    assert kernel.killed is True
    assert unrelated.terminated is False
    assert runtime_dir.exists() is False


