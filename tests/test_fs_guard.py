"""Recursive deletes go through one guard, ``battinfo._fs_guard``.

``force=True`` and ``--force`` used to delete whatever folder they were given,
with everything in it. These tests pin what the guard refuses, among it the
folder where ``battinfo.workspace()`` keeps a project's records, that roots
built by 0.8.0 (which carry no marker) still rebuild with ``--force`` while a
project folder BattINFO wrote into keeps its own files, JSON files included,
that the refusal names the files in the way, and that no other module calls
``shutil.rmtree``. The last section pins that the paths a workspace manifest
names stay inside the workspace.

Tests that point the guard at a home, working or filesystem-root folder replace
``shutil.rmtree`` with a function that fails, so a broken guard cannot delete
anything real.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo
from battinfo import CellSpec, publish
from battinfo._fs_guard import (
    MARKER_FILENAME,
    UnsafeDeleteError,
    check_relative_path,
    check_remove,
    is_within,
    remove_temp_tree,
    remove_tree,
)
from battinfo._workspace import Workspace, quantity
from battinfo.cli import app
from battinfo.demo import setup_demo_environment
from battinfo.ingest import build_ingest_workspace
from battinfo.local_workspace import LocalWorkspace
from battinfo.workspace_state import WorkspaceStateManifest

EXAMPLE_CELL_TYPE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"


def _spec() -> CellSpec:
    return CellSpec(manufacturer="Google", model="G20M7", format="pouch", chemistry="Li-ion")


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _make_evidence(tmp_path: Path) -> Path:
    # Short names: a workspace kept inside this folder nests deeply, and
    # Windows refuses paths over 260 characters.
    evidence = tmp_path / "ev"
    _write_tree(evidence, {
        "image/photo/IMG_0001.jpg": "fake-jpeg",
        "timeseries/raw/lab__c1__2026-04-09__rate__25degC.csv": "time_s,voltage_v\n0,4.20\n",
    })
    return evidence


@pytest.fixture
def no_rmtree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any delete that gets past the guard fail instead of deleting."""

    def _refuse(path: object, *args: object, **kwargs: object) -> None:
        raise AssertionError(f"the guard let a delete of {path} through")

    monkeypatch.setattr(shutil, "rmtree", _refuse)


# ── The guard ───────────────────────────────────────────────────────────────


def test_a_folder_battinfo_did_not_create_is_refused_and_kept(tmp_path: Path) -> None:
    folder = tmp_path / "my_project"
    _write_tree(folder, {"data/precious_cycler_run.csv": "t,v\n0,4.2\n"})

    with pytest.raises(UnsafeDeleteError, match="BattINFO did not create it") as refused:
        remove_tree(folder)

    assert str(folder) in str(refused.value)
    assert (folder / "data" / "precious_cycler_run.csv").exists()


