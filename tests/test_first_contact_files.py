"""The files a new user meets first promise only what the package does.

The README is also the PyPI page, and neither it nor the wheel can change once
uploaded. These checks run the commands and examples those files give, or compare
what they name with what the library emits, so a stale claim fails here.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import record_to_jsonld  # noqa: E402
from battinfo.cli import app  # noqa: E402

runner = CliRunner()

# A backticked EMMO class name for a cell or battery, such as `BatteryCell`.
BATTERY_CLASS = re.compile(r"`([A-Z][A-Za-z]*(?:Battery|Cell))`")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    """(language, body) of every fenced code block in a Markdown text."""
    pattern = re.compile(r"^```(\w*)[ \t]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
    return [(match.group(1).lower(), match.group(2)) for match in pattern.finditer(text)]


def _section(text: str, heading: str) -> str:
    """The Markdown under the ``## `` heading that starts with *heading*, up to the next one."""
    start = text.index(f"\n{heading}")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def _load_tool(rel: str) -> ModuleType:
    name = Path(rel).stem
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is built
    spec.loader.exec_module(module)
    return module


# ── README: Battery Pass, classes and type stacking ──────────────────────────────


def test_readme_promises_no_battery_pass_output() -> None:
    readme = _read("README.md")
    assert "img.shields.io/badge/Battery%20Pass" not in readme, "0.8.0 has no Battery Pass mapping to badge"
    for claim in ("Battery Pass-compatible", "Battery Pass compatible", "Battery Pass JSON-LD"):
        assert claim not in readme, f"the README still claims {claim!r} output"
    acknowledgements = readme.partition("## Acknowledgements")[2]
    assert "thebatterypass.eu" in acknowledgements, "the Battery Pass acknowledgement stays"


def test_readme_mapping_counts_match_the_curated_maps() -> None:
    match = re.search(r"(\d+) curated property→EMMO-IRI mappings and (\d+) unit→EMMO-IRI mappings", _read("README.md"))
    assert match, "the README no longer states the curated mapping counts"
    maps = ROOT / "assets" / "mappings" / "domain-battery"
    counts = tuple(
        len(json.loads((maps / name).read_text(encoding="utf-8"))["mappings"])
        for name in ("property_map.curated.json", "unit_map.curated.json")
    )
    assert (int(match.group(1)), int(match.group(2))) == counts


def test_package_and_citation_keywords_leave_out_battery_pass() -> None:
    """The keywords go into the wheel's metadata and, through CITATION.cff, into the Zenodo record."""
    keywords = {
        "pyproject.toml": tomllib.loads(_read("pyproject.toml"))["project"]["keywords"],
        "CITATION.cff": yaml.safe_load(_read("CITATION.cff"))["keywords"],
    }
    for rel, words in keywords.items():
        assert words, f"{rel} lists no keywords"
        assert not [word for word in words if "battery pass" in word.lower()], f"{rel} still lists Battery Pass"


# What the README says ws.export writes, mapped to the folder each record type is saved in.
_README_EXPORT_WORDS = {
    "cell specs": "cell-spec",
    "cells": "cell-instance",
    "test specs": "test-protocol",
    "tests": "test",
    "datasets": "dataset",
}


