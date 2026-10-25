from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
from typer.testing import CliRunner

from battinfo.bundle import ZENODO_CELL_RECORD_FILENAME, ZenodoCellRecord
from battinfo.cli import app
from battinfo.config import resolve_zenodo_sandbox_token
from battinfo.contribution import (
    _collect_data_files,
    _test_kind_from_path,
    init_batch,
    package_batch,
    push_batch,
)
from battinfo.publication import DEFAULT_PUBLISH_FILENAME, DEFAULT_RO_CRATE_METADATA_FILENAME
from battinfo.zenodo import ZenodoError, upload_zenodo_package

runner = CliRunner()

ENERGIZER_IRI = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
CREATORS = [{"name": "Clark, Simon", "affiliation": "SINTEF"}]


# ── fixtures ───────────────────────────────────────────────────────────────────


def _make_batch(tmp_path: Path, n_cells: int = 2, n_files_per_cell: int = 2) -> Path:
    """Init a batch and populate each cell with real-looking data files."""
    batch_dir = tmp_path / "batch"
    result = init_batch(batch_dir, "Energizer CR2032", n_cells, batch_id="LOT-2025", lab="SINTEF", operator="Ada")

    for cell_info in result["cells"]:
        cell = batch_dir / cell_info["folder"]
        for j in range(1, n_files_per_cell + 1):
            kinds = ["capacity_check", "cycling"]
            kind = kinds[(j - 1) % len(kinds)]
            (cell / f"2025-06-0{j}__{kind}__25degC.csv").write_text(
                f"time,voltage\n0,3.0\n1,{2.9 + 0.01 * j}\n", encoding="utf-8"
            )
        (cell / "2025-06-01__eis__25degC.csv").write_text("freq,Re,Im\n1000,10,5\n", encoding="utf-8")
    return batch_dir


def test_init_batch_rejects_duplicate_serials(tmp_path: Path) -> None:
    # Two cells with the same serial slug to the same folder; init_batch must fail closed
    # instead of silently overwriting the first cell's manifest on disk (mkdir exist_ok).
    with pytest.raises(ValueError, match="unique serial"):
        init_batch(tmp_path / "batch", "Energizer CR2032", 2, serial_numbers=["SN1", "SN1"])


# ── _collect_data_files ────────────────────────────────────────────────────────