def test_an_empty_folder_a_marked_folder_and_a_missing_one_are_fine(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    remove_tree(empty)
    assert not empty.exists()

    marked = tmp_path / "marked"
    _write_tree(marked, {MARKER_FILENAME: "x", "notes.txt": "added later", "records/a.json": "{}"})
    remove_tree(marked)
    assert not marked.exists()

    remove_tree(tmp_path / "never-made")


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param({"index.json": "{}", "examples/cell-spec/cell-spec-czgb-525v-rz6q-2xfd.json": "{}"}, id="publish-root"),
        pytest.param(
            {
                "index.json": "{}",
                "examples/cell-spec/cell-spec-czgb-525v-rz6q-2xfd.json": "{}",
                "dist/submission-package.cell_spec.czgb-525v-rz6q-2xfd.json": "{}",
            },
            id="publish-root-of-a-registry-publish",
        ),
        pytest.param(
            {
                "battinfo-authoring-workspace.json": "{}",
                "records/cell-spec/7d9k2m.json": "{}",
                "records/cell-instance/q93yzr.json": "{}",
                "records/tests/8d9ft1.json": "{}",
                "records/dataset/hqr8qr.json": "{}",
                "artifacts/dataset/hqr8qr/run.csv": "1",
                "dist/submission-package.json": "{}",
                "dist/registry-intake.json": "{}",
                "dist/registry-intake.zenodo.json": "{}",
                "dist/validation-report.json": "{}",
                "dist/normalized/test/8d9ft1.json": "{}",
            },
            id="ingest-root",
        ),
        pytest.param(
            {
                "battinfo-workspace.json": "{}",
                "resources/cell.json": "{}",
                "resources/test.json": "{}",
                "resources/dataset.json": "{}",
                "artifacts/cycling.csv": "1",
                "dist/registry-intake.json": "{}",
                "dist/zenodo-metadata.json": "{}",
                "dist/normalized/cell-instance/cell.json": "{}",
            },
            id="local-workspace",
        ),
        pytest.param(
            {
                "index.json": "{}",
                "examples/cell-spec/cell-spec-8re2-t25g-mv5p-zap2.json": "{}",
                "examples/cell-instance/cell-1kxx-22c8-jex0-aht8.json": "{}",
                "examples/test/test-c6fd-nzsp-peec-yjfx.json": "{}",
                "examples/dataset/dataset-2r0z-jk62-qsz9-ksct.json": "{}",
                "inputs/cycle-life.csv": "1",
            },
            id="demo-workspace",
        ),
        pytest.param(
            {
                "index.json": "{}",
                "examples/cell-spec/cell-spec-jk86-b096-m8pk-6cgf.json": "{}",
                "library/cell-spec/Google__G20M7.json": "{}",
                "library-rdf/cell-spec.index.json": "{}",
                "library-rdf/cell-spec/Google__G20M7.jsonld": "{}",
                "ontology/library/cell-spec.jsonld": "{}",
                "package/cell-spec/Google__G20M7.json": "{}",
                "publication/cycle-life/battinfo.publish.jsonld": "{}",
                "publication/cycle-life/cycle-life.csv": "1",
                "publication/cycle-life/index.html": "<html></html>",
                "release/battinfo-workspace.json": "{}",
                "release/artifacts/cycle-life.csv": "1",
                "release/dist/registry-intake.json": "{}",
                "battinfo-authoring-workspace.json": "{}",
                "records/tests/r312xy.json": "{}",
                "artifacts/dataset/vdegr2/cycle-life.csv": "1",
                "dist/validation-report.json": "{}",
                "dist/submission-package.dataset.vdegr2.json": "{}",
                "dist/registry-intake.dataset.vdegr2.json": "{}",
            },
            id="engine-root",
        ),
    ],
)
def test_a_root_built_by_0_8_0_without_the_marker_is_deleted(tmp_path: Path, layout: dict[str, str]) -> None:
    root = tmp_path / "root"
    _write_tree(root, layout)

    remove_tree(root)

    assert not root.exists()


def test_every_root_this_version_builds_is_recognised_without_its_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layouts the guard knows cover everything BattINFO writes into its roots.

    Each root is built as this version builds it, and its markers are then
    removed, as in a root built by 0.8.0. A new kind of entry at the top of a
    root, or a new file name in a record or report folder, fails here until
    the layouts in ``battinfo._fs_guard`` include it.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "battinfo._publish.submit_publication_package", lambda payload, **kwargs: {"status": "ok", "response": {}}
    )
    publish(_spec(), destination="local", root=tmp_path / "pub")
    publish(_spec(), destination="registry", root=tmp_path / "pub-registry", registry_base_url="https://registry.invalid",
            api_key="key", workspace_id="guard-demo", publisher_id="demo-lab")
    setup_demo_environment(tmp_path / "demo")
    build_ingest_workspace(
        _make_evidence(tmp_path), type_record=EXAMPLE_CELL_TYPE, workspace_root=tmp_path / "ing",
        workspace_id="guard-demo", publisher_id="demo-lab",
    )
    local = LocalWorkspace.init(tmp_path / "lw")
    local.validate(write_report=True)
    local.build_submission_package()
    local.clone(tmp_path / "lw-clone")
    local.new_version(tmp_path / "lw-v2", version="2.0.0")

    engine = Workspace(root=tmp_path / "eng", name="guard-demo", publisher="demo-lab")
    _write_tree(tmp_path, {"data/cycle-life.csv": "cycle,capacity_ah\n0,2.50\n"})
    cell_spec = engine.cell_spec(
        manufacturer="A123", model="ANR26650M1-B", format="cylindrical", chemistry="Li-ion",
        specs={"nominal_voltage": quantity(3.3, "V")},
    )
    cell = engine.cell(cell_spec, serial_number="guard-001", source_type="lab")
    test = engine.test(cell, kind="cycling", protocol="1C / 1C", status="completed")
    dataset = engine.dataset(cell, title="Guard dataset", test=test, path=tmp_path / "data" / "cycle-life.csv",
                             license="CC-BY-4.0")
    engine.save()
    engine.build_submission_package(dataset, registry="digibatt/hello-world")
    engine.build_publication_package(dataset, emit_html_page=True, emit_bundle_dir=True)
    engine.describe_cell(manufacturer="Google", model="G20M7", format="pouch", chemistry="Li-ion")
    engine.save_descriptions(mode="upsert")
    engine.save_workspace()
    engine.check_workspace(write_report=True)
    engine.bundle_workspace()
    engine.bundle_workspace(dataset)

    roots = ["pub", "pub-registry", "demo/workspace", "demo/release", "ing", "lw", "lw-clone", "lw-v2", "eng"]
    for name in roots:
        root = tmp_path / name
        for marker in root.rglob(MARKER_FILENAME):
            marker.unlink()
        assert any(root.iterdir()), name
        check_remove(root)
    assert {"library", "publication", "release", "records"} <= {entry.name for entry in (tmp_path / "eng").iterdir()}
    assert list((tmp_path / "pub-registry" / "dist").glob("submission-package.cell_spec.*.json"))
    assert list((tmp_path / "eng" / "dist").glob("submission-package.dataset.*.json"))


