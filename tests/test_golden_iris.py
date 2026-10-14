"""Golden identifiers: the IRI that each minting path gives one identity.

Seed rules freeze with the first PyPI release: a seed change after it moves
IRIs that users have already published. ``tests/fixtures/identity/golden-iris.json``
holds the IRI every case below minted at 057b66a0, the commit the 0.8.0
identity freeze started from, before any of its seed changes (every case
mints the same at 6a52fd5, the release candidate it was reviewed at). The
file is never regenerated. A change that moves an IRI adds the case to ``MOVED`` with
the IRI it mints now and the reason, and the changelog lists the move.

A case id reads ``kind | path | case``. The paths are the authoring
workspace (``ws``, ``battinfo.workspace``), the engine behind it
(``engine``), the ``save_*`` and ``create_*`` functions, a save of a record
without an id (``save_record``), the publication package (``publication``),
the folder-based batch path (``batch``) and the embedded-to-standalone
bridges (``bridge``, ``extract``). A path that mints a fresh random IRI on
every call is recorded as ``random``, and one that refuses to mint as
``refused``. A case with several records lists their IRIs, sorted and
comma-separated.

Running this module as a script prints the table for the code it runs
against; it was run once, at 057b66a0, to write the fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import api  # noqa: E402
from battinfo._workspace import Workspace  # noqa: E402
from battinfo.bundle import SCHEMA_VERSION, Cell, CellSpec, Dataset, Test, TestSpec  # noqa: E402

GOLDEN_PATH = ROOT / "tests" / "fixtures" / "identity" / "golden-iris.json"
RANDOM = "random"
REFUSED = "refused"

# Why IRIs moved. Each seed change names its reason once and lists its moves below.
CHEMISTRY_KEY = (
    "A cell spec's chemistry seeds as its vocabulary key, case-folded and with an alias "
    "resolved: Li-ion and LI-ION seed as li-ion, the alias li-primary as li-metal."
)
MATERIAL_BRIDGE = (
    "The material bridge mints through the material-spec seed (manufacturer, product, grade, "
    "kind) rather than the lower-cased name, and extract_material_specs de-duplicates by IRI."
)
ELECTRODE_BRIDGE = (
    "The component bridge lifts an electrode holder through create_electrode_spec, with the "
    "coating's first active material as its kind."
)
KIND_RESOLVED = (
    "A material or electrode spec saved without an id seeds its kind as the builders do: "
    "resolved through the vocabulary, else from its name or product id."
)
PUBLICATION_SERIAL_FIRST = (
    "The publication package seeds a cell with the shared cell seed, serial first, so a cell "
    "with a serial and another name gets the IRI every other path gives it."
)

TEST_RUN = (
    "A test is seeded from its cell, kind, protocol (its IRI whenever it has one, else its name) "
    "and run (its first data file's locator, else a start time the caller gives, else a name the "
    "caller gives), never from a title BattINFO generates."
)
TEST_RUN_SAVED_WITHOUT_ID = (
    TEST_RUN + " A save without an id mints a test that has a cell and a kind, where it refused one "
    "with no name or protocol name."
)
DATASET_OF_MOVED_TEST = "A dataset's seed includes its test's IRI, which moved with the test seed."
BATCH_CELL = (
    "The batch path mints a cell that has a serial number through the shared cell seed (spec, serial, batch), "
    "so it gets the IRI every other path gives it, and a cell without one gets a random IRI, recorded in its "
    "battinfo.yaml, never one from its place in the batch."
)
TEST_ON_A_BATCH_CELL = TEST_RUN + " Its cell moved as well: " + BATCH_CELL
BATCH_LIBRARY = (
    "The batch path refuses a cell spec that no cell-spec library holds, so the case saves its cell spec "
    "in the local library first. At 057b66a0 it packaged a cell spec with only its IRI and a blank name, "
    "and a dataset's title, which its seed includes, now carries the spec's name. With the blank name the "
    "case mints t11a-1q7d-hw1j-an2v, the move the test seed alone gives."
)

#: Cases whose IRI moved since 057b66a0: case id -> (what it mints now, why it moved).
MOVED: dict[str, tuple[str, str]] = {
    "cell-spec | engine | chemistry alias": (
        "https://w3id.org/battinfo/spec/vm5x-t3tk-5se8-xaqm",
        CHEMISTRY_KEY,
    ),
    "cell-spec | engine | chemistry case variant": (
        "https://w3id.org/battinfo/spec/s08z-hw1a-r5bw-ejpn",
        CHEMISTRY_KEY,
    ),
    "cell-spec | engine | chemistry upper case": (
        "https://w3id.org/battinfo/spec/pmda-v1sm-tv57-zrqt",
        CHEMISTRY_KEY,
    ),
    "cell-spec | publication | chemistry alias": (
        "https://w3id.org/battinfo/spec/vm5x-t3tk-5se8-xaqm",
        CHEMISTRY_KEY,
    ),
    "cell-spec | publication | chemistry case variant": (
        "https://w3id.org/battinfo/spec/s08z-hw1a-r5bw-ejpn",
        CHEMISTRY_KEY,
    ),
    "cell-spec | publication | chemistry upper case": (
        "https://w3id.org/battinfo/spec/pmda-v1sm-tv57-zrqt",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save | chemistry alias": (
        "https://w3id.org/battinfo/spec/vm5x-t3tk-5se8-xaqm",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save | chemistry case variant": (
        "https://w3id.org/battinfo/spec/s08z-hw1a-r5bw-ejpn",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save | chemistry upper case": (
        "https://w3id.org/battinfo/spec/pmda-v1sm-tv57-zrqt",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save_record | chemistry alias": (
        "https://w3id.org/battinfo/spec/vm5x-t3tk-5se8-xaqm",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save_record | chemistry case variant": (
        "https://w3id.org/battinfo/spec/s08z-hw1a-r5bw-ejpn",
        CHEMISTRY_KEY,
    ),
    "cell-spec | save_record | chemistry upper case": (
        "https://w3id.org/battinfo/spec/pmda-v1sm-tv57-zrqt",
        CHEMISTRY_KEY,
    ),
    "cell-spec | ws | chemistry alias": (
        "https://w3id.org/battinfo/spec/vm5x-t3tk-5se8-xaqm",
        CHEMISTRY_KEY,
    ),
    "cell-spec | ws | chemistry case variant": (
        "https://w3id.org/battinfo/spec/s08z-hw1a-r5bw-ejpn",
        CHEMISTRY_KEY,
    ),
    "cell-spec | ws | chemistry upper case": (
        "https://w3id.org/battinfo/spec/pmda-v1sm-tv57-zrqt",
        CHEMISTRY_KEY,
    ),
    "cell | batch | batch and folder index": (RANDOM, BATCH_CELL),
    "cell | batch | folder index": (RANDOM, BATCH_CELL),
    "cell | batch | serial": (
        "https://w3id.org/battinfo/cell/fq1x-4nx3-v669-sp5x",
        BATCH_CELL,
    ),
    "cell | batch | serial and batch": (
        "https://w3id.org/battinfo/cell/enyv-qcg0-2ypb-r6v4",
        BATCH_CELL,
    ),
    "cell | publication | serial and name": (
        "https://w3id.org/battinfo/cell/df2p-j6g8-f4ks-av3c",
        PUBLICATION_SERIAL_FIRST,
    ),
    "cell | publication | serial, batch and name": (
        "https://w3id.org/battinfo/cell/pxp5-t8ca-9d85-hkk9",
        PUBLICATION_SERIAL_FIRST,
    ),
    "dataset | batch | data file": (
        "https://w3id.org/battinfo/dataset/nkrg-hajk-8p2a-ajex",
        DATASET_OF_MOVED_TEST + " " + BATCH_LIBRARY,
    ),
    "dataset | engine | local file": (
        "https://w3id.org/battinfo/dataset/sn2k-65ds-d0p7-sw6m",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | engine | remote URL": (
        "https://w3id.org/battinfo/dataset/jaxg-v6h0-dk5t-hjbq",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | publication | dataset folder": (
        "https://w3id.org/battinfo/dataset/4paf-wh40-5b0b-wgjk",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | save | local file": (
        "https://w3id.org/battinfo/dataset/n7hj-ykny-pdfg-f3es",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | save | remote URL": (
        "https://w3id.org/battinfo/dataset/jaxg-v6h0-dk5t-hjbq",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | ws | colliding pair": (
        "https://w3id.org/battinfo/dataset/6ga0-td7g-4nf4-j55r, https://w3id.org/battinfo/dataset/9w9d-06sq-4eee-35vm",
        DATASET_OF_MOVED_TEST,
    ),
    "dataset | ws | local file": (
        "https://w3id.org/battinfo/dataset/7hsd-56hd-xtk2-cckf",
        DATASET_OF_MOVED_TEST,
    ),
    "electrode-spec | bridge | extended example, A123 ANR26650M1-B negative electrode": (
        "https://w3id.org/battinfo/spec/58e8-7982-avxm-w0y4",
        ELECTRODE_BRIDGE,
    ),
    "electrode-spec | bridge | extended example, A123 ANR26650M1-B positive electrode": (
        "https://w3id.org/battinfo/spec/cptc-3hxy-bn2m-cyh5",
        ELECTRODE_BRIDGE,
    ),
    "electrode-spec | save_record | kind from the name": (
        "https://w3id.org/battinfo/spec/h3t5-dn8b-8pd1-tjms",
        KIND_RESOLVED,
    ),
    "material-spec | bridge | Graphite from BTR": (
        "https://w3id.org/battinfo/spec/kb21-02cj-ffhz-ax86",
        MATERIAL_BRIDGE,
    ),
    "material-spec | bridge | Graphite from Imerys": (
        "https://w3id.org/battinfo/spec/3z1m-c26r-mc8q-vge8",
        MATERIAL_BRIDGE,
    ),
    "material-spec | bridge | lower-case name": (
        "https://w3id.org/battinfo/spec/qdbk-w86d-ae1x-jxgz",
        MATERIAL_BRIDGE,
    ),
    "material-spec | bridge | name only": (
        "https://w3id.org/battinfo/spec/6rq6-s3tx-b6ym-ht0g",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | Graphite and graphite": (
        "https://w3id.org/battinfo/spec/qdbk-w86d-ae1x-jxgz",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | Graphite from two suppliers": (
        "https://w3id.org/battinfo/spec/3z1m-c26r-mc8q-vge8, https://w3id.org/battinfo/spec/kb21-02cj-ffhz-ax86",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, Al foil": (
        "https://w3id.org/battinfo/spec/nqva-2dhw-mzy8-f8x8",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, Al2O3 particles": (
        "https://w3id.org/battinfo/spec/2j42-4zq6-xwk1-dtr2",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, CMC/SBR": (
        "https://w3id.org/battinfo/spec/gd25-a1vh-0yh1-ce83",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, Carbon black": (
        "https://w3id.org/battinfo/spec/8yq1-rsc0-h6nh-3xhj",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, Cu foil": (
        "https://w3id.org/battinfo/spec/6rpq-zcnn-wqzc-g9st",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, EC": (
        "https://w3id.org/battinfo/spec/yb44-wr9q-hwc0-vwbw",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, EMC": (
        "https://w3id.org/battinfo/spec/myrj-s5dn-ex88-m6t5",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, FEC": (
        "https://w3id.org/battinfo/spec/v5nx-qbaq-gn9e-fn2w",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, Graphite": (
        "https://w3id.org/battinfo/spec/qdbk-w86d-ae1x-jxgz",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, LFP": (
        "https://w3id.org/battinfo/spec/6rq6-s3tx-b6ym-ht0g",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, LiPF6": (
        "https://w3id.org/battinfo/spec/aeqc-tqax-m5f1-g6qq",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, PE/PP trilayer": (
        "https://w3id.org/battinfo/spec/caf0-889v-mnp6-kntt",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, PVDF": (
        "https://w3id.org/battinfo/spec/je56-4c60-jxdz-050c",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, SiOx": (
        "https://w3id.org/battinfo/spec/cx3r-61k7-mw27-rc1w",
        MATERIAL_BRIDGE,
    ),
    "material-spec | extract | extended example, VC": (
        "https://w3id.org/battinfo/spec/cqgd-n9q6-vyxr-6mrv",
        MATERIAL_BRIDGE,
    ),
    "material-spec | save_record | kind alias": (
        "https://w3id.org/battinfo/spec/kb21-02cj-ffhz-ax86",
        KIND_RESOLVED,
    ),
    "material-spec | save_record | kind from the name": (
        "https://w3id.org/battinfo/spec/6rq6-s3tx-b6ym-ht0g",
        KIND_RESOLVED,
    ),
    "test | batch | data file": (
        "https://w3id.org/battinfo/test/gszh-7v6a-ttxz-3afm",
        TEST_ON_A_BATCH_CELL,
    ),
    "test | engine | named": (
        "https://w3id.org/battinfo/test/jnz2-b453-nmwr-12jw",
        TEST_RUN,
    ),
    "test | engine | protocol name": (
        "https://w3id.org/battinfo/test/q97r-dted-6djm-be68",
        TEST_RUN,
    ),
    "test | engine | unnamed": (
        "https://w3id.org/battinfo/test/qqkc-ye32-0wn1-rg87",
        TEST_RUN,
    ),
    "test | engine | with data": (
        "https://w3id.org/battinfo/test/jtkh-tr1b-pz2m-eynn",
        TEST_RUN,
    ),
    "test | publication | named": (
        "https://w3id.org/battinfo/test/9581-wqtz-26qv-d2ac",
        TEST_RUN,
    ),
    "test | publication | protocol name": (
        "https://w3id.org/battinfo/test/h436-1422-wdbv-q43x",
        TEST_RUN,
    ),
    "test | publication | unnamed": (
        "https://w3id.org/battinfo/test/mev1-meek-zta8-61f1",
        TEST_RUN,
    ),
    "test | save | named": (
        "https://w3id.org/battinfo/test/ha18-0evh-gx4w-87nh",
        TEST_RUN,
    ),
    "test | save | protocol name": (
        "https://w3id.org/battinfo/test/q97r-dted-6djm-be68",
        TEST_RUN,
    ),
    "test | save | unnamed": (
        "https://w3id.org/battinfo/test/qqkc-ye32-0wn1-rg87",
        TEST_RUN,
    ),
    "test | save_record | named": (
        "https://w3id.org/battinfo/test/ha18-0evh-gx4w-87nh",
        TEST_RUN,
    ),
    "test | save_record | protocol name": (
        "https://w3id.org/battinfo/test/q97r-dted-6djm-be68",
        TEST_RUN,
    ),
    "test | save_record | unnamed": (
        "https://w3id.org/battinfo/test/qqkc-ye32-0wn1-rg87",
        TEST_RUN_SAVED_WITHOUT_ID,
    ),
    "test | ws | colliding pair, a.csv": (
        "https://w3id.org/battinfo/test/cyjy-8abx-gj74-693b",
        TEST_RUN,
    ),
    "test | ws | colliding pair, b.csv": (
        "https://w3id.org/battinfo/test/6w8h-wfmr-gary-mzsm",
        TEST_RUN,
    ),
    "test | ws | named": (
        "https://w3id.org/battinfo/test/ha18-0evh-gx4w-87nh",
        TEST_RUN,
    ),
    "test | ws | protocol by IRI, not saved here": (
        "https://w3id.org/battinfo/test/n7x2-v3t4-ge1v-2f93",
        TEST_RUN,
    ),
    "test | ws | protocol object": (
        "https://w3id.org/battinfo/test/y4w0-0k6s-8a94-6g24",
        TEST_RUN,
    ),
    "test | ws | unnamed": (
        "https://w3id.org/battinfo/test/qqkc-ye32-0wn1-rg87",
        TEST_RUN,
    ),
    "test | ws | with data": (
        "https://w3id.org/battinfo/test/jtkh-tr1b-pz2m-eynn",
        TEST_RUN,
    ),
}


# ── Inputs ────────────────────────────────────────────────────────────────────

SPEC = {"manufacturer": "Example Lab", "model": "R2032 half cell", "format": "coin", "chemistry": "li-ion"}

# Each chemistry case has its own model, so the cases do not collide in one workspace.
CELL_SPEC_CASES: dict[str, dict[str, str]] = {
    "chemistry key": {"chemistry": "li-ion"},
    "chemistry case variant": {"chemistry": "Li-ion"},
    "chemistry upper case": {"chemistry": "LI-ION"},
    "chemistry alias": {"chemistry": "li-primary"},
    "chemistry outside the vocabulary": {"chemistry": "LFP-Graphite"},
    "size code": {"chemistry": "li-metal", "size_code": "R2032"},
}

CELL_CASES: dict[str, dict[str, str]] = {
    "serial": {"serial_number": "C01"},
    "name": {"name": "Cell A"},
    "batch": {"batch_id": "B7"},
    "serial and name": {"serial_number": "C02", "name": "Cell B"},
    "serial and batch": {"serial_number": "C03", "batch_id": "B7"},
    "batch and name": {"batch_id": "B8", "name": "Cell C"},
    "serial, batch and name": {"serial_number": "C04", "batch_id": "B8", "name": "Cell D"},
}

TEST_PROTOCOL_CASES: dict[str, dict[str, str]] = {
    "name": {"name": "1C cycling"},
    "name and version": {"name": "C/10 formation", "version": "1.0"},
}

REMOTE_URL = "https://example.org/data/C01-run2.csv"
PROTOCOL_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"

MATERIAL_SPEC_CASES: dict[str, dict[str, Any]] = {
    "kind key": {"name": "Graphite SLP30", "kind": "graphite", "manufacturer": "Imerys", "product_id": "SLP30"},
    "kind alias": {"name": "Graphite BFC-18", "kind": "Graphite", "manufacturer": "BTR", "product_id": "BFC-18"},
    "kind from the name": {"name": "LFP"},
    "grade": {"name": "NMC811", "kind": "nmc811", "manufacturer": "Targray", "grade": "SNMC03008"},
}

# Embedded holders the material bridge lifts.
MATERIAL_HOLDERS: dict[str, dict[str, Any]] = {
    "Graphite from Imerys": {"name": "Graphite", "manufacturer": "Imerys", "product_id": "SLP30"},
    "Graphite from BTR": {"name": "Graphite", "manufacturer": "BTR", "product_id": "BFC-18"},
    "name only": {"name": "LFP"},
    "lower-case name": {"name": "graphite"},
}

MATERIAL_CASES: dict[str, dict[str, str]] = {
    "lot": {"lot_id": "LOT-1"},
    "batch": {"batch_id": "B-1"},
    "name": {"name": "Graphite jar 3"},
}

ELECTRODE_SPEC_CASES: dict[str, dict[str, Any]] = {
    "kind key": {"name": "Graphite anode", "active_material_kind": "graphite"},
    "kind alias": {"name": "Graphite anode B", "active_material_kind": "Graphite"},
    "kind from the name": {"name": "LFP"},
    "producer and route": {
        "name": "Si-Gr anode",
        "active_material_kind": "silicon_graphite",
        "manufacturer": "SINTEF",
        "product_id": "SG-1",
        "processing": {"route": "aqueous"},
    },
}

CLAIMS = [{"parameter": "particle_radius", "quantity": {"value": 5.86e-6, "unit": "m"}, "provenance_class": "fitted"}]

EXTENDED_EXAMPLE = ROOT / "examples" / "cell-spec" / "research" / "extended.example.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _org(name: str | None) -> dict[str, str] | None:
    return {"type": "Organization", "name": name} if name else None


def _save_record_id(body_key: str, body: dict[str, Any], root: Path) -> str:
    """The IRI a save of *body* without an id mints, or ``refused``."""
    doc = {"schema_version": SCHEMA_VERSION, body_key: {k: v for k, v in body.items() if v is not None}}
    try:
        return api.save_record(doc, source_root=root, validate=False, dry_run=True, resolve_references=False)["id"]
    except ValueError as exc:
        if "without an id" in str(exc):
            return REFUSED
        raise


def _random_or(first: str, second: str) -> str:
    """``random`` when two calls with one input mint two IRIs, else the IRI."""
    return RANDOM if first != second else first


def _publication(root: Path, **parts: Any) -> Any:
    """The finalized publication bundle for one cell, test and dataset folder."""
    from battinfo.publication import _finalize_publication_bundle  # noqa: PLC0415

    run = root / "run1"
    run.mkdir(parents=True, exist_ok=True)
    bundle, _ = _finalize_publication_bundle(
        cell_spec=parts.get("cell_spec") or CellSpec(**SPEC),
        cell_instance=parts.get("cell") or Cell(serial_number="P01"),
        test=parts.get("test") or Test(test_kind="cycling"),
        dataset=parts.get("dataset") or Dataset(dataset_path=str(run)),
    )
    return bundle


@contextlib.contextmanager
def _batch_library(root: Path, spec_iri: str) -> Iterator[None]:
    """Run the batch path from *root*, with :data:`SPEC` saved under *spec_iri* in its local cell-spec library.

    The batch path refuses a cell spec that neither the packaged library nor
    ``./.battinfo/library/cell-spec`` holds; at 057b66a0 it went on with a cell
    spec that had only its IRI.
    """
    library = root / ".battinfo" / "library" / "cell-spec"
    library.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": SCHEMA_VERSION, "specification": {"id": spec_iri, **SPEC}}
    (library / "golden.json").write_text(json.dumps(record), encoding="utf-8")
    with contextlib.chdir(root):
        yield


def _workspace(root: Path) -> Any:
    root.mkdir(parents=True, exist_ok=True)
    return battinfo.workspace(root, registry_url=None)


def _engine_spec_iri(root: Path) -> str:
    """The IRI the engine mints for :data:`SPEC`, which every cell case links to."""
    engine = Workspace(root)
    spec = engine.cell_spec(**SPEC)
    engine.render()
    return str(spec.id)


def _cell_spec_fields(case: str) -> dict[str, str]:
    return {**SPEC, "model": f"R2032 {case}", **CELL_SPEC_CASES[case]}


# ── Cases, grouped by the records they mint ──────────────────────────────────


def _cell_specs(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}

    engine = Workspace(root / "engine")
    made = {case: engine.cell_spec(**_cell_spec_fields(case)) for case in CELL_SPEC_CASES}
    engine.render()
    rows.update({f"cell-spec | engine | {case}": str(spec.id) for case, spec in made.items()})

    ws = _workspace(root / "ws")
    loaded = {}
    for case in CELL_SPEC_CASES:
        draft = root / "ws" / f"{case.replace(' ', '-')}.cell-spec.json"
        draft.write_text(json.dumps(_cell_spec_fields(case)), encoding="utf-8")
        loaded[case] = ws.load(draft)
    ws.save()
    rows.update({f"cell-spec | ws | {case}": str(spec.id) for case, spec in loaded.items()})

    for case in CELL_SPEC_CASES:
        fields = _cell_spec_fields(case)
        rows[f"cell-spec | save | {case}"] = api.save_cell_spec(dict(fields), source_root=root / "save")["id"]
        body = {
            "manufacturer": _org(fields["manufacturer"]),
            "model": fields["model"],
            "cell_format": fields["format"],
            "chemistry": fields["chemistry"],
            "size_code": fields.get("size_code"),
        }
        rows[f"cell-spec | save_record | {case}"] = _save_record_id("cell_spec", body, root / "save-record")
        bundle = _publication(root / "publication" / case.replace(" ", "-"), cell_spec=CellSpec(**fields))
        rows[f"cell-spec | publication | {case}"] = str(bundle.cell_spec.id)
    return rows


def _cells(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}

    engine = Workspace(root / "engine")
    spec = engine.cell_spec(**SPEC)
    made = {case: engine.cell(spec, **fields) for case, fields in CELL_CASES.items()}
    engine.render()
    rows.update({f"cell | engine | {case}": str(cell.id) for case, cell in made.items()})
    spec_iri = str(spec.id)

    ws = _workspace(root / "ws")
    ws_spec = CellSpec(**SPEC)
    by_case = {
        "serial": ws.add("cell", spec=ws_spec, serial_numbers=["C01"])[0],
        "name": ws.add("cell", spec=ws_spec, names=["Cell A"])[0],
        "serial and name": ws.add("cell", spec=ws_spec, names=["Cell B"], serial_numbers=["C02"])[0],
    }
    ws.save()
    rows.update({f"cell | ws | {case}": str(cell.id) for case, cell in by_case.items()})

    for case, fields in CELL_CASES.items():
        draft = {"cell_spec_id": spec_iri, **fields}
        saved = api.save_cell_instance(dict(draft), source_root=root / "save", resolve_references=False)
        rows[f"cell | save | {case}"] = saved["id"]
        rows[f"cell | save_record | {case}"] = _save_record_id("cell_instance", draft, root / "save-record")
        bundle = _publication(root / "publication" / case.replace(" ", "-").replace(",", ""), cell=Cell(**fields))
        rows[f"cell | publication | {case}"] = str(bundle.cell_instance.id)

    created = api.create_cell_instance(cell_spec_id=spec_iri, serial_number="C01", validate=False)
    rows["cell | create | serial"] = created["cell_instance"]["id"]

    from battinfo.contribution import init_batch  # noqa: PLC0415

    def batch_iris(folder: str, count: int, **kwargs: Any) -> str:
        """The cell IRIs two ``battinfo batch init`` runs mint, or ``random`` when they differ."""
        runs = [
            ", ".join(
                sorted(
                    cell["cell_iri"]
                    for cell in init_batch(root / "batch" / f"{folder}-{n}", cell_spec=spec_iri, count=count, **kwargs)[
                        "cells"
                    ]
                )
            )
            for n in (1, 2)
        ]
        return _random_or(*runs)

    with _batch_library(root, spec_iri):
        rows["cell | batch | serial"] = batch_iris("serial", 1, serial_numbers=["C01"])
        rows["cell | batch | serial and batch"] = batch_iris("serial-batch", 1, batch_id="B7", serial_numbers=["C03"])
        rows["cell | batch | folder index"] = batch_iris("index", 2)
        rows["cell | batch | batch and folder index"] = batch_iris("batch-index", 1, batch_id="B7")
    return rows


def _batch_packages(root: Path) -> dict[str, str]:
    """The test and dataset a ``battinfo batch`` package mints for one data file."""
    from battinfo.contribution import init_batch, package_batch  # noqa: PLC0415

    spec_iri = _engine_spec_iri(root / "engine")
    with _batch_library(root, spec_iri):
        made = init_batch(root / "batch", cell_spec=spec_iri, count=1, serial_numbers=["C01"])
        data = root / "batch" / made["cells"][0]["folder"] / "data" / "C01_cycling.csv"
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")
        result = package_batch(root / "batch", creators=[{"name": "Clark, Simon", "affiliation": "SINTEF"}])
    entry = json.loads(Path(result["bundle_path"]).read_text(encoding="utf-8"))["datasets"][0]
    return {
        "test | batch | data file": entry["test"]["test"]["id"],
        "dataset | batch | data file": entry["dataset"]["dataset"]["id"],
    }


def _test_protocols(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}

    engine = Workspace(root / "engine")
    made = {case: engine.test_spec(type="cycling", **fields) for case, fields in TEST_PROTOCOL_CASES.items()}
    engine.render()
    rows.update({f"test-protocol | engine | {case}": str(spec.id) for case, spec in made.items()})

    ws = _workspace(root / "ws")
    loaded = {}
    for case, fields in TEST_PROTOCOL_CASES.items():
        draft = root / "ws" / f"{case.replace(' ', '-')}.test-spec.json"
        draft.write_text(json.dumps({**fields, "type": "cycling"}), encoding="utf-8")
        loaded[case] = ws.load(draft)
    ws.save()
    rows.update({f"test-protocol | ws | {case}": str(spec.id) for case, spec in loaded.items()})

    for case, fields in TEST_PROTOCOL_CASES.items():
        saved = api.save_test_spec({**fields, "kind": "cycling"}, source_root=root / "save")
        rows[f"test-protocol | save | {case}"] = saved["id"]
        rows[f"test-protocol | save_record | {case}"] = _save_record_id(
            "test_spec", {**fields, "kind": "cycling"}, root / "save-record"
        )
    return rows


def _tests_and_datasets(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}

    ws = _workspace(root / "ws")
    data = root / "ws" / "data" / "C01.csv"
    data.parent.mkdir(parents=True)
    data.write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    unnamed = ws.add("test", type="cycling", cell="C01")[0]
    named = ws.add("test", type="formation", cell="C01", name="C01 formation run")[0]
    with_data = ws.add("test", type="capacity_check", cell="C01", data="data/C01.csv")[0]
    protocol_object = ws.add(
        "test", cell="C01", type="rate_capability", spec=TestSpec(name="CCCV 1C", test_kind="rate_capability")
    )[0]
    protocol_iri = ws.add("test", type="gitt", cell="C01", spec=PROTOCOL_IRI)[0]
    ws.save()
    rows["test | ws | unnamed"] = str(unnamed.id)
    rows["test | ws | named"] = str(named.id)
    rows["test | ws | with data"] = str(with_data.id)
    rows["test | ws | protocol object"] = str(protocol_object.id)
    rows["test | ws | protocol by IRI, not saved here"] = str(protocol_iri.id)
    rows["dataset | ws | local file"] = ", ".join(sorted(str(d.id) for d in ws._ws.datasets))

    engine = Workspace(root / "engine")
    spec = engine.cell_spec(**SPEC)
    cell = engine.cell(spec, serial_number="C01")
    engine_tests = {
        "unnamed": engine.test(cell, kind="cycling"),
        "named": engine.test(cell, kind="formation", name="C01 formation run"),
        "protocol name": engine.test(cell, kind="rate_capability", protocol="CCCV 1C"),
    }
    engine_data = root / "engine" / "data" / "C01.csv"
    engine_data.parent.mkdir(parents=True)
    engine_data.write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")
    engine_tests["with data"] = engine.record_test(cell, kind="capacity_check", path=engine_data)
    local = engine.datasets[-1]
    remote = engine.dataset(cell, title="C01 remote run", test=engine_tests["named"], access_url=REMOTE_URL)
    engine.render()
    rows.update({f"test | engine | {case}": str(test.id) for case, test in engine_tests.items()})
    rows["dataset | engine | local file"] = str(local.id)
    rows["dataset | engine | remote URL"] = str(remote.id)
    cell_iri, test_iri = str(cell.id), str(engine_tests["named"].id)

    save_root = root / "save"
    for case, test in {
        "unnamed": Test(cell_instance_id=cell_iri, test_kind="cycling"),
        "named": Test(cell_instance_id=cell_iri, test_kind="formation", name="C01 formation run"),
        "protocol name": Test(cell_instance_id=cell_iri, test_kind="rate_capability", protocol={"name": "CCCV 1C"}),
    }.items():
        rows[f"test | save | {case}"] = api.save_test(test, source_root=save_root, resolve_references=False)["id"]
    for case, body in {
        "unnamed": {"cell_id": cell_iri, "kind": "cycling"},
        "named": {"cell_id": cell_iri, "kind": "formation", "name": "C01 formation run"},
        "protocol name": {"cell_id": cell_iri, "kind": "rate_capability", "protocol_name": "CCCV 1C"},
    }.items():
        rows[f"test | save_record | {case}"] = _save_record_id("test", body, root / "save-record")

    save_data = save_root / "data" / "C01.csv"
    save_data.parent.mkdir(parents=True, exist_ok=True)
    save_data.write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")
    local_saved = api.save_dataset(
        Dataset(
            name="C01 data",
            cell_instance_id=cell_iri,
            test_id=test_iri,
            dataset_path=str(save_data),
            access_url=save_data.resolve().as_uri(),
        ),
        source_root=save_root,
        resolve_references=False,
    )
    remote_saved = api.save_dataset(
        Dataset(name="C01 remote run", cell_instance_id=cell_iri, test_id=test_iri, access_url=REMOTE_URL),
        source_root=save_root,
        resolve_references=False,
    )
    rows["dataset | save | local file"] = local_saved["id"]
    rows["dataset | save | remote URL"] = remote_saved["id"]
    rows["dataset | save_record | remote URL"] = _save_record_id(
        "dataset", {"name": "C01 remote run", "access_url": REMOTE_URL}, root / "save-record"
    )

    for case, test in {
        "unnamed": Test(test_kind="cycling"),
        "named": Test(test_kind="formation", name="P01 formation run"),
        "protocol name": Test(test_kind="rate_capability", protocol={"name": "CCCV 1C"}),
    }.items():
        bundle = _publication(root / "publication" / case.replace(" ", "-"), test=test)
        rows[f"test | publication | {case}"] = str(bundle.test.id)
        if case == "unnamed":
            rows["dataset | publication | dataset folder"] = str(bundle.dataset.id)
    return rows


def _material_specs(root: Path) -> dict[str, str]:
    from battinfo.materials import extract_material_specs, material_spec_from_component  # noqa: PLC0415

    rows: dict[str, str] = {}
    ws = _workspace(root / "ws")
    for case, fields in MATERIAL_SPEC_CASES.items():
        rows[f"material-spec | ws | {case}"] = ws.add("material_spec", **fields)[0]["material_spec"]["id"]
        rows[f"material-spec | create | {case}"] = api.create_material_spec(validate=False, **fields)["material_spec"][
            "id"
        ]
        rows[f"material-spec | save | {case}"] = api.save_material_spec(
            dict(fields), source_root=root / "save", validate=False
        )["id"]
        body = {**fields, "manufacturer": _org(fields.get("manufacturer"))}
        rows[f"material-spec | save_record | {case}"] = _save_record_id("material_spec", body, root / "save-record")
    ws.save()

    for case, holder in MATERIAL_HOLDERS.items():
        rows[f"material-spec | bridge | {case}"] = material_spec_from_component(holder)["material_spec"]["id"]

    extended = json.loads(EXTENDED_EXAMPLE.read_text(encoding="utf-8"))
    for spec in extract_material_specs(extended):
        body = spec["material_spec"]
        rows[f"material-spec | extract | extended example, {body['name']}"] = body["id"]
    two_suppliers = {
        "positive_electrode": {
            "coating": {"component": {"active_material": [MATERIAL_HOLDERS["Graphite from Imerys"]]}}
        },
        "negative_electrode": {"coating": {"component": {"active_material": [MATERIAL_HOLDERS["Graphite from BTR"]]}}},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lifted = extract_material_specs(two_suppliers)
    rows["material-spec | extract | Graphite from two suppliers"] = ", ".join(
        sorted(spec["material_spec"]["id"] for spec in lifted)
    )
    one_supplier = {
        "positive_electrode": {"coating": {"component": {"active_material": [{"name": "Graphite"}]}}},
        "negative_electrode": {"coating": {"component": {"active_material": [{"name": "graphite"}]}}},
    }
    rows["material-spec | extract | Graphite and graphite"] = ", ".join(
        sorted(spec["material_spec"]["id"] for spec in extract_material_specs(one_supplier))
    )
    return rows


def _materials(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    spec = api.create_material_spec(validate=False, **MATERIAL_SPEC_CASES["kind key"])
    spec_iri = spec["material_spec"]["id"]
    ws = _workspace(root / "ws")
    for case, fields in MATERIAL_CASES.items():
        lot = fields.get("lot_id")
        extra = {k: v for k, v in fields.items() if k != "lot_id"}
        rows[f"material | ws | {case}"] = ws.add("material", spec=spec, lot=lot, **extra)[0]["material"]["id"]
        rows[f"material | create | {case}"] = api.create_material(validate=False, material_spec_id=spec_iri, **fields)[
            "material"
        ]["id"]
        rows[f"material | save | {case}"] = api.save_material(
            {"material_spec_id": spec_iri, **fields},
            source_root=root / "save",
            validate=False,
            resolve_references=False,
        )["id"]
        rows[f"material | save_record | {case}"] = _save_record_id(
            "material", {"material_spec_id": spec_iri, **fields}, root / "save-record"
        )
    return rows


def _electrode_specs(root: Path) -> dict[str, str]:
    from battinfo.components import extract_component_specs  # noqa: PLC0415

    rows: dict[str, str] = {}
    ws = _workspace(root / "ws")
    for case, fields in ELECTRODE_SPEC_CASES.items():
        rows[f"electrode-spec | ws | {case}"] = ws.add("electrode_spec", **fields)[0]["electrode_spec"]["id"]
        rows[f"electrode-spec | create | {case}"] = api.create_electrode_spec(validate=False, **fields)[
            "electrode_spec"
        ]["id"]
        rows[f"electrode-spec | save | {case}"] = api.save_electrode_spec(
            dict(fields), source_root=root / "save", validate=False
        )["id"]
        body = {**fields, "manufacturer": _org(fields.get("manufacturer"))}
        rows[f"electrode-spec | save_record | {case}"] = _save_record_id("electrode_spec", body, root / "save-record")

    extended = json.loads(EXTENDED_EXAMPLE.read_text(encoding="utf-8"))
    extended["housing"] = {"name": "R26650 steel can", "material": "nickel-plated steel"}
    for record in extract_component_specs(extended):
        key = next(k for k in record if k.endswith("_spec"))
        body = record[key]
        kind = key.replace("_", "-")
        rows[f"{kind} | bridge | extended example, {body['name']}"] = body["id"]
    return rows


def _electrodes(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    spec = api.create_electrode_spec(validate=False, **ELECTRODE_SPEC_CASES["kind key"])
    spec_iri = spec["electrode_spec"]["id"]
    ws = _workspace(root / "ws")
    roll = ws.add("electrode", spec=spec, batch="E-1")[0]
    rows["electrode | ws | batch"] = roll["electrode"]["id"]
    parent = roll["electrode"]["id"]
    rows["electrode | ws | piece of a roll"] = ws.add(
        "electrode", spec=spec, batch="E-1", parent_id=parent, piece_id="disc-07"
    )[0]["electrode"]["id"]
    rows["electrode | create | batch"] = api.create_electrode(validate=False, electrode_spec_id=spec_iri, batch="E-1")[
        "electrode"
    ]["id"]
    rows["electrode | create | piece of a roll"] = api.create_electrode(
        validate=False, electrode_spec_id=spec_iri, batch="E-1", parent_id=parent, piece_id="disc-07"
    )["electrode"]["id"]
    rows["electrode | save_record | batch"] = _save_record_id(
        "electrode", {"electrode_spec_id": spec_iri, "batch_id": "E-1"}, root / "save-record"
    )
    rows["electrode | save_record | piece of a roll"] = _save_record_id(
        "electrode",
        {"electrode_spec_id": spec_iri, "batch_id": "E-1", "parent_id": parent, "piece_id": "disc-07"},
        root / "save-record",
    )
    return rows


def _component_families(root: Path) -> dict[str, str]:
    """Separators, current collectors, electrolytes and housings: random without a uid."""
    rows: dict[str, str] = {}
    for family in ("separator", "current_collector", "electrolyte", "housing"):
        create_spec = getattr(api, f"create_{family}_spec")
        create_instance = getattr(api, f"create_{family}")
        kind = family.replace("_", "-")
        first = create_spec(validate=False, name=f"Example {kind}")[f"{family}_spec"]["id"]
        second = create_spec(validate=False, name=f"Example {kind}")[f"{family}_spec"]["id"]
        rows[f"{kind}-spec | create | name"] = _random_or(first, second)
        rows[f"{kind}-spec | save_record | name"] = _save_record_id(
            f"{family}_spec", {"name": f"Example {kind}"}, root / "save-record"
        )
        made = [create_instance(validate=False, spec_id=first, name="unit 1")[family]["id"] for _ in range(2)]
        rows[f"{kind} | create | name"] = _random_or(*made)
        rows[f"{kind} | save_record | name"] = _save_record_id(
            family, {f"{family}_spec_id": first, "name": "unit 1"}, root / "save-record"
        )
    return rows


def _equipment(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    ws = _workspace(root / "ws")
    draft = root / "ws" / "cycler.equipment-spec.json"
    draft.write_text(
        json.dumps({"name": "Cycler 4200", "manufacturer": "Maccor", "model": "4200", "channel_count": 2}),
        encoding="utf-8",
    )
    spec_record = ws.load(draft)
    rows["equipment-spec | ws | manufacturer, model and name"] = spec_record["equipment_spec"]["id"]
    added = ws.add("equipment", spec=spec_record, serial_number="MC-0001", name="Cycler 1")
    rows["equipment | ws | serial"] = added[0]["equipment"]["id"]
    for channel in added[1:]:
        rows[f"channel | ws | index {channel['channel']['index']}"] = channel["channel"]["id"]

    spec_iri = spec_record["equipment_spec"]["id"]
    equipment_iri = added[0]["equipment"]["id"]
    made = [api.create_equipment_spec(validate=False, name="Cycler 4200")["equipment_spec"]["id"] for _ in range(2)]
    rows["equipment-spec | create | name"] = _random_or(*made)
    rows["equipment-spec | save_record | name"] = _save_record_id(
        "equipment_spec", {"name": "Cycler 4200"}, root / "save-record"
    )
    made = [
        api.create_equipment(validate=False, equipment_spec_id=spec_iri, serial_number="MC-0001")["equipment"]["id"]
        for _ in range(2)
    ]
    rows["equipment | create | serial"] = _random_or(*made)
    rows["equipment | save_record | serial"] = _save_record_id(
        "equipment", {"equipment_spec_id": spec_iri, "serial_number": "MC-0001"}, root / "save-record"
    )
    rows["channel | create | index 1"] = api.create_channel(validate=False, equipment_id=equipment_iri, index=1)[
        "channel"
    ]["id"]
    rows["channel | save_record | index 1"] = _save_record_id(
        "channel", {"equipment_id": equipment_iri, "index": 1}, root / "save-record"
    )
    return rows


def _parameter_sets(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    fields = {"name": "Chen 2020 - graphite", "material_kind": "graphite", "claims": CLAIMS}
    rows["parameter-set | create | claim batch"] = api.create_parameter_set(validate=False, **fields)["parameter_set"][
        "id"
    ]
    ws = _workspace(root / "ws")
    rows["parameter-set | ws | claim batch"] = ws.add(
        "parameter_set", name="Chen 2020 - graphite", material="graphite", claims=CLAIMS
    )[0]["parameter_set"]["id"]
    rows["parameter-set | save_record | claim batch"] = _save_record_id("parameter_set", fields, root / "save-record")
    rows["parameter-set | save_record | parameter file"] = _save_record_id(
        "parameter_set", {"name": "Example BPX file", "parameters_sha256": "ab" * 32, "parts": []}, root / "save-record"
    )
    return rows


def _organizations(root: Path) -> dict[str, str]:
    return {
        "organization | create | name": api.create_organization(validate=False, name="Example Lab")["organization"][
            "id"
        ],
        "organization | save_record | name": _save_record_id(
            "organization", {"name": "Example Lab"}, root / "save-record"
        ),
    }


def _colliding_pairs(root: Path) -> dict[str, str]:
    """Records whose identity fields collide get IRIs seeded from their content."""
    rows: dict[str, str] = {}
    engine = Workspace(root / "engine")
    specs = {
        capacity: engine.cell_spec(
            manufacturer="Acme",
            model="X1",
            format="cylindrical",
            chemistry="li-ion",
            specs={"nominal_capacity": {"value": capacity, "unit": "Ah"}},
        )
        for capacity in (2.5, 3.0)
    }
    engine.render()
    for capacity, spec in specs.items():
        rows[f"cell-spec | engine | colliding pair, {capacity} Ah"] = str(spec.id)

    ws = _workspace(root / "ws")
    for name in ("a.csv", "b.csv"):
        path = root / "ws" / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"time_s,voltage_V\n0,{3.0 if name == 'a.csv' else 3.1}\n", encoding="utf-8")
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    tests = {name: ws.add("test", type="cycling", cell="C01", data=f"data/{name}")[0] for name in ("a.csv", "b.csv")}
    ws.save()
    for name, test in tests.items():
        rows[f"test | ws | colliding pair, {name}"] = str(test.id)
    datasets = sorted(str(d.id) for d in ws._ws.datasets)
    rows["dataset | ws | colliding pair"] = ", ".join(datasets)
    return rows


SCENARIOS: tuple[Callable[[Path], dict[str, str]], ...] = (
    _cell_specs,
    _cells,
    _batch_packages,
    _test_protocols,
    _tests_and_datasets,
    _material_specs,
    _materials,
    _electrode_specs,
    _electrodes,
    _component_families,
    _equipment,
    _parameter_sets,
    _organizations,
    _colliding_pairs,
)


def mint_all(root: Path) -> dict[str, str]:
    """Mint every case under *root* (an empty folder) and return case id -> IRI."""
    rows: dict[str, str] = {}
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for scenario in SCENARIOS:
            folder = root / scenario.__name__.strip("_")
            folder.mkdir(parents=True)
            found = scenario(folder)
            clash = set(found) & set(rows)
            assert not clash, f"case ids used twice: {sorted(clash)}"
            rows.update(found)
    return dict(sorted(rows.items()))


# ── The checks ────────────────────────────────────────────────────────────────


def _golden() -> dict[str, str]:
    if not GOLDEN_PATH.is_file():  # only while the script writes the fixture
        return {}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["iris"]


@pytest.fixture(scope="module")
def minted(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    return mint_all(tmp_path_factory.mktemp("golden-iris"))


def test_every_case_is_in_the_golden_table(minted: dict[str, str]) -> None:
    golden = _golden()
    assert sorted(set(minted) - set(golden)) == [], "a new case needs its IRI at 057b66a0 in the fixture"
    assert sorted(set(golden) - set(minted)) == [], "a case was dropped; keep it, or list why in MOVED"


def test_moves_name_real_cases() -> None:
    golden = _golden()
    for case, (now, why) in MOVED.items():
        assert case in golden, f"MOVED names an unknown case: {case}"
        assert now != golden[case], f"MOVED lists {case}, but its IRI is the golden one"
        assert why.strip(), f"MOVED gives no reason for {case}"


@pytest.mark.parametrize("case", sorted(_golden()))
def test_iri_holds_or_moves_as_listed(case: str, minted: dict[str, str]) -> None:
    expected = MOVED[case][0] if case in MOVED else _golden()[case]
    assert minted.get(case) == expected, (
        f"{case} mints {minted.get(case)}, expected {expected}. A seed change that moves this IRI "
        "lists it in MOVED with its reason and in the changelog."
    )


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        table = mint_all(Path(folder))
    print(json.dumps({"base": "057b66a0", "iris": table}, indent=2, ensure_ascii=False))
