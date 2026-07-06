"""Execute the guide notebooks and scrub machine-local paths from outputs.

Library prints legitimately show absolute paths when YOU run them; committed
outputs must not carry the executing machine's directories. This script
re-executes every guide, then replaces the repository root (path and file://
URI forms) with the neutral marker `<repo>` in all outputs.
tests/test_notebook_hygiene.py fails if a committed output leaks a local path.

Usage:
    uv run python scripts/execute_guides.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = sorted((ROOT / "docs" / "guides").glob("0*.ipynb"))


def scrub(notebook: Path) -> int:
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    root_win = str(ROOT)
    root_fwd = root_win.replace("\\", "/")
    root_uri = Path(ROOT).as_uri()  # file:///C:/...
    hits = 0

    def clean(text: str) -> str:
        nonlocal hits
        for needle, marker in ((root_uri, "file:///<repo>"), (root_win, "<repo>"), (root_fwd, "<repo>")):
            if needle in text:
                hits += text.count(needle)
                text = text.replace(needle, marker)
        return text

    for cell in nb.get("cells", []):
        for out in cell.get("outputs", []):
            if isinstance(out.get("text"), list):
                out["text"] = [clean(line) for line in out["text"]]
            data = out.get("data", {})
            for key, value in list(data.items()):
                if isinstance(value, list):
                    data[key] = [clean(v) if isinstance(v, str) else v for v in value]
                elif isinstance(value, str):
                    data[key] = clean(value)
    notebook.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    return hits


def main() -> int:
    for nb in GUIDES:
        subprocess.run(
            [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
             "--execute", "--inplace", str(nb)],
            check=True,
            cwd=ROOT,
        )
        scrubbed = scrub(nb)
        print(f"{nb.name}: executed, scrubbed {scrubbed} path reference(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