def test_index_json_next_to_records_is_not_a_root_battinfo_built(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_tree(root, {"index.json": "{}", "records/cell-spec/x.json": "{}"})

    with pytest.raises(UnsafeDeleteError, match="BattINFO did not create it"):
        remove_tree(root)

    assert (root / "records" / "cell-spec" / "x.json").exists()


@pytest.mark.parametrize(
    ("target", "tree"),
    [
        pytest.param(
            "lab/.battinfo",
            {"lab/.battinfo/index.json": "{}", "lab/.battinfo/records/cell-spec/cell-spec-x.json": "{}"},
            id="records-of-0.8",
        ),
        pytest.param(
            "lab/.battinfo/records",
            {"lab/.battinfo/records/index.json": "{}", "lab/.battinfo/records/examples/cell-spec/x.json": "{}"},
            id="records-of-0.7",
        ),
        pytest.param(
            "lab/.battinfo",
            {f"lab/.battinfo/{MARKER_FILENAME}": "x", "lab/.battinfo/records/cell-spec/x.json": "{}"},
            id="marked",
        ),
        pytest.param(
            "lab",
            {f"lab/{MARKER_FILENAME}": "x", "lab/.battinfo/records/cell-spec/x.json": "{}"},
            id="folder-holding-one",
        ),
    ],
)
def test_the_folder_where_a_workspace_keeps_its_records_is_refused(
    tmp_path: Path, target: str, tree: dict[str, str]
) -> None:
    _write_tree(tmp_path, tree)

    with pytest.raises(UnsafeDeleteError, match=r"battinfo\.workspace\(\) keeps a project's records"):
        remove_tree(tmp_path / target)

    assert all((tmp_path / relative).exists() for relative in tree)


@pytest.mark.parametrize(
    ("own", "in_the_way"),
    [
        pytest.param({"inputs/raw_cycler_run.csv": "t,v\n0,4.2\n"}, "inputs/raw_cycler_run.csv", id="inputs"),
        pytest.param(
            {"inputs/cycle-life.csv": "1", "inputs/notes.txt": "mine"}, "inputs/notes.txt",
            id="inputs-beside-the-demo-file",
        ),
        pytest.param({"publication/main.tex": "x"}, "publication/main.tex", id="publication-file"),
        pytest.param({"publication/figures/plot.png": "x"}, "publication/figures", id="publication-folder"),
        pytest.param({"dist/mypkg-1.0-py3-none-any.whl": "x"}, "dist/mypkg-1.0-py3-none-any.whl", id="dist"),
        pytest.param({"dist/results-summary.json": "{}"}, "dist/results-summary.json", id="dist-json"),
        pytest.param({"dist/assets/app.js": "x", "dist/assets/manifest.json": "{}"}, "dist/assets", id="dist-folder"),
        pytest.param({"library/paper.pdf": "x"}, "library/paper.pdf", id="library"),
        pytest.param({"library/datasheets.json": "{}"}, "library/datasheets.json", id="library-json"),
        pytest.param({"package/package.json": "{}"}, "package/package.json", id="package-json"),
        pytest.param({"library-rdf/terms.jsonld": "{}"}, "library-rdf/terms.jsonld", id="library-rdf-jsonld"),
        pytest.param({"ontology/my-lab-terms.jsonld": "{}"}, "ontology/my-lab-terms.jsonld", id="ontology-jsonld"),
        pytest.param({"release/notes.md": "x"}, "release", id="release"),
        pytest.param(
            {f"release/{MARKER_FILENAME}": "x", "release/.battinfo/records/cell-spec/x.json": "{}"}, "release/.battinfo",
            id="release-holding-a-workspace-store",
        ),
        pytest.param({"examples/analysis.ipynb": "{}"}, "examples/analysis.ipynb", id="examples"),
        pytest.param({"examples/request.json": "{}"}, "examples/request.json", id="examples-json"),
        pytest.param({"examples/cell-spec/my-cell.json": "{}"}, "examples/cell-spec/my-cell.json", id="examples-name"),
        pytest.param({"artifacts/run.csv": "1"}, "artifacts", id="artifacts"),
    ],
)
def test_a_common_folder_name_counts_only_with_the_content_battinfo_writes_there(
    tmp_path: Path, own: dict[str, str], in_the_way: str
) -> None:
    root = tmp_path / "a_project"
    _write_tree(root, {"index.json": "{}", "examples/cell-spec/cell-spec-x.json": "{}", **own})

    with pytest.raises(UnsafeDeleteError, match=re.escape(f"it holds {Path(in_the_way)}, which is not BattINFO output")):
        remove_tree(root)

    assert all((root / relative).exists() for relative in own)


@pytest.mark.parametrize(
    ("layout", "own", "in_the_way"),
    [
        pytest.param(
            {"battinfo-authoring-workspace.json": "{}", "records/cell-spec/7d9k2m.json": "{}"},
            {"records/notes/plan.json": "{}"}, "records/notes", id="ingest-records",
        ),
        pytest.param(
            {"battinfo-authoring-workspace.json": "{}", "dist/submission-package.json": "{}"},
            {"dist/normalized/cell-spec/summary.csv": "x"}, "dist/normalized/cell-spec/summary.csv", id="ingest-dist",
        ),
        pytest.param(
            {"battinfo-workspace.json": "{}", "resources/cell.json": "{}"},
            {"resources/drafts/cell.json": "{}"}, "resources/drafts", id="local-workspace-resources",
        ),
        pytest.param(
            {"battinfo-workspace.json": "{}", "dist/registry-intake.json": "{}"},
            {"dist/analysis.json": "{}"}, "dist/analysis.json", id="local-workspace-dist",
        ),
    ],
)
def test_a_records_or_reports_folder_holds_only_the_names_battinfo_gives(
    tmp_path: Path, layout: dict[str, str], own: dict[str, str], in_the_way: str
) -> None:
    root = tmp_path / "root"
    _write_tree(root, {**layout, **own})

    with pytest.raises(UnsafeDeleteError, match=re.escape(f"it holds {Path(in_the_way)}, which is not BattINFO output")):
        remove_tree(root)

    assert all((root / relative).exists() for relative in own)


def test_the_refusal_names_the_file_in_the_way_not_the_battinfo_folder(tmp_path: Path) -> None:
    root = tmp_path / "r1"
    _write_tree(root, {
        "index.json": "{}",
        "examples/cell-spec/cell-spec-x.json": "{}",
        "examples/cell-spec/notes.md": "mine",
    })

    with pytest.raises(UnsafeDeleteError) as refused:
        publish(_spec(), destination="local", root=root, force=True)

    message = str(refused.value)
    assert f"it holds {Path('examples/cell-spec/notes.md')}, which is not BattINFO output" in message
    assert "it holds examples," not in message
    assert (root / "examples" / "cell-spec" / "notes.md").exists()


def test_the_refusal_names_five_things_in_the_way_and_counts_the_rest(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_tree(root, {"index.json": "{}", **{f"examples/notes-{n}.md": "mine" for n in range(7)}})

    with pytest.raises(UnsafeDeleteError) as refused:
        remove_tree(root)

    message = str(refused.value)
    assert f"{Path('examples/notes-4.md')} and 2 more, which are not BattINFO output" in message
    assert "notes-5" not in message


def test_what_battinfo_leaves_part_way_through_a_write_counts_as_its_own(tmp_path: Path) -> None:
    """A crash can leave _jsonio's temporary file, or the folders workspace_state swaps in and out."""
    root = tmp_path / "root"
    _write_tree(root, {
        "index.json": "{}",
        "examples/cell-spec/cell-spec-x.json": "{}",
        "battinfo-authoring-workspace.json": "{}",
        "records/cell-spec/7d9k2m.json": "{}",
    })
    # Named as _jsonio.atomic_write_text and workspace_state._swap_dir name them.
    handle, _ = tempfile.mkstemp(dir=root / "examples" / "cell-spec", prefix=".cell-spec-y.json.", suffix=".tmp")
    os.close(handle)
    staging = Path(tempfile.mkdtemp(dir=root / "records", prefix=".cell-spec.staging-"))
    (staging / "7d9k2m.json").write_text("{}", encoding="utf-8")
    shutil.copytree(staging, staging.with_name(staging.name + ".bak"))

    remove_tree(root)

    assert not root.exists()


def test_a_temporary_file_counts_only_where_the_file_it_stands_in_for_would(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_tree(root, {"index.json": "{}", "examples/cell-spec/cell-spec-x.json": "{}"})
    handle, leftover = tempfile.mkstemp(dir=root / "examples" / "cell-spec", prefix=".notes.md.", suffix=".tmp")
    os.close(handle)

    with pytest.raises(UnsafeDeleteError, match=re.escape(str(Path(leftover).relative_to(root)))):
        remove_tree(root)


def test_an_old_layout_that_also_holds_other_files_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_tree(root, {
        "index.json": "{}",
        "examples/cell-spec/cell-spec-x.json": "{}",
        "data/precious.csv": "1",
        "analysis.ipynb": "{}",
    })

    with pytest.raises(UnsafeDeleteError, match=r"it holds analysis\.ipynb, data, which are not BattINFO output"):
        remove_tree(root)

    assert (root / "data" / "precious.csv").exists()


def test_home_and_working_folders_their_parents_and_filesystem_roots_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_rmtree: None
) -> None:
    home = tmp_path / "home" / "user"
    work = tmp_path / "work" / "project"
    for folder in (home, work):
        # Marked, so only the home and working-folder rules can refuse them.
        _write_tree(folder, {MARKER_FILENAME: "x"})
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)

    for target in (home, home.parent):
        with pytest.raises(UnsafeDeleteError, match="home folder"):
            remove_tree(target)
    for target in (work, work.parent, Path(".")):
        with pytest.raises(UnsafeDeleteError, match="current working folder"):
            remove_tree(target)
    with pytest.raises(UnsafeDeleteError, match="root of a drive or file system"):
        remove_tree(Path(tmp_path.anchor))
    with pytest.raises(UnsafeDeleteError, match="home folder"):
        remove_temp_tree(home)
    assert (home / MARKER_FILENAME).exists() and (work / MARKER_FILENAME).exists()


def test_a_folder_that_overlaps_an_input_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _write_tree(out, {MARKER_FILENAME: "x", "evidence/run.csv": "1"})
    evidence_file = out / "evidence" / "run.csv"

    with pytest.raises(UnsafeDeleteError, match="which this operation reads"):
        remove_tree(out, inputs=[evidence_file])
    with pytest.raises(UnsafeDeleteError, match="which this operation reads"):
        remove_tree(out, inputs=[out])
    with pytest.raises(UnsafeDeleteError, match="lies inside"):
        remove_tree(out / "evidence", inputs=[None, out])

    assert evidence_file.exists()
    remove_tree(out, inputs=[None, tmp_path / "elsewhere.csv"])
    assert not out.exists()


def test_a_path_read_from_a_manifest_must_stay_inside_its_root(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _write_tree(workspace, {"dist/report.json": "{}"})
    precious = tmp_path / "x" / "precious.txt"
    _write_tree(tmp_path / "x", {"precious.txt": "keep"})

    with pytest.raises(UnsafeDeleteError, match="not inside"):
        remove_tree(workspace / ".." / "x", within=workspace)
    with pytest.raises(UnsafeDeleteError, match="not inside"):
        remove_tree(workspace / ".", within=workspace)
    with pytest.raises(UnsafeDeleteError, match="not inside"):
        remove_tree(tmp_path / "x" / "gone", within=workspace)
    assert precious.exists()

    # A derived folder inside its root needs no marker of its own.
    remove_tree(workspace / "dist", within=workspace)
    assert not (workspace / "dist").exists()


def test_is_within_resolves_dot_dot_segments(tmp_path: Path) -> None:
    assert is_within(tmp_path / "a" / "b", tmp_path / "a")
    assert is_within(tmp_path / "a", tmp_path / "a")
    assert not is_within(tmp_path / "a" / ".." / "b", tmp_path / "a")
    assert not is_within(tmp_path / "ab", tmp_path / "a")


def test_temp_cleanup_removes_a_folder_and_ignores_a_missing_one(tmp_path: Path) -> None:
    made = tmp_path / "made"
    _write_tree(made, {"x/y.txt": "1"})
    remove_temp_tree(made)
    assert not made.exists()
    remove_temp_tree(tmp_path / "gone")


def test_only_the_guard_module_calls_rmtree() -> None:
    """``shutil.rmtree`` appears nowhere in src/battinfo but in the guard module.

    The text search covers comments and strings too; the syntax walk catches
    ``from shutil import rmtree`` and an aliased module.
    """
    package = ROOT / "src" / "battinfo"
    offenders: set[str] = set()
    for path in sorted(package.rglob("*.py")):
        if path == package / "_fs_guard.py":
            continue
        source = path.read_text(encoding="utf-8")
        where = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(source.splitlines(), start=1):
            if "shutil.rmtree" in line:
                offenders.add(f"{where}:{lineno}")
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, ast.Attribute) and node.attr == "rmtree":
                offenders.add(f"{where}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module == "shutil" and any(
                alias.name in {"rmtree", "*"} for alias in node.names
            ):
                offenders.add(f"{where}:{node.lineno}")
    assert not offenders, (
        "Delete folders through battinfo._fs_guard (remove_tree or remove_temp_tree), "
        f"not shutil.rmtree: {sorted(offenders)}"
    )


# ── publish(force=True) and `battinfo publish cell-spec --force` ────────────


def test_publish_force_refuses_a_project_folder_and_keeps_its_files(tmp_path: Path) -> None:
    project = tmp_path / "my_project"
    _write_tree(project, {"data/precious_cycler_run.csv": "time_s,voltage_v\n0,4.2\n", "analysis.ipynb": "{}"})

    with pytest.raises(UnsafeDeleteError, match="BattINFO did not create it"):
        publish(_spec(), destination="local", root=project, force=True)

    assert (project / "data" / "precious_cycler_run.csv").exists()
    assert (project / "analysis.ipynb").exists()


def test_publish_cli_force_rebuilds_a_root_built_by_0_8_0(tmp_path: Path) -> None:
    root = tmp_path / "publish-root"
    _write_tree(root, {"index.json": "{}", "examples/cell-spec/cell-spec-stale.json": "{}"})

    result = CliRunner().invoke(app, [
        "publish", "cell-spec",
        "--manufacturer", "Google", "--model", "G20M7", "--cell-format", "pouch", "--chemistry", "Li-ion",
        "--root", str(root), "--force", "--format", "json",
    ])

    assert result.exit_code == 0, result.stdout
    assert not (root / "examples" / "cell-spec" / "cell-spec-stale.json").exists()
    assert Path(json.loads(result.stdout)["debug_paths"]["canonical_record_path"]).exists()
    assert (root / MARKER_FILENAME).exists()


def test_publish_cli_force_refuses_a_root_that_holds_the_input_file(tmp_path: Path) -> None:
    root = tmp_path / "publish-root"
    _write_tree(root, {MARKER_FILENAME: "x"})
    draft = root / "draft.json"
    draft.write_text(json.dumps({"manufacturer": "Google", "model": "G20M7", "format": "pouch",
                                 "chemistry": "Li-ion"}), encoding="utf-8")

    result = CliRunner().invoke(app, [
        "publish", "cell-spec", "--input", str(draft), "--root", str(root), "--force",
    ])

    assert result.exit_code == 1
    assert "Refusing to delete" in result.stdout
    assert draft.exists()


def test_new_output_roots_carry_the_marker_and_a_marked_root_rebuilds(tmp_path: Path) -> None:
    root = tmp_path / "out"
    publish(_spec(), destination="local", root=root)
    assert (root / MARKER_FILENAME).is_file()

    (root / "notes.txt").write_text("added by hand", encoding="utf-8")
    publish(_spec(), destination="local", root=root, force=True)
    assert not (root / "notes.txt").exists()
    assert (root / MARKER_FILENAME).is_file()


@pytest.mark.parametrize(
    ("own", "in_the_way"),
    [
        ("data/run.csv", "data"),
        ("inputs/raw_cycler_run.csv", "inputs/raw_cycler_run.csv"),
        ("ontology/my-lab-terms.jsonld", "ontology/my-lab-terms.jsonld"),
        ("dist/results-summary.json", "dist/results-summary.json"),
    ],
)
def test_a_folder_battinfo_writes_into_is_not_marked(tmp_path: Path, own: str, in_the_way: str) -> None:
    """A publish without force writes index.json and examples/ into a project folder; force then keeps its files."""
    project = tmp_path / "my_project"
    _write_tree(project, {own: "t,v\n0,4.2\n"})

    publish(_spec(), destination="local", root=project)

    assert not (project / MARKER_FILENAME).exists()
    with pytest.raises(UnsafeDeleteError, match=re.escape(f"{Path(in_the_way)}, which is not BattINFO output")):
        publish(_spec(), destination="local", root=project, force=True)
    assert (project / own).exists()


def test_the_authoring_workspace_folder_is_not_marked(tmp_path: Path) -> None:
    battinfo.workspace(tmp_path / "lab", registry_url=None)

    assert (tmp_path / "lab" / ".battinfo").is_dir()
    assert not (tmp_path / "lab" / ".battinfo" / MARKER_FILENAME).exists()


def test_publish_cli_force_refuses_the_folder_where_a_workspace_keeps_its_records(tmp_path: Path) -> None:
    """After an offline session the folder holds only index.json and records/."""
    ws = battinfo.workspace(tmp_path / "lab", registry_url=None)
    spec = CellSpec(manufacturer="Example Lab", model="R2032 graphite half cell", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01", "C02"])
    ws.save()
    store = tmp_path / "lab" / ".battinfo"
    saved = sorted(store.rglob("*.json"))

    result = CliRunner().invoke(app, [
        "publish", "cell-spec",
        "--manufacturer", "Google", "--model", "G20M7", "--cell-format", "pouch", "--chemistry", "Li-ion",
        "--root", str(store), "--force",
    ])

    assert result.exit_code == 1
    assert "keeps a project's records there" in result.stdout
    assert len(saved) == 4 and all(path.exists() for path in saved)


# ── Ingest builds ───────────────────────────────────────────────────────────


def _ingest_args(evidence: Path, root: Path) -> list[str]:
    return [
        "ingest", "build", str(evidence),
        "--type-record", str(EXAMPLE_CELL_TYPE),
        "--workspace-root", str(root),
        "--workspace-id", "guard-demo", "--publisher-id", "demo-lab",
        "--force", "--format", "json",
    ]


def test_ingest_build_refuses_the_evidence_folder_as_its_workspace_root(tmp_path: Path) -> None:
    evidence = _make_evidence(tmp_path)
    files = sorted(path for path in evidence.rglob("*") if path.is_file())

    result = CliRunner().invoke(app, _ingest_args(evidence, evidence))

    assert result.exit_code == 1
    assert "Refusing to delete" in result.stdout
    assert files and all(path.exists() for path in files)


def test_ingest_build_force_rebuilds_a_root_built_by_0_8_0(tmp_path: Path) -> None:
    evidence = _make_evidence(tmp_path)
    root = tmp_path / "ingest-workspace"
    _write_tree(root, {
        "battinfo-authoring-workspace.json": "{}",
        "records/cell-spec/stale.json": "{}",
        "artifacts/dataset/stale/run.csv": "1",
        "dist/registry-intake.json": "{}",
    })

    result = CliRunner().invoke(app, _ingest_args(evidence, root))

    assert result.exit_code == 0, result.stdout
    assert not (root / "records" / "cell-spec" / "stale.json").exists()
    assert (root / "battinfo-authoring-workspace.json").exists()
    assert (root / MARKER_FILENAME).exists()


def test_a_workspace_kept_inside_the_evidence_folder_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`battinfo dataset process --force` run from the folder keeps its workspace under ./.battinfo/."""
    evidence = _make_evidence(tmp_path)
    monkeypatch.chdir(evidence)
    kwargs = dict(type_record=EXAMPLE_CELL_TYPE, workspace_id="guard-demo", publisher_id="demo-lab", clean=True)

    first = build_ingest_workspace(evidence, **kwargs)
    second = build_ingest_workspace(evidence, **kwargs)

    assert first["workspace_root"] == second["workspace_root"]
    assert (evidence / first["workspace_root"] / "battinfo-authoring-workspace.json").exists()
    assert (evidence / "timeseries" / "raw").is_dir()


# ── LocalWorkspace clone, new_version and export ────────────────────────────


def test_clone_or_new_version_into_its_own_root_is_refused(tmp_path: Path) -> None:
    workspace = LocalWorkspace.init(tmp_path / "release-v1")

    with pytest.raises(ValueError, match="one of the two folders holds the other"):
        workspace.clone(workspace.root, force=True)
    with pytest.raises(ValueError, match="one of the two folders holds the other"):
        workspace.new_version(workspace.root, version="2.0.0", force=True)
    with pytest.raises(ValueError, match="one of the two folders holds the other"):
        workspace.clone(workspace.root / "nested")
    with pytest.raises(ValueError, match="one of the two folders holds the other"):
        workspace.clone(tmp_path, force=True)

    assert workspace.manifest_path.exists()
    assert (workspace.root / "resources" / "cell.json").exists()
    assert not (workspace.root / "nested").exists()


def test_a_manifest_dist_dir_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    workspace = LocalWorkspace.init(tmp_path / "ws")
    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    manifest["dist_dir"] = "../x"
    workspace.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _write_tree(tmp_path / "x", {"precious.txt": "keep"})

    with pytest.raises(ValueError):
        workspace.clone(tmp_path / "clone")

    assert (tmp_path / "x" / "precious.txt").exists()
    assert not (tmp_path / "clone").exists()


def test_clone_force_replaces_a_release_root_built_by_0_8_0(tmp_path: Path) -> None:
    source = LocalWorkspace.init(tmp_path / "source")
    target = tmp_path / "target"
    _write_tree(target, {
        "battinfo-workspace.json": "{}",
        "resources/cell.json": "{}",
        "artifacts/stale.csv": "1",
        "dist/registry-intake.json": "{}",
    })

    clone = source.clone(target, force=True)

    assert not (target / "artifacts" / "stale.csv").exists()
    assert clone.manifest_path.exists()
    assert (target / MARKER_FILENAME).exists()


def test_export_force_refuses_a_release_root_that_holds_the_dataset_file(tmp_path: Path) -> None:
    engine = Workspace(root=tmp_path / "engine")
    release = tmp_path / "release"
    data_file = release / "cycle-life.csv"
    _write_tree(release, {MARKER_FILENAME: "x", "cycle-life.csv": "cycle,capacity_ah\n0,2.50\n"})
    cell_spec = engine.cell_spec(
        manufacturer="A123", model="ANR26650M1-B", format="cylindrical", chemistry="Li-ion",
        specs={"nominal_voltage": quantity(3.3, "V")},
    )
    cell = engine.cell(cell_spec, serial_number="guard-001", source_type="lab")
    test = engine.test(cell, kind="cycling", protocol="1C / 1C", status="completed")
    dataset = engine.dataset(cell, title="Guard dataset", test=test, path=data_file, license="CC-BY-4.0")

    with pytest.raises(UnsafeDeleteError, match="which this operation reads"):
        engine.build_submission_package(dataset, root=release, registry="digibatt/hello-world", force=True)

    assert data_file.exists()


# ── Paths a workspace manifest names ────────────────────────────────────────


@pytest.mark.parametrize("value", [
    "../x", r"..\x", "dist/../../x", "dist/..", "/tmp/x", r"\x", r"C:\x", "C:x",
    r"\\host\share\x", "//host/share/x", "", ".", "./", "...", " ",
])
def test_a_manifest_path_that_leaves_the_folder_or_names_it_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="dist_dir"):
        check_relative_path(value, field="dist_dir")


@pytest.mark.parametrize("value", ["dist", "out/dist", r"out\dist", "./dist", "records/cell-spec", "resources/cell.json"])
def test_a_relative_manifest_path_inside_the_folder_is_kept(value: str) -> None:
    assert check_relative_path(value, field="dist_dir") == value


def _edit_manifest(path: Path, keys: tuple[str | int, ...], value: str) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    node = manifest
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "keys",
    [("dist_dir",), ("artifacts_dir",), ("resources", "cell"), ("resources", "test"), ("resources", "dataset")],
    ids=".".join,
)
def test_a_local_workspace_manifest_path_outside_the_workspace_is_refused_on_load(
    tmp_path: Path, keys: tuple[str, ...]
) -> None:
    workspace = LocalWorkspace.init(tmp_path / "ws")
    _edit_manifest(workspace.manifest_path, keys, "../outside")

    with pytest.raises(ValueError, match=re.escape(".".join(keys))):
        workspace.load()


def test_validate_reports_a_dist_dir_outside_the_workspace_and_writes_nothing_there(tmp_path: Path) -> None:
    workspace = LocalWorkspace.init(tmp_path / "ws")
    _edit_manifest(workspace.manifest_path, ("dist_dir",), "../outside")

    report = workspace.validate(write_report=True)

    assert report["ok"] is False
    assert "dist_dir '../outside'" in report["issues"][0]["message"]
    assert not (tmp_path / "outside").exists()


def test_update_release_rewrites_no_file_outside_the_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace.init(tmp_path / "ws")
    victim = tmp_path / "outside" / "dataset.json"
    victim.parent.mkdir()
    shutil.copyfile(workspace.root / "resources" / "dataset.json", victim)
    before = victim.read_text(encoding="utf-8")
    _edit_manifest(workspace.manifest_path, ("resources", "dataset"), "../outside/dataset.json")

    with pytest.raises(ValueError, match=re.escape("resources.dataset")):
        workspace.update_release(version="9.9.9")

    assert victim.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "keys",
    [("dist_dir",), ("artifacts_dir",), ("paths", "cell_specs"), ("paths", "cells"), ("paths", "tests"), ("paths", "datasets")],
    ids=".".join,
)
def test_an_authoring_workspace_manifest_path_outside_the_workspace_is_refused(keys: tuple[str, ...]) -> None:
    raw: dict = {"paths": {}}
    node = raw
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = r"C:\outside"

    with pytest.raises(ValueError, match=re.escape(".".join(keys))):
        WorkspaceStateManifest.model_validate(raw)


def test_reopening_copies_no_dataset_artifact_from_outside_the_workspace(tmp_path: Path) -> None:
    """A manifest's artifact path is read back as the dataset's file, which the next save copies."""
    root = tmp_path / "ws"
    _write_tree(tmp_path, {"inputs/a.csv": "cycle,capacity_ah\n0,2.50\n", "secret/notes.txt": "private"})
    engine = Workspace(root, name="guard", title="Guard", tenant="digibatt", publisher="demo-lab", version="0.1.0")
    cell_spec = engine.cell_spec(
        manufacturer="A123", model="ANR26650M1-B", format="cylindrical", chemistry="Li-ion",
        specs={"nominal_voltage": quantity(3.3, "V")}, source_file="a123.manual.json",
    )
    cell = engine.cell(cell_spec, serial_number="guard-001", source_type="lab")
    test = engine.test(cell, kind="cycling", protocol="1C / 1C", status="completed")
    engine.dataset(cell, title="Guard dataset", test=test, path=tmp_path / "inputs" / "a.csv", license="CC-BY-4.0")
    engine.save_workspace()
    _edit_manifest(root / "battinfo-authoring-workspace.json", ("dataset_artifacts", 0, "path"), "../secret")

    with pytest.raises(ValueError, match="dataset_artifacts"):
        Workspace.open(root).save_workspace()

    assert not list(root.rglob("notes.txt"))
