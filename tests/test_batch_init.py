from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
import yaml
from typer.testing import CliRunner

from battinfo.cli import app
from battinfo.contribution import (
    BATCH_MANIFEST,
    CONTRIBUTION_MANIFEST,
    _resolve_cell_spec_for_batch,
    add_to_batch,
    init_batch,
    load_batch_manifest,
)

runner = CliRunner()

ENERGIZER_IRI = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"


# ── _resolve_cell_spec_for_batch ───────────────────────────────────────────────

class TestResolveCellSpecification:
    def test_direct_iri_passthrough(self) -> None:
        iri, name, mfr, model = _resolve_cell_spec_for_batch(ENERGIZER_IRI)
        assert iri == ENERGIZER_IRI
        assert mfr == "Energizer"
        assert model == "CR2032"

    def test_name_resolves_to_iri(self) -> None:
        iri, name, mfr, model = _resolve_cell_spec_for_batch("Energizer CR2032")
        assert iri == ENERGIZER_IRI
        assert "Energizer" in name
        assert "CR2032" in name
        assert mfr == "Energizer"
        assert model == "CR2032"

    def test_slash_separator_accepted(self) -> None:
        iri, _, _, _ = _resolve_cell_spec_for_batch("Energizer/CR2032")
        assert iri == ENERGIZER_IRI

    def test_fuzzy_manufacturer(self) -> None:
        iri, _, _, _ = _resolve_cell_spec_for_batch("Enegizer CR2032")
        assert iri == ENERGIZER_IRI

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="No cell type found"):
            _resolve_cell_spec_for_batch("NoSuchManufacturer XYZ999")


# ── init_batch ─────────────────────────────────────────────────────────────────

def _first_cell(result: dict, batch_dir: Path) -> Path:
    """Return the Path to the first cell folder from an init_batch result."""
    return batch_dir / result["cells"][0]["folder"]


