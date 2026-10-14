"""The cell-spec library the batch path reads, and what happens when it lacks a cell spec.

``battinfo batch init``, ``battinfo dataset process`` and ``battinfo batch package``
look a cell spec up in the library packaged with battinfo, then in
``./.battinfo/library/cell-spec``. The packaged library has to be found from the
package itself: an installed wheel has no ``src/`` folder, and a path built from
the repository layout made all three commands fail there, or write a cell spec
with nothing but its IRI. A cell spec that neither library holds is an error that
names the IRI and both folders.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import battinfo
from battinfo.api import PACKAGED_LIBRARY_CELL_SPEC_DIR, query_library_cell_specs
from battinfo.cli import app
from battinfo.contribution import (
    BATCH_MANIFEST,
    CONTRIBUTION_MANIFEST,
    INGEST_MANIFEST,
    TEMPLATE_DIR,
    init_batch,
    package_batch,
    process_contribution,
)
from battinfo.publication import DEFAULT_CR2032_LIBRARY_SPEC

runner = CliRunner()

ENERGIZER_IRI = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
# A well-formed cell-spec IRI that no library holds.
UNKNOWN_IRI = "https://w3id.org/battinfo/spec/zzzz-zzzz-zzzz-zzzz"
CREATORS = [{"name": "Clark, Simon", "affiliation": "SINTEF"}]


def _local_library(folder: Path) -> Path:
    return Path(folder).absolute() / ".battinfo" / "library" / "cell-spec"


def _assert_names_the_libraries(message: str, folder: Path) -> None:
    assert str(PACKAGED_LIBRARY_CELL_SPEC_DIR) in message
    assert str(_local_library(folder)) in message
    assert "battinfo library save cell-spec" in message
    assert "--no-sync-packaged-copy" in message  # no stray ./src/battinfo/ copy outside a checkout


def _cell_with_data(batch_dir: Path, result: dict) -> Path:
    cell = batch_dir / result["cells"][0]["folder"]
    (cell / "2025-06-01__capacity_check__25degC.csv").write_text("time,voltage\n0,3.0\n1,2.9\n", encoding="utf-8")
    return cell


def _point_batch_at(batch_dir: Path, cell_spec_iri: str) -> None:
    """Make batch.yaml name another cell spec, as a hand edit or an older battinfo can."""
    manifest = yaml.safe_load((batch_dir / BATCH_MANIFEST).read_text(encoding="utf-8"))
    manifest["cell_spec_iri"] = cell_spec_iri
    (batch_dir / BATCH_MANIFEST).write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


# ── Where the packaged library is ─────────────────────────────────────────────


def test_the_packaged_library_is_found_from_the_package_itself() -> None:
    package_dir = Path(battinfo.__file__).resolve().parent
    assert PACKAGED_LIBRARY_CELL_SPEC_DIR == package_dir / "data" / "library" / "cell-spec"
    assert DEFAULT_CR2032_LIBRARY_SPEC.parent == PACKAGED_LIBRARY_CELL_SPEC_DIR
    assert DEFAULT_CR2032_LIBRARY_SPEC.is_file()


def test_the_contribution_template_gives_a_packaged_cell_spec_as_its_example() -> None:
    # The example IRI in the battinfo.yaml that `battinfo dataset init` writes
    # was under cell/, the namespace of cell instances, and named no record.
    text = (TEMPLATE_DIR / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
    examples = re.findall(r"^# Example: (\S+)", text, flags=re.MULTILINE)
    assert examples, text
    for iri in examples:
        assert iri.startswith("https://w3id.org/battinfo/spec/"), iri
        assert query_library_cell_specs(id=iri, directory=PACKAGED_LIBRARY_CELL_SPEC_DIR), iri


_RUN_OUTSIDE_A_CHECKOUT = """
import json
from pathlib import Path

import battinfo
from battinfo.contribution import _load_cell_spec_for_batch, _resolve_type_record_path, init_batch
from battinfo.publication import DEFAULT_CR2032_LIBRARY_SPEC