class TestCollectDataFiles:
    def test_empty_cell_returns_empty(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        assert _collect_data_files(cell) == []

    def test_csv_at_root_collected(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        f = cell / "test.csv"
        f.write_text("t,V\n", encoding="utf-8")
        pairs = _collect_data_files(cell)
        assert len(pairs) == 1
        assert pairs[0][0] == f
        assert pairs[0][1] is None

    def test_various_extensions_collected(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        for ext in (".csv", ".nda", ".ndax", ".ccs"):
            (cell / f"file{ext}").write_text("x", encoding="utf-8")
        pairs = _collect_data_files(cell)
        assert len(pairs) == 4

    def test_bdf_paired_when_present(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        raw = cell / "test.csv"
        bdf = cell / "test.bdf.parquet"
        raw.write_text("t,V\n", encoding="utf-8")
        bdf.write_bytes(b"PAR1")
        pairs = _collect_data_files(cell)
        assert len(pairs) == 1
        assert pairs[0][0] == raw
        assert pairs[0][1] == bdf

    def test_staging_dir_excluded(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        (cell / "real.csv").write_text("t,V\n", encoding="utf-8")
        staging = cell / "staging"
        staging.mkdir()
        (staging / "dataset-001.csv").write_text("t,V\n", encoding="utf-8")
        pairs = _collect_data_files(cell)
        assert len(pairs) == 1
        assert pairs[0][0].name == "real.csv"

    def test_bdf_parquet_not_treated_as_raw(self, tmp_path: Path) -> None:
        cell = tmp_path / "cell"
        cell.mkdir()
        (cell / "already_converted.bdf.parquet").write_bytes(b"PAR1")
        pairs = _collect_data_files(cell)
        assert pairs == []


# ── _test_kind_from_path ───────────────────────────────────────────────────────


class TestTestKindFromPath:
    @pytest.mark.parametrize(
        "filename,subdir,expected",
        [
            ("2025-06-01__capacity_check__25degC.csv", "timeseries", "capacity_check"),
            ("cycle_life_test.nda", "timeseries", "cycling"),
            ("cycling_001.csv", "timeseries", "cycling"),
            ("rate_capability.csv", "timeseries", "rate_capability"),
            ("ici_test.csv", "timeseries", "ici"),
            ("hppc.csv", "timeseries", "hppc"),
            ("formation_001.csv", "timeseries", "formation"),
            ("any_file.csv", "eis", "eis"),  # subdir override
            ("eis_spectrum.csv", "timeseries", "eis"),
            ("unknown.ccs", "timeseries", "other"),
        ],
    )
    def test_kind_inference(self, filename: str, subdir: str, expected: str) -> None:
        assert _test_kind_from_path(Path(filename), subdir) == expected


# ── package_batch ──────────────────────────────────────────────────────────────


class TestPackageBatch:
    def test_produces_staging_dir(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        assert Path(result["staging_dir"]).exists()

    def test_default_staging_dir_inside_batch(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        assert result["staging_dir"] == str(batch / "staging")

    def test_custom_staging_dir(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        custom = tmp_path / "out"
        result = package_batch(batch, custom, creators=CREATORS)
        assert result["staging_dir"] == str(custom)
        assert custom.exists()

    def test_counts_correct(self, tmp_path: Path) -> None:
        # 2 cells × (2 timeseries + 1 eis) = 6 dataset entries
        batch = _make_batch(tmp_path, n_cells=2, n_files_per_cell=2)
        result = package_batch(batch, creators=CREATORS)
        assert result["cell_count"] == 2
        assert result["entry_count"] == 6

    def test_rejects_duplicate_cell_iri_across_folders(self, tmp_path: Path) -> None:
        # Two cells sharing a serial / cell_name resolve to the same IRI; publishing
        # both would silently overwrite one on ingest, so package_batch must fail closed
        # (the second IRI-minting path the Phase 3 review flagged as a known gap).
        import yaml

        from battinfo.contribution import CONTRIBUTION_MANIFEST

        batch = _make_batch(tmp_path, n_cells=2)
        cell_dirs = sorted(d for d in batch.iterdir() if d.is_dir() and (d / CONTRIBUTION_MANIFEST).exists())
        assert len(cell_dirs) == 2
        m0 = yaml.safe_load((cell_dirs[0] / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8"))
        m1_path = cell_dirs[1] / CONTRIBUTION_MANIFEST
        m1 = yaml.safe_load(m1_path.read_text(encoding="utf-8"))
        m1["cell_iri"] = m0["cell_iri"]  # force the duplicate-serial collision
        m1_path.write_text(yaml.safe_dump(m1), encoding="utf-8")
        with pytest.raises(ValueError, match="same cell IRI"):
            package_batch(batch, creators=CREATORS)

    def test_same_kind_undated_files_get_distinct_test_iris(self, tmp_path: Path) -> None:
        # Multiple same-kind, undated data files in ONE cell must mint distinct test IRIs
        # (the test seed now carries a per-file discriminator). Previously they collapsed
        # onto a single test @id and overwrote each other on ingest, despite a unique cell IRI.
        import re

        batch_dir = tmp_path / "batch"
        result = init_batch(batch_dir, "Energizer CR2032", 1, batch_id="LOT", lab="L", operator="O")
        cell = batch_dir / result["cells"][0]["folder"]
        for n in (1, 2, 3):
            (cell / f"cycling_00{n}.csv").write_text("time,voltage\n0,3.0\n1,2.9\n", encoding="utf-8")
        pkg = package_batch(batch_dir, creators=CREATORS)
        assert pkg["entry_count"] == 3
        bundle_text = (Path(pkg["staging_dir"]) / ZENODO_CELL_RECORD_FILENAME).read_text(encoding="utf-8")
        test_ids = set(re.findall(r"https://w3id\.org/battinfo/id/1001/test/[a-z0-9-]+", bundle_text))
        assert len(test_ids) == 3, "undated same-kind tests in one cell collided onto one IRI"

    def test_bundle_json_parseable(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        record = ZenodoCellRecord.from_path(staging / ZENODO_CELL_RECORD_FILENAME)
        assert record.cell_spec.id == ENERGIZER_IRI
        assert len(record.datasets) == result["entry_count"]

    def test_publish_jsonld_has_graph(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        payload = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
        assert "@graph" in payload
        ids = {n.get("@id") for n in payload["@graph"]}
        assert ENERGIZER_IRI in ids

    def test_placeholder_in_jsonld(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
        assert "ZENODO_RECORD_ID" in text
        assert "file://" not in text

    def test_ro_crate_present(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        crate = json.loads((staging / DEFAULT_RO_CRATE_METADATA_FILENAME).read_text(encoding="utf-8"))
        assert "@graph" in crate

    def test_data_files_canonically_named(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path, n_cells=1, n_files_per_cell=1)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        # Should have dataset-001.csv and dataset-002.csv (1 ts + 1 eis)
        csv_files = list(staging.glob("dataset-*.csv"))
        assert len(csv_files) >= 1

    def test_test_kinds_inferred(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path, n_cells=1, n_files_per_cell=2)
        result = package_batch(batch, creators=CREATORS)
        record = ZenodoCellRecord.from_path(Path(result["staging_dir"]) / ZENODO_CELL_RECORD_FILENAME)
        kinds = {e.test.test_type for e in record.datasets}
        assert "capacity_check" in kinds
        assert "eis" in kinds

    def test_cell_instances_populated(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path, n_cells=2, n_files_per_cell=1)
        result = package_batch(batch, creators=CREATORS)
        record = ZenodoCellRecord.from_path(Path(result["staging_dir"]) / ZENODO_CELL_RECORD_FILENAME)
        for entry in record.datasets:
            assert len(entry.cell_instances) == 1
            assert entry.cell_instances[0].id is not None

    def test_no_data_files_raises(self, tmp_path: Path) -> None:
        batch_dir = tmp_path / "batch"
        init_batch(batch_dir, "Energizer CR2032", 1)
        with pytest.raises(ValueError, match="No raw data files"):
            package_batch(batch_dir, creators=CREATORS)

    def test_empty_creators_raises(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        with pytest.raises(ValueError, match="creators"):
            package_batch(batch, creators=[])

    def test_bdf_files_included_when_present(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path, n_cells=1, n_files_per_cell=1)
        cell = next(d for d in sorted(batch.iterdir()) if d.is_dir())
        bdf = cell / "2025-06-01__capacity_check__25degC.bdf.parquet"
        bdf.write_bytes(b"PAR1")
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        bdf_files = list(staging.glob("*.bdf.parquet"))
        assert len(bdf_files) >= 1

    def test_packaged_batch_names_no_local_path(self, tmp_path: Path) -> None:
        # The package goes to Zenodo: no file: URL, and no absolute path of the batch
        # (which holds the user name), in any file it writes.
        batch = _make_batch(tmp_path)
        result = package_batch(batch, creators=CREATORS)
        staging = Path(result["staging_dir"])
        local = {
            form
            for path in (batch, batch.resolve())
            for form in (str(path), path.as_posix(), json.dumps(str(path))[1:-1])
        }
        texts = {
            name: (staging / name).read_text(encoding="utf-8")
            for name in (ZENODO_CELL_RECORD_FILENAME, DEFAULT_PUBLISH_FILENAME, DEFAULT_RO_CRATE_METADATA_FILENAME)
        }
        for name, text in texts.items():
            assert "file:" not in text.lower(), name
            assert not [path for path in local if path in text], name

        # Each dataset points at the Zenodo record instead, which the upload fills in.
        bundle = json.loads(texts[ZENODO_CELL_RECORD_FILENAME])
        for entry in bundle["datasets"]:
            assert entry["dataset"]["dataset"]["access_url"] == "https://zenodo.org/records/ZENODO_RECORD_ID"

    def test_dropping_the_local_urls_keeps_the_iris(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The dataset IRI is seeded from the folder's name, so the local URLs go only after
        # the IRIs are minted: the same batch packaged with them kept gives the same IRIs.
        import re

        from battinfo import contribution

        batch = _make_batch(tmp_path)

        def iris(staging: Path) -> list[str]:
            text = (staging / ZENODO_CELL_RECORD_FILENAME).read_text(encoding="utf-8")
            return sorted(set(re.findall(r"https://w3id\.org/battinfo/id/1001/(?:cell|test|dataset)/[a-z0-9-]+", text)))

        cleaned = iris(Path(package_batch(batch, tmp_path / "cleaned", creators=CREATORS)["staging_dir"]))
        monkeypatch.setattr(contribution, "_without_local_urls", lambda record: record)
        kept_staging = Path(package_batch(batch, tmp_path / "kept", creators=CREATORS)["staging_dir"])

        assert "file:" in (kept_staging / ZENODO_CELL_RECORD_FILENAME).read_text(encoding="utf-8")
        assert cleaned and cleaned == iris(kept_staging)


# ── CLI: batch package ─────────────────────────────────────────────────────────


class TestBatchPackageCli:
    def _make_batch(self, tmp_path: Path) -> Path:
        batch = _make_batch(tmp_path, n_cells=2, n_files_per_cell=1)
        return batch

    def test_basic_invocation(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--creator",
                "Clark, Simon",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Package built" in result.output
        assert (batch / "staging").is_dir()

    def test_creator_with_affiliation(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--creator",
                "Clark, Simon; SINTEF",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_multiple_creators(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--creator",
                "Clark, Simon",
                "--creator",
                "Smith, Jane",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_custom_staging_dir(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        out = tmp_path / "output"
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--staging",
                str(out),
                "--creator",
                "Clark, Simon",
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.is_dir()

    def test_no_data_fails(self, tmp_path: Path) -> None:
        batch = tmp_path / "batch"
        init_batch(batch, "Energizer CR2032", 1)
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--creator",
                "Clark, Simon",
            ],
        )
        assert result.exit_code != 0

    def test_shows_upload_hint(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        result = runner.invoke(
            app,
            [
                "batch",
                "package",
                str(batch),
                "--creator",
                "Clark, Simon",
            ],
        )
        assert "batch upload" in result.output


# ── Uploads go only to the Zenodo sandbox in this release ──────────────────────


def _one_line(text: str) -> str:
    return " ".join(text.split())


class TestSandboxOnlyUploads:
    def test_batch_upload_refuses_zenodo_org(self, tmp_path: Path) -> None:
        staging = Path(package_batch(_make_batch(tmp_path), creators=CREATORS)["staging_dir"])
        with patch("battinfo.zenodo.ZenodoClient") as client:
            result = runner.invoke(
                app,
                [
                    "batch",
                    "upload",
                    str(staging),
                    "--token",
                    "tok",
                    "--creator",
                    "Clark, Simon",
                ],
            )
        assert result.exit_code == 1
        assert "only to the Zenodo sandbox" in _one_line(result.output)
        client.assert_not_called()
        assert "ZENODO_RECORD_ID" in (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")

    def test_push_refuses_zenodo_org_before_it_moves_a_file(self, tmp_path: Path) -> None:
        folder = tmp_path / "flat"
        folder.mkdir()
        for n in (1, 2):
            (folder / f"cell{n}_cycling.csv").write_text("time,voltage\n0,3.0\n", encoding="utf-8")
        before = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))
        with patch("battinfo.zenodo.ZenodoClient") as client:
            result = runner.invoke(
                app,
                [
                    "push",
                    str(folder),
                    "--cell-spec",
                    "Energizer CR2032",
                    "--creator",
                    "Clark, Simon",
                    "--token",
                    "tok",
                    "--yes",
                ],
            )
        assert result.exit_code == 1
        assert "only to the Zenodo sandbox" in _one_line(result.output)
        client.assert_not_called()
        assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == before

    def test_push_batch_refuses_zenodo_org_before_it_packages(self, tmp_path: Path) -> None:
        batch = _make_batch(tmp_path)
        with patch("battinfo.zenodo.ZenodoClient") as client:
            with pytest.raises(ValueError, match="only to the Zenodo sandbox"):
                push_batch(batch, creators=CREATORS, zenodo_token="tok")
        client.assert_not_called()
        assert not (batch / "staging").exists()

    @pytest.mark.parametrize(
        "args",
        [
            ["batch", "upload", "{folder}", "--token", "tok", "--creator", "Clark, Simon"],
            ["push", "{folder}", "--cell-spec", "Energizer CR2032", "--creator", "Clark, Simon", "--token", "tok"],
        ],
        ids=["batch-upload", "push"],
    )
    def test_the_commands_refuse_zenodo_org_before_they_call_the_upload(
        self, tmp_path: Path, user_config: Path, args: list[str]
    ) -> None:
        # upload_zenodo_package() and push_batch() refuse zenodo.org too. Patched out
        # here, so the refusal must come from the commands' own check.
        folder = tmp_path / "data"
        folder.mkdir()
        with (
            patch("battinfo.zenodo.upload_zenodo_package") as upload,
            patch("battinfo.contribution.push_batch") as push,
        ):
            result = runner.invoke(app, [arg.format(folder=folder) for arg in args])
        assert result.exit_code == 1
        assert "only to the Zenodo sandbox" in _one_line(result.output)
        upload.assert_not_called()
        push.assert_not_called()


# ── The batch path sends a sandbox token to the sandbox ────────────────────────


@pytest.fixture()
def user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """~/.battinfo/config.yaml in the test's folder (absent until written), with no Zenodo token exported."""
    path = tmp_path / "home" / ".battinfo" / "config.yaml"
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", path)
    for name in ("ZENODO_API_TOKEN", "ZENODO_SANDBOX_TOKEN", "ZENODO_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return path


def _store(path: Path, **values: str) -> None:
    """Write *values* to the config file, as `battinfo config set` would."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}: {value}\n" for key, value in values.items()), encoding="utf-8")


UPLOADED = {"record_id": 1, "doi": "10.5072/zenodo.1", "deposit_url": "u", "uploaded_files": [], "published": False}
PUSHED = {"status": "draft", "cells": 1, "files": 1, "staging_dir": "s", "zenodo_url": "u"}


class TestSandboxToken:
    """A zenodo.org token, stored with `battinfo config set zenodo_token` or exported, never goes to the sandbox."""

    @pytest.mark.parametrize(
        ("argument", "exported", "stored", "expected"),
        [
            ("sbx-arg", "sbx-env", "sbx-config", "sbx-arg"),
            (None, "sbx-env", "sbx-config", "sbx-env"),
            (None, None, "sbx-config", "sbx-config"),
            (None, None, None, None),
        ],
        ids=["argument", "environment", "config", "none"],
    )
    def test_the_sandbox_token_comes_from_the_argument_then_the_environment_then_the_config(
        self,
        user_config: Path,
        monkeypatch: pytest.MonkeyPatch,
        argument: str | None,
        exported: str | None,
        stored: str | None,
        expected: str | None,
    ) -> None:
        _store(user_config, zenodo_token="prod-config", **({"zenodo_sandbox_token": stored} if stored else {}))
        monkeypatch.setenv("ZENODO_API_TOKEN", "prod-env")
        if exported:
            monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", exported)
        assert resolve_zenodo_sandbox_token(argument) == expected

    @pytest.mark.parametrize("source", ["environment", "config"])
    @pytest.mark.parametrize("command", ["batch-upload", "push"])
    def test_the_commands_send_the_sandbox_token(
        self, tmp_path: Path, user_config: Path, monkeypatch: pytest.MonkeyPatch, command: str, source: str
    ) -> None:
        _store(
            user_config, zenodo_token="prod-config", **({"zenodo_sandbox_token": "sbx"} if source == "config" else {})
        )
        monkeypatch.setenv("ZENODO_API_TOKEN", "prod-env")
        if source == "environment":
            monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "sbx")
        folder = tmp_path / "data"
        folder.mkdir()
        with (
            patch("battinfo.zenodo.upload_zenodo_package", return_value=UPLOADED) as upload,
            patch("battinfo.contribution.push_batch", return_value=PUSHED) as push,
        ):
            result = runner.invoke(app, _sandbox_command(command, folder))
        assert result.exit_code == 0, result.output
        if command == "batch-upload":
            assert upload.call_args.kwargs["token"] == "sbx"
        else:
            assert push.call_args.kwargs["zenodo_token"] == "sbx"

    @pytest.mark.parametrize("command", ["batch-upload", "push"])
    def test_the_commands_stop_without_a_sandbox_token(
        self, tmp_path: Path, user_config: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        _store(user_config, zenodo_token="prod-config")
        monkeypatch.setenv("ZENODO_API_TOKEN", "prod-env")
        folder = tmp_path / "data"
        folder.mkdir()
        with (
            patch("battinfo.zenodo.upload_zenodo_package") as upload,
            patch("battinfo.contribution.push_batch") as push,
        ):
            result = runner.invoke(app, _sandbox_command(command, folder))
        assert result.exit_code == 1
        text = _one_line(result.output)
        assert "Zenodo sandbox token required" in text and "zenodo_sandbox_token" in text
        assert "prod-" not in text
        upload.assert_not_called()
        push.assert_not_called()

    def test_upload_zenodo_package_reads_the_sandbox_token(
        self, tmp_path: Path, user_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ZENODO_API_TOKEN", "prod-env")
        staging = tmp_path / "staging"
        staging.mkdir()
        with patch("battinfo.zenodo.ZenodoClient") as client:
            with pytest.raises(ZenodoError, match="No Zenodo sandbox token"):
                upload_zenodo_package(staging, CREATORS, sandbox=True)
            client.assert_not_called()

            monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "sbx-env")
            with pytest.raises(FileNotFoundError):  # the staging folder holds no package
                upload_zenodo_package(staging, CREATORS, sandbox=True)
        client.assert_called_once_with(token="sbx-env", sandbox=True)


def _sandbox_command(command: str, folder: Path) -> list[str]:
    """A --sandbox run of *command* on *folder* that gives no --token."""
    if command == "batch-upload":
        return ["batch", "upload", str(folder), "--sandbox", "--creator", "Clark, Simon", "--json"]
    return ["push", str(folder), "--cell-spec", "Energizer CR2032", "--creator", "Clark, Simon", "--sandbox", "--json"]
