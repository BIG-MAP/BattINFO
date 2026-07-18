"""Execute the code snippets in the newcomer-path docs so they cannot rot.

Extracts fenced code blocks from QUICKSTART.md, docs/python-api.md, and
docs/pages/getting-started.rst, then executes the safe ones:

- ``python`` blocks run cumulatively per file (each block re-runs the file's
  previous blocks first, in a fresh temp directory, so later blocks may use
  names defined earlier — mirroring how a reader follows the page top to
  bottom). Blocks containing a literal ``...`` placeholder are skipped.
- ``bash``/``powershell``/``console`` blocks: only read-only ``battinfo``
  commands (validate / query / properties / --help) are executed, from the
  repo root. Everything else (pip install, save, publish, git) is skipped.

A block can opt out explicitly with a marker on the line above the fence:
``<!-- doc-snippet: skip -->`` in Markdown, ``.. doc-snippet: skip`` in RST.

Exit code is non-zero if any executed snippet fails. Every skipped block is
reported with its reason so silent rot is impossible.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SNIPPET_FILES = (
    "QUICKSTART.md",
    "docs/python-api.md",
    "docs/pages/getting-started.rst",
    "docs/pages/troubleshooting.md",
    "docs/howto/bulk-ingest.md",
    "docs/howto/build-a-cell-from-components.md",
    "docs/howto/find-existing-records.md",
    "docs/howto/fix-validation-errors.md",
    "docs/howto/label-your-cells.md",
    "docs/howto/register-equipment.md",
    "docs/howto/register-materials.md",
    "docs/test-specs.md",
)

SKIP_MARKERS = ("<!-- doc-snippet: skip -->", ".. doc-snippet: skip")
CLI_LANGS = {"bash", "powershell", "shell", "console", "sh"}
# Read-only battinfo subcommands that are safe to execute against the repo.
CLI_ALLOWED = {"validate", "query", "properties", "--help"}
SNIPPET_TIMEOUT_S = 300


@dataclass
class Block:
    path: str
    line: int
    lang: str
    text: str
    skip_marked: bool

    @property
    def label(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class Report:
    executed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _extract_markdown(path: Path, rel: str) -> list[Block]:
    blocks: list[Block] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^```(\w+)\s*$", lines[i])
        if not match:
            i += 1
            continue
        lang = match.group(1).lower()
        start = i + 1
        j = start
        while j < len(lines) and not lines[j].startswith("```"):
            j += 1
        prev = next((ln.strip() for ln in reversed(lines[:i]) if ln.strip()), "")
        blocks.append(
            Block(
                path=rel,
                line=start + 1,
                lang=lang,
                text="\n".join(lines[start:j]),
                skip_marked=prev in SKIP_MARKERS,
            )
        )
        i = j + 1
    return blocks


def _extract_rst(path: Path, rel: str) -> list[Block]:
    blocks: list[Block] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)\.\. code-block::\s*(\w+)\s*$", lines[i])
        if not match:
            i += 1
            continue
        indent, lang = match.group(1), match.group(2).lower()
        j = i + 1
        body: list[str] = []
        while j < len(lines):
            line = lines[j]
            if line.strip() and not line.startswith(indent + " "):
                break
            body.append(line)
            j += 1
        while body and not body[0].strip():
            body.pop(0)
        common = min((len(ln) - len(ln.lstrip()) for ln in body if ln.strip()), default=0)
        prev = next((ln.strip() for ln in reversed(lines[:i]) if ln.strip()), "")
        blocks.append(
            Block(
                path=rel,
                line=i + 2,
                lang=lang,
                text="\n".join(ln[common:] if ln.strip() else "" for ln in body),
                skip_marked=prev in SKIP_MARKERS,
            )
        )
        i = j
    return blocks


def _extract(rel: str) -> list[Block]:
    path = REPO_ROOT / rel
    if rel.endswith(".rst"):
        return _extract_rst(path, rel)
    return _extract_markdown(path, rel)


def _run_python_blocks(blocks: list[Block], report: Report) -> None:
    accepted: list[Block] = []
    for block in blocks:
        if block.skip_marked:
            report.skipped.append((block.label, "explicit doc-snippet: skip marker"))
            continue
        if "..." in block.text:
            report.skipped.append((block.label, "contains ... placeholder (not executable)"))
            continue
        chain = [*accepted, block]
        with tempfile.TemporaryDirectory(prefix="doc-snippet-") as tmp:
            # Snippets may read the repo's packaged examples by relative path.
            shutil.copytree(REPO_ROOT / "examples", Path(tmp) / "examples")
            script = Path(tmp) / "snippet.py"
            script.write_text(
                "\n\n".join(f"# --- {b.label}\n{b.text}" for b in chain) + "\n",
                encoding="utf-8",
            )
            proc = subprocess.run(  # noqa: S603
                [sys.executable, str(script)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=SNIPPET_TIMEOUT_S,
            )
        if proc.returncode == 0:
            accepted.append(block)
            report.executed.append(f"{block.label} (python)")
        else:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-15:]
            report.failed.append((block.label, "\n".join(tail)))


def _cli_commands(text: str) -> list[str]:
    joined: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        pending = ""
        if line.endswith("`") or line.endswith("\\"):
            pending = line[:-1].rstrip() + " "
            continue
        if line:
            joined.append(line)
    if pending:
        joined.append(pending.rstrip())
    commands: list[str] = []
    for line in joined:
        line = re.sub(r"^[.\\/\w-]*[\\/]battinfo(\.exe)?\s", "battinfo ", line)
        line = re.sub(r"^\$\s+", "", line)
        if not line.startswith("#"):
            commands.append(line)
    return commands


def _run_cli_blocks(blocks: list[Block], report: Report) -> None:
    battinfo = shutil.which("battinfo")
    for block in blocks:
        if block.skip_marked:
            report.skipped.append((block.label, "explicit doc-snippet: skip marker"))
            continue
        for command in _cli_commands(block.text):
            if not command.startswith("battinfo "):
                report.skipped.append((f"{block.label} `{command}`", "not a battinfo command"))
                continue
            subcommand = command.split()[1]
            if subcommand not in CLI_ALLOWED:
                report.skipped.append((f"{block.label} `{command}`", f"'{subcommand}' is not read-only"))
                continue
            if battinfo is None:
                report.failed.append((block.label, "battinfo CLI not found on PATH"))
                continue
            proc = subprocess.run(  # noqa: S603
                [battinfo, *shlex.split(command)[1:]],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=SNIPPET_TIMEOUT_S,
            )
            if proc.returncode == 0:
                report.executed.append(f"{block.label} `{command}`")
            else:
                tail = (proc.stderr or proc.stdout).strip().splitlines()[-15:]
                report.failed.append((f"{block.label} `{command}`", "\n".join(tail)))


def main() -> int:
    report = Report()
    for rel in SNIPPET_FILES:
        blocks = _extract(rel)
        _run_python_blocks([b for b in blocks if b.lang == "python"], report)
        _run_cli_blocks([b for b in blocks if b.lang in CLI_LANGS], report)

    print(f"executed: {len(report.executed)}")
    for label in report.executed:
        print(f"  PASS {label}")
    print(f"skipped: {len(report.skipped)}")
    for label, reason in report.skipped:
        print(f"  SKIP {label} - {reason}")
    if report.failed:
        print(f"failed: {len(report.failed)}", file=sys.stderr)
        for label, detail in report.failed:
            print(f"  FAIL {label}\n{detail}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
