from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo._fs_guard import UnsafeDeleteError
from battinfo.api import build_cell_spec_library_rdf

MINIMAL_SPEC = ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_cell_spec_library_rdf_from_descriptor(tmp_path: Path) -> None:
    input_dir = tmp_path / "cell-spec"
    output_jsonld_dir = tmp_path / "library-rdf" / "cell-spec"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-spec.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-spec.index.json"

    input_dir.mkdir(parents=True)
    descriptor = _load_json(ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json")
    (input_dir / "minimal.json").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".tools" / "build" / "build_cell_spec_library_rdf.py"),
            "--input-dir",
            str(input_dir),
            "--output-jsonld-dir",
            str(output_jsonld_dir),
            "--aggregate-jsonld",
            str(aggregate_jsonld),
            "--manifest-json",
            str(manifest_json),
            "--clean-output",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    record_jsonld = _load_json(output_jsonld_dir / "minimal.jsonld")
    aggregate_payload = _load_json(aggregate_jsonld)
    manifest_payload = _load_json(manifest_json)

    expected_id = descriptor["cell_spec"]["id"]
    expected_manufacturer = descriptor["cell_spec"]["manufacturer"]["name"]
    expected_model = descriptor["cell_spec"]["model"]

    assert "@graph" in record_jsonld
    assert record_jsonld["@graph"][0]["@id"] == expected_id

    assert aggregate_payload["@graph"]
    assert aggregate_payload["@graph"][0]["@id"] == expected_id

    assert manifest_payload["entry_count"] == 1
    assert manifest_payload["entries"][0]["id"] == expected_id
    assert manifest_payload["entries"][0]["manufacturer"] == expected_manufacturer
    assert manifest_payload["entries"][0]["model"] == expected_model


def _library(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(MINIMAL_SPEC, folder / name)
    return folder


def _build(input_dir: Path, output_dir: Path, tmp_path: Path, **kwargs: object) -> dict:
    return build_cell_spec_library_rdf(
        input_dir=input_dir,
        output_jsonld_dir=output_dir,
        aggregate_jsonld=tmp_path / "ontology" / "cell-spec.jsonld",
        manifest_json=tmp_path / "library-rdf" / "cell-spec.index.json",
        **kwargs,
    )


def test_clean_output_into_the_input_folder_is_refused_and_keeps_its_files(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib", "ENERGIZER__CR2032.json")
    (library / "my-notes.json").write_text('{"note": "mine"}', encoding="utf-8")

    with pytest.raises(UnsafeDeleteError, match="which this operation reads"):
        _build(library, library, tmp_path, clean_output=True)

    assert sorted(path.name for path in library.iterdir()) == ["ENERGIZER__CR2032.json", "my-notes.json"]


@pytest.mark.parametrize("output", ["rdf", ".."], ids=["inside", "holding"])
def test_clean_output_refuses_an_output_folder_inside_or_around_the_input_folder(tmp_path: Path, output: str) -> None:
    library = _library(tmp_path / "lib" / "cell-spec", "ENERGIZER__CR2032.json")

    with pytest.raises(UnsafeDeleteError, match="which this operation reads"):
        _build(library, library / output, tmp_path, clean_output=True)

    assert (library / "ENERGIZER__CR2032.json").exists()
    assert not (library / "rdf").exists()


def test_clean_output_deletes_only_the_outputs_the_previous_build_listed(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib", "a.json", "b.json")
    output = tmp_path / "rdf"
    _build(library, output, tmp_path)
    assert sorted(path.name for path in output.iterdir()) == ["a.jsonld", "b.jsonld"]
    (output / "notes.json").write_text("{}", encoding="utf-8")
    (output / "mine.jsonld").write_text("{}", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere.jsonld"
    elsewhere.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "library-rdf" / "cell-spec.index.json"
    listed = _load_json(manifest)
    listed["entries"] += [{"output_jsonld": str(elsewhere)}, {"output_jsonld": str(output / ".." / "elsewhere.jsonld")}]
    manifest.write_text(json.dumps(listed), encoding="utf-8")
    (library / "b.json").unlink()

    result = _build(library, output, tmp_path, clean_output=True)

    assert result["entry_count"] == 1
    assert sorted(path.name for path in output.iterdir()) == ["a.jsonld", "mine.jsonld", "notes.json"]
    assert elsewhere.exists()


def _library_with_an_unversioned_descriptor(tmp_path: Path) -> Path:
    """A library whose a.json maps and whose b.json is a cell descriptor without schema_version."""
    library = _library(tmp_path / "lib", "a.json")
    descriptor = _load_json(ROOT / "src" / "battinfo" / "data" / "library" / "cell-spec" / "A123__ANR26650M1-B.json")
    del descriptor["schema_version"]
    (library / "b.json").write_text(json.dumps(descriptor), encoding="utf-8")
    return library


def test_build_names_the_file_of_a_descriptor_it_cannot_map(tmp_path: Path) -> None:
    library = _library_with_an_unversioned_descriptor(tmp_path)

    with pytest.raises(ValueError) as raised:
        _build(library, tmp_path / "rdf", tmp_path)

    message = str(raised.value)
    assert str(library / "b.json") in message, message
    assert "schema_version" in message


def test_library_build_rdf_command_names_the_file_it_cannot_map(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from battinfo.cli import app

    library = _library_with_an_unversioned_descriptor(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "library",
            "build-rdf",
            "--input-dir",
            str(library),
            "--output-jsonld-dir",
            str(tmp_path / "rdf"),
            "--aggregate-jsonld",
            str(tmp_path / "ontology" / "cell-spec.jsonld"),
            "--manifest-json",
            str(tmp_path / "library-rdf" / "cell-spec.index.json"),
        ],
    )

    assert result.exit_code == 1, result.output
    assert "b.json" in result.output and "schema_version" in result.output
