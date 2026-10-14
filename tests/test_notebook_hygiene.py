"""Committed guide notebooks must not leak the executing machine's paths, and must run from a pip install."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = sorted((ROOT / "docs" / "guides").glob("*.ipynb"))

# Windows user-profile paths and unix home dirs — none belong in committed output.
# Outputs are checked as JSON text, where a Windows backslash is written twice.
_LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/home/|/Users/")


def test_no_machine_local_paths_in_committed_outputs() -> None:
    offenders: list[str] = []
    for notebook in GUIDES:
        nb = json.loads(notebook.read_text(encoding="utf-8"))
        for index, cell in enumerate(nb.get("cells", [])):
            blob = json.dumps(cell.get("outputs", []))
            if _LOCAL_PATH.search(blob):
                offenders.append(f"{notebook.name} cell {index}")
    assert not offenders, (
        "machine-local paths leaked into committed notebook outputs — re-run "
        "`uv run python scripts/execute_guides.py`:\n" + "\n".join(offenders)
    )


def _code_cells(notebook: Path) -> list[tuple[int, str]]:
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    return [(index, "".join(cell["source"])) for index, cell in enumerate(nb["cells"]) if cell["cell_type"] == "code"]


def _string_literals(source: str) -> list[str]:
    # IPython magics and shell escapes are not Python.
    python = "\n".join("" if line.lstrip().startswith(("%", "!")) else line for line in source.splitlines())
    return [
        node.value
        for node in ast.walk(ast.parse(python))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_tutorials_open_no_file_that_only_a_checkout_has() -> None:
    """A path next to the notebook, or up in the repository, exists only in a checkout."""
    offenders: list[str] = []
    for notebook in GUIDES:
        for index, source in _code_cells(notebook):
            for literal in _string_literals(source):
                if not literal or "\n" in literal or len(literal) > 200:
                    continue
                try:
                    in_checkout = (notebook.parent / literal).is_file()
                except (OSError, ValueError):
                    continue
                if in_checkout:
                    offenders.append(f"{notebook.name} cell {index}: {literal}")
    assert not offenders, (
        "read these from the installed package, with importlib.resources.files('battinfo.data'):\n"
        + "\n".join(offenders)
    )


_PACKAGED_PATH = re.compile(r'files\(\s*"battinfo\.data"\s*\)((?:\s*/\s*"[^"]+")+)')


def test_the_files_the_tutorials_read_from_the_package_are_package_data() -> None:
    """pyproject.toml ships everything under src/battinfo/data in the wheel (data/**/*)."""
    read: set[str] = set()
    for notebook in GUIDES:
        for index, source in _code_cells(notebook):
            for match in _PACKAGED_PATH.finditer(source):
                parts = re.findall(r'"([^"]+)"', match.group(1))
                packaged = ROOT.joinpath("src", "battinfo", "data", *parts)
                assert packaged.is_file(), f"{notebook.name} cell {index} reads {'/'.join(parts)}, not in battinfo/data"
                read.add("/".join(parts))
    # Tutorial 1 reads the flagship record, 4 the property map and 6 a cycler export.
    assert {
        "examples/cell-spec/A123__ANR26650M1-B.json",
        "mappings/domain-battery/property_map.curated.json",
        "samples/neware-sample.csv",
    } <= read, read


def test_the_local_path_check_sees_windows_and_posix_paths() -> None:
    for path in ("C:\\Users\\someone\\data.csv", "C:/Users/someone/data.csv", "/home/someone/x", "/Users/someone/x"):
        assert _LOCAL_PATH.search(json.dumps([{"text": path}])), path
    assert not _LOCAL_PATH.search(json.dumps([{"text": "docs/guides/_scratch/guide-04"}]))