class TestInitBatch:
    def test_basic_scaffold(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 3)
        root = Path(result["output_dir"])
        assert root.exists()
        assert result["cell_spec_iri"] == ENERGIZER_IRI
        assert result["count"] == 3
        assert len(result["cells"]) == 3

    def test_folder_names_include_manufacturer_model_cell_shortid(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 2, batch_id="LOT-X")
        folders = [c["folder"] for c in result["cells"]]
        iris = [c["cell_iri"] for c in result["cells"]]
        # e.g. "energizer-CR2032-azcdbd"
        assert all("energizer" in f for f in folders)
        assert all("CR2032" in f for f in folders)
        # short ID is the first 6 chars of the cell instance IRI uid (no hyphens)
        for folder, iri in zip(folders, iris):
            short_id = iri.rstrip("/").split("/")[-1].replace("-", "")[:6]
            assert folder.endswith(short_id)
        # folders are all unique
        assert len(set(folders)) == 2

    def test_cell_iris_written_to_battinfo_yaml(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 2, batch_id="LOT-X")
        for cell_info in result["cells"]:
            cell_dir = tmp_path / "batch" / cell_info["folder"]
            text = (cell_dir / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
            assert cell_info["cell_iri"] in text

    def test_creates_cell_subdirs(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 2)
        root = tmp_path / "batch"
        for cell in result["cells"]:
            assert (root / cell["folder"]).is_dir()
        assert len(list(root.iterdir())) == 3  # 2 cells + batch.yaml

    def test_cell_folder_and_photos_created(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 1)
        cell = _first_cell(result, tmp_path / "batch")
        assert cell.is_dir()
        assert (cell / "photos").is_dir()

    def test_battinfo_yaml_written(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 2)
        for cell_info in result["cells"]:
            manifest = tmp_path / "batch" / cell_info["folder"] / CONTRIBUTION_MANIFEST
            assert manifest.exists()
            assert ENERGIZER_IRI in manifest.read_text(encoding="utf-8")

    def test_batch_yaml_written(self, tmp_path: Path) -> None:
        init_batch(tmp_path / "batch", "Energizer CR2032", 2, batch_id="B001")
        manifest = tmp_path / "batch" / BATCH_MANIFEST
        assert manifest.exists()
        text = manifest.read_text(encoding="utf-8")
        assert "B001" in text
        assert ENERGIZER_IRI in text

    def test_batch_yaml_stores_manufacturer_and_model(self, tmp_path: Path) -> None:
        init_batch(tmp_path / "batch", "Energizer CR2032", 1)
        data = yaml.safe_load((tmp_path / "batch" / BATCH_MANIFEST).read_text(encoding="utf-8"))
        assert data["manufacturer"] == "Energizer"
        assert data["model"] == "CR2032"

    def test_serial_numbers_as_folder_names(self, tmp_path: Path) -> None:
        init_batch(
            tmp_path / "batch", "Energizer CR2032", 2,
            serial_numbers=["SN-A01", "SN-A02"],
        )
        assert (tmp_path / "batch" / "sn-a01").is_dir()
        assert (tmp_path / "batch" / "sn-a02").is_dir()

    def test_serial_numbers_in_manifest(self, tmp_path: Path) -> None:
        result = init_batch(
            tmp_path / "batch", "Energizer CR2032", 2,
            serial_numbers=["SN-001", "SN-002"],
        )
        folder = result["cells"][0]["folder"]
        text = (tmp_path / "batch" / folder / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "SN-001" in text

    def test_pre_assigned_iris(self, tmp_path: Path) -> None:
        ci_iri = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
        result = init_batch(
            tmp_path / "batch", "Energizer CR2032", 1,
            cell_iris=[ci_iri],
        )
        cell = _first_cell(result, tmp_path / "batch")
        assert ci_iri in (cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_operator_in_manifest(self, tmp_path: Path) -> None:
        result = init_batch(
            tmp_path / "batch", "Energizer CR2032", 1,
            lab="SINTEF", operator="Ada Lovelace",
        )
        text = _first_cell(result, tmp_path / "batch") / CONTRIBUTION_MANIFEST
        content = text.read_text(encoding="utf-8")
        assert "SINTEF" in content
        assert "Ada Lovelace" in content
        assert "operator" in content

    def test_project_in_manifest(self, tmp_path: Path) -> None:
        result = init_batch(
            tmp_path / "batch", "Energizer CR2032", 1,
            project="SolidBat-2025",
        )
        text = (_first_cell(result, tmp_path / "batch") / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "SolidBat-2025" in text
        assert "project" in text

    def test_cell_folder_created(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 1)
        cell = _first_cell(result, tmp_path / "batch")
        assert cell.is_dir()
        assert (cell / "battinfo.yaml").is_file()

    def test_batch_id_in_cell_manifest(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", "Energizer CR2032", 1, batch_id="LOT-2025")
        text = (_first_cell(result, tmp_path / "batch") / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "LOT-2025" in text

    def test_existing_dir_raises_without_force(self, tmp_path: Path) -> None:
        dest = tmp_path / "batch"
        dest.mkdir()
        with pytest.raises(FileExistsError):
            init_batch(dest, "Energizer CR2032", 1)

    def test_overwrite_flag(self, tmp_path: Path) -> None:
        dest = tmp_path / "batch"
        dest.mkdir()
        result = init_batch(dest, "Energizer CR2032", 1, overwrite=True)
        assert result["count"] == 1

    def test_iris_length_mismatch_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cell_iris length"):
            init_batch(
                tmp_path / "batch", "Energizer CR2032", 2,
                cell_iris=["https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"],
            )

    def test_serials_length_mismatch_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="serial_numbers length"):
            init_batch(
                tmp_path / "batch", "Energizer CR2032", 3,
                serial_numbers=["SN-1", "SN-2"],
            )

    def test_direct_iri_uses_library_for_folder_names(self, tmp_path: Path) -> None:
        result = init_batch(tmp_path / "batch", ENERGIZER_IRI, 1)
        assert result["cell_spec_iri"] == ENERGIZER_IRI
        folder = result["cells"][0]["folder"]
        assert "energizer" in folder
        assert "CR2032" in folder  # model case preserved


# ── CLI ────────────────────────────────────────────────────────────────────────

def _first_cell_dir(tmp_path: Path) -> Path:
    """Find the first cell directory (not batch.yaml) in a batch root."""
    batch = tmp_path / "batch"
    return next(d for d in sorted(batch.iterdir()) if d.is_dir())


class TestBatchInitCli:
    def test_basic_invocation(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "batch", "init",
            str(tmp_path / "batch"),
            "--cell-spec", "Energizer CR2032",
            "--count", "2",
        ])
        assert result.exit_code == 0, result.output
        assert "Initialised batch" in result.output
        cell_dirs = [d for d in (tmp_path / "batch").iterdir() if d.is_dir()]
        assert len(cell_dirs) == 2
        assert all("energizer" in d.name for d in cell_dirs)

    def test_with_batch_id_and_lab(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "batch", "init",
            str(tmp_path / "batch"),
            "--cell-spec", "Energizer CR2032",
            "--count", "3",
            "--batch-id", "B2025-06",
            "--lab", "SINTEF",
            "--operator", "Test User",
            "--project", "SolidBat-2025",
        ])
        assert result.exit_code == 0, result.output
        cell = _first_cell_dir(tmp_path)
        text = (cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "B2025-06" in text
        assert "SINTEF" in text
        assert "Test User" in text
        assert "SolidBat-2025" in text

    def test_cell_folder_via_cli(self, tmp_path: Path) -> None:
        runner.invoke(app, [
            "batch", "init", str(tmp_path / "batch"),
            "--cell-spec", "Energizer CR2032", "--count", "1",
        ])
        cell = _first_cell_dir(tmp_path)
        assert cell.is_dir()
        assert (cell / "battinfo.yaml").is_file()

    def test_with_serials(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "batch", "init",
            str(tmp_path / "batch"),
            "--cell-spec", "Energizer CR2032",
            "--count", "2",
            "--serials", "SN-01,SN-02",
        ])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "batch" / "sn-01").is_dir()
        assert (tmp_path / "batch" / "sn-02").is_dir()

    def test_with_pre_assigned_iris(self, tmp_path: Path) -> None:
        ci1 = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
        ci2 = "https://w3id.org/battinfo/cell/1111-2222-3333-4444"
        result = runner.invoke(app, [
            "batch", "init",
            str(tmp_path / "batch"),
            "--cell-spec", "Energizer CR2032",
            "--count", "2",
            "--iris", f"{ci1},{ci2}",
        ])
        assert result.exit_code == 0, result.output
        # Find the folder whose short_id matches ci1's short_id
        ci1_short = ci1.rstrip("/").split("/")[-1].replace("-", "")[:6]
        ci1_dir = next(d for d in _cell_dirs(tmp_path / "batch") if ci1_short in d.name)
        assert ci1 in (ci1_dir / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_unknown_cell_spec_exits_with_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "batch", "init",
            str(tmp_path / "batch"),
            "--cell-spec", "NoSuchBrand XYZ999",
            "--count", "1",
        ])
        assert result.exit_code != 0

    def test_existing_dir_exits_with_error(self, tmp_path: Path) -> None:
        dest = tmp_path / "batch"
        dest.mkdir()
        result = runner.invoke(app, [
            "batch", "init", str(dest),
            "--cell-spec", "Energizer CR2032", "--count", "1",
        ])
        assert result.exit_code != 0

    def test_force_flag_overwrites(self, tmp_path: Path) -> None:
        dest = tmp_path / "batch"
        dest.mkdir()
        result = runner.invoke(app, [
            "batch", "init", str(dest),
            "--cell-spec", "Energizer CR2032", "--count", "1",
            "--force",
        ])
        assert result.exit_code == 0, result.output


# ── add_to_batch ───────────────────────────────────────────────────────────────

def _cell_dirs(batch_dir: Path) -> list[Path]:
    """Return sorted list of cell directories (excludes files like batch.yaml)."""
    return sorted(d for d in batch_dir.iterdir() if d.is_dir())


class TestAddToBatch:
    def _init(self, tmp_path: Path, count: int = 2, **kw) -> Path:
        batch_dir = tmp_path / "batch"
        init_batch(batch_dir, "Energizer CR2032", count, **kw)
        return batch_dir

    def test_adds_new_folders_with_cell_short_ids(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        result = add_to_batch(d, 3)
        new_folders = [c["folder"] for c in result["new_cells"]]
        new_iris = [c["cell_iri"] for c in result["new_cells"]]
        assert len(new_folders) == 3
        for folder, iri in zip(new_folders, new_iris):
            assert (d / folder).is_dir()
            short_id = iri.rstrip("/").split("/")[-1].replace("-", "")[:6]
            assert folder.endswith(short_id)
        assert len(_cell_dirs(d)) == 5

    def test_total_count_returned(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        result = add_to_batch(d, 3)
        assert result["total_count"] == 5
        assert result["added"] == 3

    def test_batch_yaml_count_updated(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        add_to_batch(d, 3)
        assert load_batch_manifest(d)["count"] == 5

    def test_new_cell_folder_created(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        result = add_to_batch(d, 1)
        cell = d / result["new_cells"][0]["folder"]
        assert cell.is_dir()
        assert (cell / "battinfo.yaml").is_file()

    def test_inherits_cell_spec_from_batch_yaml(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        result = add_to_batch(d, 1)
        assert result["cell_spec_iri"] == ENERGIZER_IRI
        cell = d / result["new_cells"][0]["folder"]
        assert ENERGIZER_IRI in (cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_inherits_lab_and_operator(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1, lab="SINTEF", operator="Ada")
        result = add_to_batch(d, 1)
        cell = d / result["new_cells"][0]["folder"]
        text = (cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "SINTEF" in text
        assert "Ada" in text

    def test_override_operator_for_new_cells(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1, operator="Original")
        orig_folders = {c.name for c in _cell_dirs(d)}
        result = add_to_batch(d, 1, operator="NewPerson")
        new_cell = d / result["new_cells"][0]["folder"]
        orig_cell = d / next(iter(orig_folders))
        assert "Original" in (orig_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "NewPerson" in (new_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "NewPerson" not in (orig_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_override_batch_id_for_new_cells(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1, batch_id="LOT-A")
        orig_folders = {c.name for c in _cell_dirs(d)}
        result = add_to_batch(d, 1, batch_id="LOT-B")
        new_cell = d / result["new_cells"][0]["folder"]
        orig_cell = d / next(iter(orig_folders))
        assert "LOT-A" in (orig_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "LOT-B" in (new_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        assert "LOT-B" not in (orig_cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_serial_numbers_as_folder_names(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        add_to_batch(d, 2, serial_numbers=["SN-NEW-01", "SN-NEW-02"])
        assert (d / "sn-new-01").is_dir()
        assert (d / "sn-new-02").is_dir()

    def test_pre_assigned_iris(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        ci_iri = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
        result = add_to_batch(d, 1, cell_iris=[ci_iri])
        cell = d / result["new_cells"][0]["folder"]
        assert ci_iri in (cell / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_multiple_adds_accumulate(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        add_to_batch(d, 2)
        add_to_batch(d, 2)
        assert load_batch_manifest(d)["count"] == 6
        assert len(_cell_dirs(d)) == 6

    def test_no_batch_yaml_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="batch.yaml"):
            add_to_batch(empty, 1)

    def test_existing_folder_collision_raises(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        # Add one cell with serial "SN-A", then try to add another with the same serial
        add_to_batch(d, 1, serial_numbers=["SN-A"])
        with pytest.raises(FileExistsError):
            add_to_batch(d, 1, serial_numbers=["SN-A"])

    def test_iris_length_mismatch_raises(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        with pytest.raises(ValueError, match="cell_iris length"):
            add_to_batch(d, 2, cell_iris=["https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"])

    def test_serials_length_mismatch_raises(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        with pytest.raises(ValueError, match="serial_numbers length"):
            add_to_batch(d, 3, serial_numbers=["SN-1", "SN-2"])


# ── batch add CLI ──────────────────────────────────────────────────────────────

class TestBatchAddCli:
    def _init(self, tmp_path: Path, count: int = 2) -> Path:
        batch_dir = tmp_path / "batch"
        runner.invoke(app, [
            "batch", "init", str(batch_dir),
            "--cell-spec", "Energizer CR2032",
            "--count", str(count),
            "--lab", "SINTEF",
        ])
        return batch_dir

    def test_basic_add(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        result = runner.invoke(app, [
            "batch", "add", str(d), "--count", "3",
        ])
        assert result.exit_code == 0, result.output
        assert "Added 3 cell(s)" in result.output
        assert "New total  : 5" in result.output
        assert len(_cell_dirs(d)) == 5

    def test_add_with_override_operator(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        before = {c.name for c in _cell_dirs(d)}
        result = runner.invoke(app, [
            "batch", "add", str(d), "--count", "1",
            "--operator", "Bob",
        ])
        assert result.exit_code == 0, result.output
        new_cells = [c for c in _cell_dirs(d) if c.name not in before]
        assert len(new_cells) == 1
        assert "Bob" in (new_cells[0] / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")

    def test_add_with_serials(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 1)
        result = runner.invoke(app, [
            "batch", "add", str(d), "--count", "2",
            "--serials", "SN-X01,SN-X02",
        ])
        assert result.exit_code == 0, result.output
        assert (d / "sn-x01").is_dir()
        assert (d / "sn-x02").is_dir()

    def test_batch_yaml_count_updated_via_cli(self, tmp_path: Path) -> None:
        d = self._init(tmp_path, 2)
        runner.invoke(app, ["batch", "add", str(d), "--count", "3"])
        manifest = load_batch_manifest(d)
        assert manifest["count"] == 5

    def test_nonexistent_dir_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "batch", "add", str(tmp_path / "nonexistent"), "--count", "1",
        ])
        assert result.exit_code != 0
