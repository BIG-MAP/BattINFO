"""Recursive deletes go through one guard, ``battinfo._fs_guard``.

``force=True`` and ``--force`` used to delete whatever folder they were given,
with everything in it. These tests pin what the guard refuses, that roots built
by 0.8.0 (which carry no marker) still rebuild with ``--force``, and that no
other module calls ``shutil.rmtree``.

Tests that point the guard at a home, working or filesystem-root folder replace
``shutil.rmtree`` with a function that fails, so a broken guard cannot delete
anything real.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
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
    is_within,
    remove_temp_tree,
    remove_tree,
)
from battinfo._workspace import Workspace, quantity
from battinfo.cli import app
from battinfo.ingest import build_ingest_workspace
from battinfo.local_workspace import LocalWorkspace

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
        pytest.param({"index.json": "{}", "examples/cell-spec/cell-spec-x.json": "{}"}, id="publish-root"),
        pytest.param(
            {
                "battinfo-authoring-workspace.json": "{}",
                "records/cell-spec/x.json": "{}",
                "artifacts/dataset/x/run.csv": "1",
                "dist/submission-package.json": "{}",
            },
            id="ingest-root",
        ),
        pytest.param(
            {
                "battinfo-workspace.json": "{}",
                "resources/cell.json": "{}",
                "artifacts/cycling.csv": "1",
                "dist/registry-intake.json": "{}",
            },
            id="local-workspace",
        ),
        pytest.param({"index.json": "{}", "examples/x.json": "{}", "inputs/cycle-life.csv": "1"}, id="demo-workspace"),
        pytest.param({"index.json": "{}", "records/cell-spec/x.json": "{}", "library/x.json": "{}"}, id="records-layout"),
    ],
)
def test_a_root_built_by_0_8_0_without_the_marker_is_deleted(tmp_path: Path, layout: dict[str, str]) -> None:
    root = tmp_path / "root"
    _write_tree(root, layout)

    remove_tree(root)

    assert not root.exists()


def test_an_old_layout_that_also_holds_other_files_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write_tree(root, {
        "index.json": "{}",
        "examples/x.json": "{}",
        "data/precious.csv": "1",
        "analysis.ipynb": "{}",
    })

    with pytest.raises(UnsafeDeleteError, match=r"analysis\.ipynb, data"):
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


def test_a_folder_battinfo_writes_into_is_not_marked(tmp_path: Path) -> None:
    project = tmp_path / "my_project"
    _write_tree(project, {"data/run.csv": "1"})

    publish(_spec(), destination="local", root=project)

    assert not (project / MARKER_FILENAME).exists()
    with pytest.raises(UnsafeDeleteError, match="data, which BattINFO did not put there"):
        publish(_spec(), destination="local", root=project, force=True)
    assert (project / "data" / "run.csv").exists()


def test_the_authoring_workspace_folder_is_not_marked(tmp_path: Path) -> None:
    battinfo.workspace(tmp_path / "lab", registry_url=None)

    assert (tmp_path / "lab" / ".battinfo").is_dir()
    assert not (tmp_path / "lab" / ".battinfo" / MARKER_FILENAME).exists()


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
