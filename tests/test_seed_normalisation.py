"""One seed normaliser for every identity seed, and chemistry by its vocabulary key.

Seed rules freeze with the first PyPI release. A free-text identity field
(manufacturer, model, name, serial, batch, label, size code) enters a seed
stripped, with each run of whitespace (no-break and other non-space
whitespace included) as one space, in Unicode NFC, and with its case kept.
A locator (a URL or a path) gets NFC alone: whitespace in it is part of the
location. A cell spec's chemistry enters as its vocabulary key, with an alias
resolved, so Li-ion, li-ion and LI-ION are one cell spec. A cell spec saved
under the seeds of before 0.8.0 keeps its IRI when it is saved again.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import api  # noqa: E402
from battinfo._workspace import Workspace  # noqa: E402
from battinfo.bundle import SCHEMA_VERSION, Cell, CellSpec, Dataset, Test  # noqa: E402
from battinfo.entities import (  # noqa: E402
    cell_instance_identity_seed,
    chemistry_seed_key,
    seed_text,
    stable_uid,
)

NFC_NAME = unicodedata.normalize("NFC", "Société Bleue")
NFD_NAME = unicodedata.normalize("NFD", "Société Bleue")
NBSP = "\u00a0"
SPEC = {"manufacturer": "Example Lab", "model": "R2032 half cell", "format": "coin", "chemistry": "li-ion"}


def _save_record_id(body_key: str, body: dict, root: Path) -> str:
    doc = {"schema_version": SCHEMA_VERSION, body_key: body}
    return api.save_record(
        doc, source_root=root, mode="upsert", validate=False, dry_run=True, resolve_references=False
    )["id"]


# ── The normaliser ────────────────────────────────────────────────────────────


def test_seed_text_strips_collapses_and_composes() -> None:
    assert NFC_NAME != NFD_NAME
    assert seed_text(" C01 ") == "C01"
    assert seed_text(f"Example{NBSP}Lab") == "Example Lab"
    assert seed_text("Example \t\n Lab") == "Example Lab"
    assert seed_text("Example\u2003Lab\u3000") == "Example Lab"
    assert seed_text(NFD_NAME) == NFC_NAME
    assert seed_text("Example Lab") == "Example Lab", "case is kept"
    assert seed_text(None) == ""
    assert seed_text(f" {NBSP}\t") == "", "nothing but whitespace counts as missing"


def test_stable_uid_composes_the_seed_and_keeps_ascii_seeds() -> None:
    assert stable_uid(NFD_NAME) == stable_uid(NFC_NAME)
    # An ASCII seed mints what it minted before the NFC step (golden table, 057b66a0).
    assert stable_uid("organization:example lab") == "6ssw-hd0y-q74w-cmjf"


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("li-ion", "li-ion"),
        ("Li-ion", "li-ion"),
        ("LI-ION", "li-ion"),
        (" Li-Ion ", "li-ion"),
        ("li-primary", "li-metal"),
        ("Li-primary", "li-metal"),
        ("Alkaline", "alkaline-zn-mno2"),
        ("ZnMnO2", "zn-mno2"),
        ("Zn-MnO2", "zn-mno2"),
        ("li-mno2", "li-mno2"),  # a narrower couple keeps its own key; broader is not followed
        ("unknown", "unknown"),
        ("LFP-Graphite", "LFP-Graphite"),
        ("NMC622 | Graphite", "NMC622 | Graphite"),
        (f"LFP{NBSP} Graphite", "LFP Graphite"),
    ],
)
def test_chemistry_seeds_as_its_vocabulary_key(value: str, key: str) -> None:
    assert chemistry_seed_key(value) == key


def test_cell_seed_normalises_serial_batch_and_name() -> None:
    spec_iri = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
    clean = cell_instance_identity_seed(cell_spec_id=spec_iri, serial_number="C01", batch_id="B7")
    assert cell_instance_identity_seed(cell_spec_id=spec_iri, serial_number="C01 ", batch_id=f" B7{NBSP}") == clean
    assert cell_instance_identity_seed(cell_spec_id=spec_iri, name="Cell  A") == cell_instance_identity_seed(
        cell_spec_id=spec_iri, name="Cell A"
    )
    assert cell_instance_identity_seed(cell_spec_id=spec_iri, serial_number="  ", name=" ") is None


# ── Cell specs: one IRI for one spelling, on every path ───────────────────────


def _cell_spec_iris(fields: dict, root: Path) -> dict[str, str]:
    """The IRI each cell-spec minting path gives *fields*."""
    from battinfo.publication import _finalize_publication_bundle  # noqa: PLC0415

    iris: dict[str, str] = {}
    iris["save"] = api.save_cell_spec(dict(fields), source_root=root / "save", mode="upsert")["id"]
    engine = Workspace(root / "engine")
    spec = engine.cell_spec(**fields)
    engine.render()
    iris["engine"] = str(spec.id)
    body = {
        "manufacturer": {"type": "Organization", "name": fields["manufacturer"]},
        "model": fields["model"],
        "cell_format": fields["format"],
        "chemistry": fields["chemistry"],
    }
    iris["save_record"] = _save_record_id("cell_spec", body, root / "save-record")
    run = root / "publication" / "run1"
    run.mkdir(parents=True, exist_ok=True)
    bundle, _ = _finalize_publication_bundle(
        cell_spec=CellSpec(**fields),
        cell_instance=Cell(serial_number="P01"),
        test=Test(test_kind="cycling"),
        dataset=Dataset(dataset_path=str(run)),
    )
    iris["publication"] = str(bundle.cell_spec.id)
    ws = battinfo.workspace(root / "ws", registry_url=None)
    ws_spec = CellSpec(**fields)
    ws.add("cell", spec=ws_spec, serial_numbers=["C01"])
    ws.save()
    iris["ws"] = str(ws_spec.id)
    return iris


@pytest.mark.parametrize("chemistry", ["Li-ion", "LI-ION", " li-ion "])
def test_chemistry_spellings_mint_the_key_iri_on_every_path(chemistry: str, tmp_path: Path) -> None:
    key = _cell_spec_iris(SPEC, tmp_path / "key")
    spelled = _cell_spec_iris({**SPEC, "chemistry": chemistry}, tmp_path / "spelled")
    assert len(set(key.values())) == 1, key
    assert spelled == key


def test_the_alias_li_primary_mints_the_iri_of_li_metal(tmp_path: Path) -> None:
    metal = _cell_spec_iris({**SPEC, "chemistry": "li-metal"}, tmp_path / "metal")
    primary = _cell_spec_iris({**SPEC, "chemistry": "li-primary"}, tmp_path / "primary")
    assert primary == metal


def test_chemistry_outside_the_vocabulary_and_manufacturer_keep_their_case(tmp_path: Path) -> None:
    root = tmp_path / "save"
    mint = lambda **extra: api.save_cell_spec({**SPEC, **extra}, source_root=root, mode="upsert")["id"]  # noqa: E731
    assert mint(chemistry="LFP-Graphite") != mint(chemistry="lfp-graphite")
    assert mint(manufacturer="Example Lab") != mint(manufacturer="example lab")
    assert mint(model="R2032 Half Cell") != mint(model="R2032 half cell")


def test_free_text_spec_fields_mint_one_iri(tmp_path: Path) -> None:
    clean = _cell_spec_iris({**SPEC, "manufacturer": NFC_NAME}, tmp_path / "clean")
    messy = _cell_spec_iris(
        {**SPEC, "manufacturer": f" {NFD_NAME.replace(' ', NBSP)} ", "model": "R2032  half\tcell"},
        tmp_path / "messy",
    )
    assert messy == clean


def test_size_code_is_normalised(tmp_path: Path) -> None:
    root = tmp_path / "save"
    one = api.save_cell_spec({**SPEC, "size_code": "R2032"}, source_root=root, mode="upsert")["id"]
    two = api.save_cell_spec({**SPEC, "size_code": " R2032 "}, source_root=root, mode="upsert")["id"]
    assert one == two


# ── Cells: "C01 " and "C01" are one cell ──────────────────────────────────────


def test_a_serial_with_stray_whitespace_mints_the_same_cell_on_every_path(tmp_path: Path) -> None:
    spec_iri = api.save_cell_spec(dict(SPEC), source_root=tmp_path / "save")["id"]

    def iris(serial: str, folder: str) -> dict[str, str]:
        root = tmp_path / folder
        found = {
            "save": api.save_cell_instance(
                {"cell_spec_id": spec_iri, "serial_number": serial}, source_root=root, resolve_references=False
            )["id"],
            "create": api.create_cell_instance(cell_spec_id=spec_iri, serial_number=serial, validate=False)[
                "cell_instance"
            ]["id"],
            "save_record": _save_record_id(
                "cell_instance", {"cell_spec_id": spec_iri, "serial_number": serial}, root / "save-record"
            ),
        }
        engine = Workspace(root / "engine")
        cell = engine.cell(CellSpec(id=spec_iri, **SPEC), serial_number=serial)
        engine.render()
        found["engine"] = str(cell.id)
        ws = battinfo.workspace(root / "ws", registry_url=None)
        added = ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=[serial])[0]
        ws.save()
        found["ws"] = str(added.id)
        return found

    clean = iris("C01", "clean")
    assert len(set(clean.values())) == 1, clean
    assert iris("C01 ", "trailing") == clean
    assert iris(f"C01{NBSP}", "no-break") == clean


# ── Other kinds use the same normaliser ───────────────────────────────────────


def test_other_free_text_identity_fields_are_normalised(tmp_path: Path) -> None:
    spec_iri = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
    cell_iri = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
    root = tmp_path / "save-record"
    pairs = [
        (
            "test_spec",
            {"name": "1C  cycling", "kind": "cycling", "version": " 1.0"},
            {"name": "1C cycling", "kind": "cycling", "version": "1.0"},
        ),
        (
            "test",
            {"cell_id": cell_iri, "kind": "cycling", "name": f"C01{NBSP}run "},
            {"cell_id": cell_iri, "kind": "cycling", "name": "C01 run"},
        ),
        (
            "material",
            {"material_spec_id": spec_iri, "lot_id": "LOT-1 "},
            {"material_spec_id": spec_iri, "lot_id": "LOT-1"},
        ),
        (
            "electrode",
            {"electrode_spec_id": spec_iri, "batch_id": " E-1", "piece_id": "disc 07 "},
            {"electrode_spec_id": spec_iri, "batch_id": "E-1", "piece_id": "disc 07"},
        ),
        ("organization", {"name": f"Example{NBSP} Lab"}, {"name": "Example Lab"}),
        (
            "material_spec",
            {"name": "Graphite", "kind": "graphite", "manufacturer": {"name": NFD_NAME}},
            {"name": "Graphite", "kind": "graphite", "manufacturer": {"name": NFC_NAME}},
        ),
    ]
    for body_key, messy, clean in pairs:
        assert _save_record_id(body_key, messy, root) == _save_record_id(body_key, clean, root), body_key


def test_equipment_identity_fields_are_normalised(tmp_path: Path) -> None:
    def minted(folder: str, manufacturer: str, serial: str) -> tuple[str, str]:
        root = tmp_path / folder
        root.mkdir()
        draft = root / "cycler.equipment-spec.json"
        draft.write_text(
            json.dumps({"name": "Cycler 4200", "manufacturer": manufacturer, "model": "4200", "channel_count": 1}),
            encoding="utf-8",
        )
        ws = battinfo.workspace(root, registry_url=None)
        spec = ws.load(draft)
        unit = ws.add("equipment", spec=spec, serial_number=serial)[0]
        return spec["equipment_spec"]["id"], unit["equipment"]["id"]

    assert minted("messy", " Maccor  Inc", "MC-0001 ") == minted("clean", "Maccor Inc", "MC-0001")


# ── Locators: NFC alone ───────────────────────────────────────────────────────


def test_a_locator_differing_only_in_normal_form_mints_one_dataset(tmp_path: Path) -> None:
    cell_iri = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
    nfc = f"https://example.org/{unicodedata.normalize('NFC', 'café')}.csv"
    nfd = f"https://example.org/{unicodedata.normalize('NFD', 'café')}.csv"
    assert nfc != nfd

    def minted(url: str, folder: str) -> str:
        dataset = Dataset(name="run", cell_instance_id=cell_iri, access_url=url)
        return api.save_dataset(dataset, source_root=tmp_path / folder, resolve_references=False)["id"]

    assert minted(nfc, "nfc") == minted(nfd, "nfd")


def test_a_locator_differing_in_whitespace_keeps_its_own_dataset(tmp_path: Path) -> None:
    cell_iri = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"

    def minted(url: str) -> str:
        dataset = Dataset(name="run", cell_instance_id=cell_iri, access_url=url)
        return api.save_dataset(dataset, source_root=tmp_path, resolve_references=False, mode="upsert")["id"]

    assert minted("https://example.org/run%201.csv") != minted("https://example.org/run%20%201.csv")
    assert minted("https://example.org/run 1.csv") != minted("https://example.org/run  1.csv")


# ── A cell spec saved before 0.8.0 keeps its IRI ─────────────────────────────

# The IRI save_cell_spec gave these fields at 057b66a0 (golden table): the
# chemistry is spelled "Li-ion", which now seeds as the key "li-ion".
LEGACY_FIELDS = {**SPEC, "model": "R2032 chemistry case variant", "chemistry": "Li-ion"}
LEGACY_IRI = "https://w3id.org/battinfo/spec/9wc8-sm5b-j9n9-c4w7"


def _save_legacy_spec(root: Path) -> None:
    """A record as an earlier release saved it: under its old natural-key IRI."""
    api.save_cell_spec({**LEGACY_FIELDS, "id": LEGACY_IRI}, source_root=root)


def test_the_old_rule_iri_is_not_the_new_mint(tmp_path: Path) -> None:
    fresh = api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path)["id"]
    assert fresh != LEGACY_IRI


def test_save_cell_spec_keeps_an_iri_saved_under_the_old_rule(tmp_path: Path) -> None:
    _save_legacy_spec(tmp_path)
    again = api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path, mode="upsert")
    assert again["id"] == LEGACY_IRI
    assert again["status"] == "updated"
    assert again["content_changed"] is False


def test_the_engine_and_the_workspace_keep_an_iri_saved_under_the_old_rule(tmp_path: Path) -> None:
    engine = Workspace(tmp_path / "engine")
    _save_legacy_spec(engine.source_root)
    spec = engine.cell_spec(**LEGACY_FIELDS)
    engine.save(build_index=False)
    assert spec.id == LEGACY_IRI

    ws = battinfo.workspace(tmp_path / "ws", registry_url=None)
    _save_legacy_spec(tmp_path / "ws" / ".battinfo" / "records")
    ws_spec = CellSpec(**LEGACY_FIELDS)
    ws.add("cell", spec=ws_spec, serial_numbers=["C01"])
    ws.save()
    assert ws_spec.id == LEGACY_IRI


def test_a_save_without_an_id_keeps_an_iri_saved_under_the_old_rule(tmp_path: Path) -> None:
    _save_legacy_spec(tmp_path)
    body = {
        "manufacturer": {"type": "Organization", "name": LEGACY_FIELDS["manufacturer"]},
        "model": LEGACY_FIELDS["model"],
        "cell_format": LEGACY_FIELDS["format"],
        "chemistry": LEGACY_FIELDS["chemistry"],
    }
    assert _save_record_id("cell_spec", body, tmp_path) == LEGACY_IRI


def test_the_old_rule_iri_is_kept_only_for_the_same_identity(tmp_path: Path) -> None:
    # A record pinned to the old-rule IRI that describes another cell is not reused.
    api.save_cell_spec({**LEGACY_FIELDS, "model": "Another model", "id": LEGACY_IRI}, source_root=tmp_path)
    again = api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path, mode="upsert")
    assert again["id"] != LEGACY_IRI


def test_a_record_already_saved_under_the_new_mint_wins(tmp_path: Path) -> None:
    new_iri = api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path / "fresh")["id"]
    api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path / "both")
    api.save_cell_spec({**LEGACY_FIELDS, "id": LEGACY_IRI}, source_root=tmp_path / "both")
    again = api.save_cell_spec(dict(LEGACY_FIELDS), source_root=tmp_path / "both", mode="upsert")
    assert again["id"] == new_iri


def test_the_library_keeps_an_iri_saved_under_the_old_rule(tmp_path: Path) -> None:
    library, package = tmp_path / "library", tmp_path / "package"
    record = {
        "specification": {
            "id": LEGACY_IRI,
            "manufacturer": LEGACY_FIELDS["manufacturer"],
            "model": LEGACY_FIELDS["model"],
            "format": LEGACY_FIELDS["format"],
            "chemistry": LEGACY_FIELDS["chemistry"],
        }
    }
    api.save_library_cell_spec(dict(record), library_root=library, package_root=package, validate=False)
    unpinned = {"specification": {k: v for k, v in record["specification"].items() if k != "id"}}
    again = api.save_library_cell_spec(
        unpinned, library_root=library, package_root=package, mode="upsert", validate=False
    )
    assert again["id"] == LEGACY_IRI