@pytest.mark.filterwarnings("ignore:semantic.value_text_only")
def test_readme_names_the_record_types_ws_export_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from battinfo.entities import ENTITY_KINDS, kind_for_doc

    records = tmp_path / ".battinfo" / "records"
    for path in sorted((ROOT / "examples").rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = kind_for_doc(record)
        if kind is None or (records / kind.subdir).exists():
            continue
        (records / kind.subdir).mkdir(parents=True)
        (records / kind.subdir / path.name).write_text(json.dumps(record), encoding="utf-8")
    assert len(list(records.iterdir())) == len(ENTITY_KINDS), "save one record of every kind"

    written = battinfo.workspace(str(tmp_path)).export(output_dir=tmp_path / "rdf")
    exported = {path.parent.name for path in written}
    assert "WARNING" not in capsys.readouterr().out

    line = next(ln for ln in _read("README.md").splitlines() if "(`ws.export`)" in ln)
    claim = re.search(r"for a workspace's saved (.+?) \(`ws\.export`\)", line)
    assert claim, f"say which records ws.export writes: {line}"
    words = re.split(r", | and ", claim.group(1))
    assert {_README_EXPORT_WORDS.get(word, word) for word in words} == exported, (
        f"the README names {words}; ws.export writes the folders {sorted(exported)}"
    )


@pytest.mark.parametrize(
    "rel",
    ["README.md", "QUICKSTART.md", "docs/how-battinfo-is-built.md", "docs/pages/glossary.md"],
)
def test_battery_classes_named_in_the_docs_exist(rel: str) -> None:
    context = json.loads(_read("src/battinfo/data/context/records.context.v1.json"))["@context"]
    named = set(BATTERY_CLASS.findall(_read(rel)))
    assert named, f"{rel} names no battery class; drop it from this check"
    missing = sorted(name for name in named if name not in context)
    assert not missing, f"{rel} names classes the records context does not define: {missing}"


@pytest.mark.filterwarnings("ignore:semantic.value_text_only")
def test_readme_type_stacking_example_is_what_the_emitter_writes() -> None:
    """The README's cylindrical LFP example is the A123 flagship, whose negative basis is unknown."""
    record = json.loads(_read("examples/cell-spec/A123__ANR26650M1-B.json"))
    stacked = set(record_to_jsonld(record, "cell-spec")["isDescriptionFor"]["@type"])
    line = next(ln for ln in _read("README.md").splitlines() if "`@type` stacking" in ln)
    named = set(BATTERY_CLASS.findall(line))
    assert stacked <= named, f"the README's stacking example leaves out {sorted(stacked - named)}"
    extra = named - stacked
    assert extra <= {"LithiumIonGraphiteBattery"}, f"the emitter does not stack {sorted(extra)} on this cell"
    if extra:
        assert "negative_electrode_basis" in line, "say that the graphite class comes from the negative electrode"


# ── QUICKSTART step 4 ─────────────────────────────────────────────────────────


def test_quickstart_step_4_runs_as_written_in_any_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    quickstart = _read("QUICKSTART.md")
    step1 = next(body for lang, body in _fenced_blocks(_section(quickstart, "## 1. ")) if lang == "python")
    step4 = _fenced_blocks(_section(quickstart, "## 4. "))
    shell_blocks = [(lang, body) for lang, body in step4 if lang not in {"json", "python", "text"}]
    assert len(shell_blocks) == 1, shell_blocks
    lang, body = shell_blocks[0]
    assert lang in {"bash", "sh", "shell", "console"}, f"step 4 is a {lang} block"
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert len(lines) == 1, f"step 4 should be one command on one line, with no line continuation: {lines}"
    command = lines[0]
    assert not re.search(r"[<>`\\]", command), f"step 4 has shell-specific syntax or a placeholder: {command}"
    argv = shlex.split(command)
    assert argv[0] == "battinfo", "with the virtual environment active, battinfo is on the PATH in every shell"

    monkeypatch.chdir(tmp_path)
    namespace: dict = {"__name__": "quickstart_step_1"}
    exec(compile(step1, "QUICKSTART.md step 1", "exec"), namespace)
    printed_iri = re.search(r"^# (https://w3id\.org/battinfo/id/1001/spec/\S+)$", step1, re.MULTILINE)
    assert printed_iri, "step 1 shows the IRI it prints"
    assert namespace["result"].canonical_iri == printed_iri.group(1), "the IRI step 1 shows is the one it mints"

    result = runner.invoke(app, argv[1:])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    expected = json.loads(next(body for lang, body in step4 if lang == "json"))
    assert payload["ok"] is expected["ok"] is True
    assert payload["error_count"] == expected["error_count"] == 0
    assert payload["mode"] == expected["mode"]
    assert Path(payload["source_root"]).as_posix() == expected["source_root"]


# ── Issue templates ───────────────────────────────────────────────────────────


def test_issue_chooser_sends_questions_to_a_template() -> None:
    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    config = yaml.safe_load((folder / "config.yml").read_text(encoding="utf-8"))
    urls = [link["url"] for link in config.get("contact_links") or []]
    # Discussions are turned off for BIG-MAP/BattINFO, so the link would 404.
    # If they are turned on again, this check can go.
    assert not any(url.rstrip("/").endswith("/discussions") for url in urls), urls
    if config.get("blank_issues_enabled") is False:
        labels = []
        for template in folder.glob("*.md"):
            front_matter = template.read_text(encoding="utf-8").split("---")[1]
            labels.append(str(yaml.safe_load(front_matter).get("labels", "")))
        assert any("question" in label for label in labels), "with blank issues off, a template must take questions"


def test_issue_templates_ask_for_commands_that_work(capsys: pytest.CaptureFixture[str]) -> None:
    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    for template in sorted(folder.glob("*.md")):
        text = template.read_text(encoding="utf-8")
        for argv in re.findall(r"`battinfo ([^`]+)`", text):
            result = runner.invoke(app, shlex.split(argv))
            assert result.exit_code == 0, f"{template.name} asks for `battinfo {argv}`, which fails: {result.output}"
        for code in re.findall(r'python -c "([^"]+)"', text):
            capsys.readouterr()
            exec(code, {})
            assert capsys.readouterr().out.strip() == battinfo.__version__, f"{template.name}: {code}"
    bug_report = (folder / "bug_report.md").read_text(encoding="utf-8")
    assert 'python -c "import battinfo; print(battinfo.__version__)"' in bug_report


# ── battinfo dataset and its contribution template ────────────────────────────


def test_dataset_commands_say_they_are_experimental() -> None:
    group = runner.invoke(app, ["dataset", "--help"])
    assert group.exit_code == 0, group.output
    assert "Experimental" in group.stdout and "ws.zenodo()" in group.stdout, group.stdout
    publish = runner.invoke(app, ["dataset", "publish", "--help"])
    assert publish.exit_code == 0, publish.output
    assert "Experimental" in publish.stdout and "ws.zenodo()" in publish.stdout, publish.stdout


def test_contribution_template_gives_only_commands_that_exist() -> None:
    readme = _read("src/battinfo/data/templates/contribution/README.md")
    commands = [
        line.strip()
        for _lang, body in _fenced_blocks(readme)
        for line in body.splitlines()
        if line.strip().startswith("battinfo ")
    ]
    assert commands
    for command in commands:
        # --help is eager, so the command is not run; an option that does not exist still fails.
        result = runner.invoke(app, [*shlex.split(command)[1:], "--help"])
        assert result.exit_code == 0, f"{command!r} fails: {result.output}"
    assert "dist/" not in readme, "battinfo dataset process writes no dist/ folder into the contribution"
    assert "Experimental" in readme


# ── Generated layer ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rel",
    [
        "README.md",
        "CONTRIBUTING.md",
        "docs/how-battinfo-is-built.md",
        "docs/python-api.md",
        "docs/workspace-authoring.md",
        "docs/pages/api-reference.rst",
    ],
)
def test_docs_say_the_schema_is_the_contract_and_the_models_are_hand_written(rel: str) -> None:
    """A page that calls bundle_generated.py generated, without more, invites a regeneration that loses hand edits."""
    for paragraph in re.split(r"\n\s*\n", _read(rel)):
        flat = " ".join(paragraph.split())
        assert not re.search(r"(single|canonical) source of truth", flat, re.IGNORECASE), (
            f"{rel}: the JSON Schema is the save-time contract and the models are the authoring surface: {flat[:200]}"
        )
        assert not re.search(r"pydantic models are generated", flat, re.IGNORECASE), f"{rel}: {flat[:200]}"
        if re.search(r"\bgenerated\b", flat.replace("bundle_generated", "")) and "bundle_generated" in flat:
            assert "by hand" in flat, f"{rel} says bundle_generated.py is generated but not that it is edited by hand"


