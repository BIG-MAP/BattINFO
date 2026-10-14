"""The "Build a cell from components" how-to is safe to run again.

CI runs the page's Python blocks once (``.tools/quality/run_doc_snippets.py``).
A reader re-runs it, so this runs every block twice in one folder: the second
run must land on the records the first one saved, with the same files and the
same component links on the cell spec, not add a copy of each part.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PAGE = "docs/howto/build-a-cell-from-components.md"
LINKS = (
    "positive_electrode_spec_id",
    "negative_electrode_spec_id",
    "electrolyte_spec_id",
    "separator_spec_id",
    "housing_spec_id",
)


def _page_script() -> str:
    spec = importlib.util.spec_from_file_location(
        "run_doc_snippets", ROOT / ".tools" / "quality" / "run_doc_snippets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_doc_snippets", module)  # its dataclasses look their module up there
    spec.loader.exec_module(module)
    blocks = [
        block
        for block in module._extract(PAGE)
        if block.lang == "python" and not block.skip_marked and "..." not in block.text
    ]
    assert len(blocks) >= 6, "the page's Python blocks were not found"
    return "\n\n".join(block.text for block in blocks)


def _run(script: str) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(script, PAGE, "exec"), {"__name__": "__howto__"})  # noqa: S102


def _library(root: Path) -> dict[str, list[str]]:
    """Folder -> the record files in it."""
    out: dict[str, list[str]] = {}
    for path in sorted((root / "my-library").rglob("*.json")):
        out.setdefault(path.parent.relative_to(root).as_posix(), []).append(path.name)
    return out


def _cell_spec_links(root: Path) -> list[dict[str, str]]:
    links = []
    for path in sorted((root / "my-library").rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "cell_spec" in record:  # the links sit beside the cell_spec body
            links.append({key: record.get(key) for key in LINKS})
    return links


def test_running_the_page_twice_in_one_folder_changes_no_file_or_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _page_script()
    monkeypatch.chdir(tmp_path)

    _run(script)
    files, links = _library(tmp_path), _cell_spec_links(tmp_path)
    assert len(links) == 1 and all(links[0].values()), links

    _run(script)
    assert _library(tmp_path) == files
    assert _cell_spec_links(tmp_path) == links