batch = init_batch(Path("batch"), "Energizer CR2032", 1)
cell_spec, _ = _load_cell_spec_for_batch(batch["cell_spec_iri"])
print(json.dumps({
    "package": str(Path(battinfo.__file__).resolve().parent),
    "default_cr2032_library_spec": str(DEFAULT_CR2032_LIBRARY_SPEC),
    "cell_spec_iri": batch["cell_spec_iri"],
    "cell_spec_name": batch["cell_spec_name"],
    "manufacturer": cell_spec.manufacturer,
    "model": cell_spec.model,
    "type_record": _resolve_type_record_path(batch["cell_spec_iri"]),
}))
"""


def test_the_batch_path_finds_the_packaged_library_outside_a_source_checkout(tmp_path: Path) -> None:
    # An installed wheel puts the package in site-packages, with no src/ folder above
    # it. Copy the package to such a folder and run the three lookups of the batch
    # path (batch init, batch package, dataset process) from an empty folder.
    package_dir = Path(battinfo.__file__).resolve().parent
    site_packages = tmp_path / "site-packages"
    shutil.copytree(package_dir, site_packages / "battinfo", ignore=shutil.ignore_patterns("__pycache__"))
    work = tmp_path / "work"
    work.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [str(site_packages), os.environ.get("PYTHONPATH")])),
    }

    proc = subprocess.run(
        [sys.executable, "-c", _RUN_OUTSIDE_A_CHECKOUT],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    copied_library = site_packages.resolve() / "battinfo" / "data" / "library" / "cell-spec"
    assert out["package"] == str(site_packages.resolve() / "battinfo")
    assert out["default_cr2032_library_spec"] == str(copied_library / "ENERGIZER__CR2032.json")
    assert out["cell_spec_iri"] == ENERGIZER_IRI
    assert out["cell_spec_name"] == "Energizer CR2032"
    assert (out["manufacturer"], out["model"]) == ("Energizer", "CR2032")
    assert out["type_record"] == str(copied_library / "ENERGIZER__CR2032.json")


# ── A cell spec neither library holds ─────────────────────────────────────────


class TestACellSpecNeitherLibraryHolds:
    def test_batch_init_refuses_its_iri_and_creates_nothing(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError) as excinfo:
            init_batch(tmp_path / "batch", UNKNOWN_IRI, 1)
        message = str(excinfo.value)
        assert UNKNOWN_IRI in message
        _assert_names_the_libraries(message, tmp_path)
        assert not (tmp_path / "batch").exists()

    def test_batch_init_names_both_libraries_for_a_name_it_cannot_find(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError) as excinfo:
            init_batch(tmp_path / "batch", "NoSuchManufacturer XYZ999", 1)
        message = str(excinfo.value)
        assert "No cell spec found matching 'NoSuchManufacturer XYZ999'" in message
        _assert_names_the_libraries(message, tmp_path)

    def test_the_batch_init_command_prints_the_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["batch", "init", "batch", "--cell-spec", UNKNOWN_IRI, "--count", "1"])
        assert result.exit_code == 1
        assert f"Error: Cell spec {UNKNOWN_IRI} is not in the cell-spec library" in result.output
        assert not (tmp_path / "batch").exists()

    def test_batch_package_refuses_it_instead_of_writing_a_blank_cell_spec(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        batch_dir = tmp_path / "batch"
        _cell_with_data(batch_dir, init_batch(batch_dir, "Energizer CR2032", 1))
        _point_batch_at(batch_dir, UNKNOWN_IRI)

        with pytest.raises(ValueError) as excinfo:
            package_batch(batch_dir, creators=CREATORS)
        message = str(excinfo.value)
        assert UNKNOWN_IRI in message
        _assert_names_the_libraries(message, tmp_path)
        assert not (batch_dir / "staging").exists()

    def test_the_batch_package_command_prints_the_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        batch_dir = tmp_path / "batch"
        _cell_with_data(batch_dir, init_batch(batch_dir, "Energizer CR2032", 1))
        _point_batch_at(batch_dir, UNKNOWN_IRI)

        result = runner.invoke(
            app, ["batch", "package", "batch", "--creator", "Clark, Simon; SINTEF", "--no-community", "--json"]
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"].startswith(f"Cell spec {UNKNOWN_IRI} is not in the cell-spec library")
        assert not (batch_dir / "staging").exists()

    def test_dataset_process_names_it_and_writes_no_ingest_manifest(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        batch_dir = tmp_path / "batch"
        cell = _cell_with_data(batch_dir, init_batch(batch_dir, "Energizer CR2032", 1, lab="SINTEF"))
        manifest_path = cell / CONTRIBUTION_MANIFEST
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8").replace(ENERGIZER_IRI, UNKNOWN_IRI), encoding="utf-8"
        )

        with pytest.raises(ValueError) as excinfo:
            process_contribution(cell, bundle=False)
        message = str(excinfo.value)
        assert UNKNOWN_IRI in message
        _assert_names_the_libraries(message, tmp_path)
        assert not (cell / INGEST_MANIFEST).exists()

    def test_the_dataset_process_command_puts_it_in_the_json_errors(self, tmp_path: Path, monkeypatch) -> None:
        # --json printed {"ok": false, "errors": []} here: the exception message
        # reached only the console, which --json silences.
        monkeypatch.chdir(tmp_path)
        batch_dir = tmp_path / "batch"
        cell = _cell_with_data(batch_dir, init_batch(batch_dir, "Energizer CR2032", 1, lab="SINTEF"))
        manifest_path = cell / CONTRIBUTION_MANIFEST
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8").replace(ENERGIZER_IRI, UNKNOWN_IRI), encoding="utf-8"
        )
        expected = f"Cell spec {UNKNOWN_IRI} is not in the cell-spec library"

        result = runner.invoke(app, ["dataset", "process", str(cell), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert len(payload["errors"]) == 1 and payload["errors"][0].startswith(expected), payload

        result = runner.invoke(app, ["dataset", "process", str(batch_dir), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert (payload["ok"], payload["fail_count"]) == (False, 1)
        [cell_result] = payload["cells"]
        assert len(cell_result["errors"]) == 1 and cell_result["errors"][0].startswith(expected), payload


# ── The local library ─────────────────────────────────────────────────────────


def _suggested_command(message: str) -> list[str]:
    """The `battinfo ...` command an error message suggests, as arguments for the CLI app."""
    match = re.search(r"`battinfo ([^`]+)`", message)
    assert match, message
    return match.group(1).split()


def test_a_cell_spec_saved_as_the_error_suggests_is_found(tmp_path: Path, monkeypatch) -> None:
    # The error tells the user how to save the cell spec; running that command
    # as written, in the same folder, makes the whole batch path work and
    # writes nothing outside .battinfo/ (no stray src/battinfo/ copy).
    monkeypatch.chdir(tmp_path)
    record = json.loads(DEFAULT_CR2032_LIBRARY_SPEC.read_text(encoding="utf-8"))
    record["specification"].update(id=UNKNOWN_IRI, manufacturer="Acme", model="X1", size_code="R9999")
    (tmp_path / "acme.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        init_batch(tmp_path / "first-try", UNKNOWN_IRI, 1, lab="SINTEF")
    command = _suggested_command(str(excinfo.value))
    assert command[:3] == ["library", "save", "cell-spec"] and "<file>" in command
    saved = runner.invoke(app, [("acme.json" if arg == "<file>" else arg) for arg in command])
    assert saved.exit_code == 0, saved.output
    saved_path = Path(json.loads(saved.stdout)["path"])
    assert saved_path.parent.absolute() == _local_library(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [".battinfo", "acme.json"]

    batch_dir = tmp_path / "batch"
    result = init_batch(batch_dir, UNKNOWN_IRI, 1, lab="SINTEF")
    assert (result["cell_spec_iri"], result["cell_spec_name"]) == (UNKNOWN_IRI, "Acme X1")
    cell = _cell_with_data(batch_dir, result)

    processed = process_contribution(cell, bundle=False)
    assert processed["errors"] == []
    ingest = json.loads((cell / INGEST_MANIFEST).read_text(encoding="utf-8"))
    assert Path(ingest["type_record"]).name == saved_path.name

    package = package_batch(batch_dir, creators=CREATORS)
    bundle = json.loads(Path(package["bundle_path"]).read_text(encoding="utf-8"))
    cell_spec = bundle["cell_spec"]["cell_spec"]
    assert cell_spec["id"] == UNKNOWN_IRI
    assert (cell_spec["manufacturer"]["name"], cell_spec["model"]) == ("Acme", "X1")