def test_makefile_leaves_bundle_generated_alone() -> None:
    assert "bundle_generated.py" not in _read("Makefile"), (
        "bundle_generated.py has been edited by hand since it was generated, and the locked linkml "
        "has no --pydantic-version option; regenerating or retiring it waits for 0.9"
    )


# ── The battinfo.ws module docstring ──────────────────────────────────────────


def test_ws_module_docstring_example_runs_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snippets = _load_tool(".tools/quality/run_doc_snippets.py")
    assert "src/battinfo/ws.py" in snippets.SNIPPET_FILES, "the doc-snippet job runs the module docstring"
    blocks = [block for block in snippets._extract("src/battinfo/ws.py") if block.lang == "python"]
    assert blocks, "the battinfo.ws module docstring has no example"
    monkeypatch.chdir(tmp_path)
    namespace: dict = {"__name__": "ws_docstring"}
    for block in blocks:
        # Sockets are off in the test suite, so this also proves the example needs no network.
        exec(compile(block.text, block.label, "exec"), namespace)
    saved = sorted(path.parent.name for path in tmp_path.glob("**/.battinfo/records/*/*.json"))
    assert {"cell-spec", "cell-instance", "test-protocol", "test"} <= set(saved), saved


# ── The docs home page ────────────────────────────────────────────────────────


