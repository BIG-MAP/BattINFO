from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from battinfo._util import _as_path

PathLike = str | Path


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    return os.path.normcase(str(Path(path).resolve()))


def _load_psutil() -> Any:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only when optional dependency missing.
        raise RuntimeError(
            "Notebook recovery requires 'psutil'. Install notebook dependencies into the active environment first."
        ) from exc
    return psutil


def _default_venv_python(workspace_root: Path, venv_path: Path) -> Path:
    candidates = [
        (workspace_root / venv_path / "Scripts" / "python.exe"),
        (workspace_root / venv_path / "bin" / "python"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0 if os.name == "nt" else 1]


def _looks_like_notebook_kernel_process(info: dict[str, Any], venv_python: Path, current_pid: int) -> bool:
    pid = info.get("pid")
    if not isinstance(pid, int) or pid == current_pid:
        return False
    executable = _normalize_path(info.get("exe"))
    if executable != _normalize_path(str(venv_python)):
        return False
    cmdline = [str(item).lower() for item in (info.get("cmdline") or []) if item is not None]
    return any("ipykernel" in item for item in cmdline)


def recover_notebook_runtime(
    *,
    workspace_root: PathLike = ".",
    venv_path: PathLike = ".venv",
    clear_local_runtime: bool = True,
    force_kill: bool = True,
) -> dict[str, Any]:
    psutil = _load_psutil()

    root = _as_path(workspace_root).resolve()
    venv_python = _default_venv_python(root, _as_path(venv_path))
    current_pid = os.getpid()

    kernel_processes: list[Any] = []
    scanned = 0
    for proc in psutil.process_iter(attrs=["pid", "exe", "cmdline"]):
        scanned += 1
        try:
            if _looks_like_notebook_kernel_process(proc.info, venv_python, current_pid):
                kernel_processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    tree_by_pid: dict[int, Any] = {}
    for proc in kernel_processes:
        try:
            tree_by_pid[proc.pid] = proc
            for child in proc.children(recursive=True):
                tree_by_pid[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes = list(tree_by_pid.values())
    terminated_pids: list[int] = []
    killed_pids: list[int] = []

    for proc in reversed(processes):
        try:
            proc.terminate()
            terminated_pids.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    gone, alive = psutil.wait_procs(processes, timeout=2)
    if force_kill:
        for proc in alive:
            try:
                proc.kill()
                killed_pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(alive, timeout=2)

    cleared_runtime_paths: list[str] = []
    local_runtime_root = root / ".jupyter-runtime-test"
    if clear_local_runtime and local_runtime_root.exists():
        if local_runtime_root.is_dir():
            shutil.rmtree(local_runtime_root)
        else:
            local_runtime_root.unlink()
        cleared_runtime_paths.append(str(local_runtime_root))

    return {
        "status": "ok",
        "workspace_root": str(root),
        "venv_python": str(venv_python),
        "scanned_processes": scanned,
        "kernel_process_count": len(kernel_processes),
        "terminated_pid_count": len(terminated_pids),
        "killed_pid_count": len(killed_pids),
        "terminated_pids": terminated_pids,
        "killed_pids": killed_pids,
        "remaining_pid_count": len(alive),
        "remaining_pids": [proc.pid for proc in alive],
        "cleared_runtime_paths": cleared_runtime_paths,
    }