def _home_page_includes() -> list[tuple[str, str, set[str]]]:
    """(tab label, path from the repository root, option names) of each literalinclude on docs/index.rst."""
    lines = _read("docs/index.rst").splitlines()
    includes = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)\.\. literalinclude::\s*(\S+)\s*$", line)
        if not match:
            continue
        options = set()
        for follow in lines[index + 1 :]:
            option = re.match(r"^(\s+):([\w-]+):", follow)
            if not option or len(option.group(1)) <= len(match.group(1)):
                break
            options.add(option.group(2))
        tabs = [
            found.group(1).strip() for prev in lines[:index] if (found := re.match(r"^\s*\.\. tab-item::(.*)$", prev))
        ]
        path = (ROOT / "docs" / match.group(2)).resolve().relative_to(ROOT).as_posix()
        includes.append((tabs[-1] if tabs else "", path, options))
    return includes


def test_docs_home_page_shows_the_flagship_record_and_its_generated_jsonld() -> None:
    """Both tabs include files, so neither can drift from the record or from what the library emits."""
    gallery = _load_tool("scripts/gen_web_jsonld.py")
    flagship = next(item for item in gallery.GALLERY if item["slug"] == "cell-spec")
    # tests/test_web_generated.py fails when this file drifts from record_to_jsonld.
    jsonld = (gallery.PUBLIC_DIR / "cell-spec.jsonld").relative_to(ROOT).as_posix()

    includes = _home_page_includes()

    assert [path for _, path, _ in includes] == [flagship["file"], jsonld]
    for label, path, options in includes:
        assert (ROOT / path).is_file(), path
        assert "flagship" in label.lower(), f"label the tab that shows {path} as the flagship's"
        # Whole files: a line range would shift when the file is regenerated.
        assert not options & {"lines", "start-after", "end-before", "start-at", "end-at", "pyobject"}, options
    assert ".. code-block:: json" not in _read("docs/index.rst"), "a hand-written record goes stale"


def test_docs_home_page_python_tab_says_it_mints_its_own_iri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snippets = _load_tool(".tools/quality/run_doc_snippets.py")
    assert "docs/index.rst" in snippets.SNIPPET_FILES, "the doc-snippet job runs the home page's Python tab"
    blocks = [block for block in snippets._extract("docs/index.rst") if block.lang == "python"]
    assert len(blocks) == 1, blocks
    code = blocks[0].text

    monkeypatch.chdir(tmp_path)
    namespace: dict = {"__name__": "docs_home_page"}
    exec(compile(code, blocks[0].label, "exec"), namespace)

    flagship = json.loads(_read("examples/cell-spec/A123__ANR26650M1-B.json"))["cell_spec"]["id"]
    minted = namespace["result"].canonical_iri
    assert minted.startswith("https://w3id.org/battinfo/id/1001/spec/") and minted != flagship
    comments = " ".join(line.strip(" #") for line in code.splitlines() if line.lstrip().startswith("#"))
    assert "own IRI" in comments and "flagship" in comments, "say that the snippet mints its own IRI"


# ── Tutorials in Colab ────────────────────────────────────────────────────────

_COLAB_LINK = re.compile(r"https://colab\.research\.google\.com/github/[^\s)\"'>]+")


@pytest.mark.parametrize(
    "rel", ["README.md", "QUICKSTART.md", "docs/index.md", "docs/index.rst", "docs/pages/guides.rst"]
)
def test_colab_links_open_a_release_tag_with_an_install_cell(rel: str) -> None:
    """Colab opened on main runs the notebook as main has it, against whatever pip installs then."""
    for link in _COLAB_LINK.findall(_read(rel)):
        pinned = re.search(r"/blob/v\d+\.\d+\.\d+/(.+\.ipynb)$", link)
        assert pinned, f"{rel} opens {link} from a branch; pin it to a release tag"
        notebook = json.loads(_read(pinned.group(1)))
        code = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
        assert any("pip install" in source for source in code), f"{pinned.group(1)} has no install cell for Colab"


def test_getting_started_gives_the_lines_that_install_battinfo_in_a_notebook() -> None:
    """The Tutorials known limitation sends hosted-notebook users there for a line that runs in a cell."""
    lines = [line.strip() for line in _read("docs/pages/getting-started.rst").splitlines()]
    shell = {line.split("#")[0].strip() for line in lines if line.startswith("pip install ")}
    notebook = [line for line in lines if line.startswith("%pip install ")]
    assert any("[processing]" in line for line in notebook), "tutorial 6 needs the processing extra"
    assert any("[" not in line for line in notebook), "give the core line as well"
    for line in notebook:
        # The same requirement as a shell line on the page, so the stamp at the tag switches both to PyPI.
        assert line.removeprefix("%") in shell, f"{line} installs something no shell line on the page installs"

    scope = _read("docs/scope.md")
    start = scope.index("\n### Tutorials")
    entry = scope[start : scope.index("\n### ", start + 1)]
    assert "%pip" in entry and "pages/getting-started.rst" in entry, entry
