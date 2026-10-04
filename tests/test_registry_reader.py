"""The read side of a registry: listing, links, files, downloads, catalog.

Everything here runs against an in-memory stand-in for the registry, wired in
by replacing ``Registry._open``, so no test touches the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from battinfo.registry import Registry, RegistryFile, _cache_file, _record_ref, bdf_column_names

BASE = "https://registry.example"
FILES = "https://files.example"

DATASET = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"
TEST = "https://w3id.org/battinfo/test/eeee-ffff-gggg-hhhh"
CELL = "https://w3id.org/battinfo/cell/jjjj-kkkk-mmmm-nnnn"
SPEC = "https://w3id.org/battinfo/spec/pppp-qqqq-rrrr-ssss"

CSV_BYTES = (
    b"Test Time / s,Voltage / V,Current / A,Cycle Count / 1,Step Index / 1\n"
    b"0,3.0,1.0,1,1\n"
    b"1,3.1,1.0,1,1\n"
)
CSV_SHA = hashlib.sha256(CSV_BYTES).hexdigest()


class _Response(io.BytesIO):
    def __init__(self, body: bytes, headers: dict | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeRegistry:
    """Serves /resources, /resources/{type}/{id}, /health and file URLs."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.revision = 1
        self.file_bytes = CSV_BYTES
        self.summaries: dict[str, list[dict]] = {
            "dataset": [self._summary(DATASET, "dataset", "Cell 1 cycling data", {
                "license": "cc-by-4.0", "media_type": "text/csv", "record_url": f"{FILES}/cell1.bdf.csv",
            })],
            "test": [self._summary(TEST, "test", "Cycling", {"kind": "cycling"})],
            "cell": [self._summary(CELL, "cell", "Cell 1", {
                "name": "Cell 1", "cell_spec_id": SPEC, "manufacturer": "Acme", "model": "A1",
                "format": "coin", "chemistry": "Li-ion", "positive_electrode_basis": "NMC",
                "negative_electrode_basis": "graphite", "properties": {},
            })],
            "cell_spec": [self._summary(SPEC, "cell_spec", "Acme A1", {"format": "coin"}, benchmark={
                "properties": {"rated_capacity": {"value": 2500, "unit": "mAh"}},
            })],
        }
        self.details: dict[str, dict] = {
            "dataset/aaaa-bbbb-cccc-dddd": {
                "canonical_iri": DATASET,
                "resource_type": "dataset",
                "semantic_payload": {"battinfo_records": {"dataset": {"dataset": {"distributions": [{
                    "role": "processed", "content_url": f"{FILES}/cell1.bdf.csv", "name": "cell1.bdf.csv",
                    "encoding_format": "text/csv", "content_size": str(len(CSV_BYTES)),
                    "checksum": {"algorithm": "sha256", "value": CSV_SHA},
                }]}}}},
                "related_resources": [
                    {"relationship": "aboutCell", "resource_type": "cell", "canonical_iri": CELL},
                    {"relationship": "generatedByTest", "resource_type": "test", "canonical_iri": TEST},
                ],
                "distributions": [
                    {"title": "cell1.bdf.csv", "access_url": f"{FILES}/cell1.bdf.csv", "role": "processed",
                     "media_type": "text/csv"},
                    {"title": "cell1.png", "access_url": f"{FILES}/cell1.png", "role": "plot_static",
                     "media_type": "image/png"},
                ],
            },
        }

    @staticmethod
    def _summary(iri: str, rtype: str, title: str, metadata: dict, **extra: object) -> dict:
        return {"canonical_iri": iri, "canonical_id": iri.rsplit("/", 1)[1], "resource_type": rtype,
                "title": title, "metadata": metadata, **extra}

    def open(self, url: str, *, retries: int = 2) -> _Response:  # noqa: ARG002
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        if url.startswith(FILES):
            return _Response(self.file_bytes)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/health":
            return _Response(json.dumps({"corpus_revision": self.revision}).encode())
        if parsed.path == "/resources":
            rows = self.summaries.get(query["resource_type"][0], [])
            if "kind" in query:
                rows = [r for r in rows if r["metadata"].get("kind") == query["kind"][0]]
            limit, offset = int(query["limit"][0]), int(query.get("offset", ["0"])[0])
            body = json.dumps(rows[offset:offset + limit]).encode()
            return _Response(body, {"X-Total-Count": str(len(rows))})
        key = parsed.path.removeprefix("/resources/")
        if key in self.details:
            return _Response(json.dumps(self.details[key]).encode())
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]


@pytest.fixture()
def fake() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture()
def reg(fake: FakeRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry(BASE, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(registry, "_open", fake.open)
    return registry


# ── Record references ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (DATASET, ("dataset", "aaaa-bbbb-cccc-dddd")),
        (DATASET + "/", ("dataset", "aaaa-bbbb-cccc-dddd")),
        ("dataset/aaaa-bbbb-cccc-dddd", ("dataset", "aaaa-bbbb-cccc-dddd")),
        ("aaaa-bbbb-cccc-dddd", (None, "aaaa-bbbb-cccc-dddd")),
        ({"canonical_iri": SPEC}, ("spec", "pppp-qqqq-rrrr-ssss")),
        ({"canonical_id": "aaaa-bbbb-cccc-dddd", "resource_type": "dataset"}, ("dataset", "aaaa-bbbb-cccc-dddd")),
    ],
)
def test_record_ref_accepts_iris_ids_and_records(ref: object, expected: tuple) -> None:
    assert _record_ref(ref) == expected


def test_record_ref_rejects_what_is_not_a_record() -> None:
    with pytest.raises(ValueError, match="not a record IRI or id"):
        _record_ref("https://example.org/not-a-record")


def test_get_needs_a_type_for_a_bare_id(reg: Registry) -> None:
    with pytest.raises(ValueError, match="record_type is required"):
        reg.get("aaaa-bbbb-cccc-dddd")
    assert reg.get("aaaa-bbbb-cccc-dddd", record_type="dataset")["canonical_iri"] == DATASET


# ── Listing and links ─────────────────────────────────────────────────────────

def test_list_pages_until_the_corpus_is_exhausted(reg: Registry, fake: FakeRegistry) -> None:
    fake.summaries["test"] = [
        fake._summary(f"https://w3id.org/battinfo/test/{i:04d}-0000-0000-0000", "test", f"t{i}", {"kind": "cycling"})
        for i in range(2300)
    ]
    rows = reg.list("test")
    assert len(rows) == 2300
    offsets = [urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["offset"][0] for u in fake.calls]
    assert offsets == ["0", "1000", "2000"]


def test_list_passes_the_kind_filter(reg: Registry, fake: FakeRegistry) -> None:
    fake.summaries["test"].append(fake._summary(TEST.replace("eeee", "zzzz"), "test", "GITT", {"kind": "gitt"}))
    assert [t["title"] for t in reg.list("test", kind="cycling")] == ["Cycling"]
    assert "kind=cycling" in fake.calls[-1]


def test_links_group_targets_by_type(reg: Registry) -> None:
    assert reg.links(DATASET) == {"cell": [CELL], "test": [TEST]}


# ── Files ─────────────────────────────────────────────────────────────────────

def test_files_merge_checksum_and_size_from_the_record_body(reg: Registry) -> None:
    files = reg.files(DATASET)
    assert files[0] == RegistryFile(
        name="cell1.bdf.csv", url=f"{FILES}/cell1.bdf.csv", role="processed",
        media_type="text/csv", sha256=CSV_SHA, size=len(CSV_BYTES),
    )
    assert [f.role for f in files] == ["processed", "plot_static"]
    assert [f.name for f in reg.files(DATASET, role="processed")] == ["cell1.bdf.csv"]


def test_download_verifies_then_reuses_the_cached_copy(reg: Registry, fake: FakeRegistry) -> None:
    path = reg.download(DATASET)
    assert path.read_bytes() == CSV_BYTES
    assert path.parent.name == "aaaa-bbbb-cccc-dddd"
    fetches = sum(u.startswith(FILES) for u in fake.calls)
    assert reg.download(DATASET) == path
    assert sum(u.startswith(FILES) for u in fake.calls) == fetches  # served from the cache


def test_download_rejects_bytes_that_do_not_match_the_record(reg: Registry, fake: FakeRegistry) -> None:
    fake.file_bytes = CSV_BYTES + b"tampered\n"
    with pytest.raises(OSError, match="checksum mismatch"):
        reg.download(DATASET)
    assert not list((reg.cache_dir / "files").rglob("*.csv"))  # nothing left behind
    assert not list((reg.cache_dir / "files").rglob("*.part"))


def test_download_replaces_a_cached_copy_that_went_bad(reg: Registry) -> None:
    path = reg.download(DATASET)
    path.write_bytes(b"corrupted")
    assert reg.download(DATASET).read_bytes() == CSV_BYTES


def test_download_reports_a_dataset_with_no_data_file(reg: Registry) -> None:
    with pytest.raises(FileNotFoundError, match="no file with role 'raw'"):
        reg.download(DATASET, role="raw")


# ── Reading ───────────────────────────────────────────────────────────────────

def test_read_returns_machine_readable_column_names(reg: Registry) -> None:
    pytest.importorskip("pandas")
    df = reg.read(DATASET)
    assert list(df.columns) == ["test_time_second", "voltage_volt", "current_ampere", "cycle_count", "step_index"]
    assert len(df) == 2
    as_published = reg.read(DATASET, bdf_names=False)
    assert list(as_published.columns)[0] == "Test Time / s"


def test_bdf_column_names_converts_unit_variants() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({
        "test_time_millisecond": [0, 1500],
        "cycle_dimensionless": [0, 1],
        "voltage_volt": [3.0, 3.1],
        "my_lab_column": [1, 2],
    })
    out = bdf_column_names(df)
    assert list(out.columns) == ["test_time_second", "cycle_count", "voltage_volt", "my_lab_column"]
    assert out["test_time_second"].tolist() == [0.0, 1.5]
    assert list(df.columns)[0] == "test_time_millisecond"  # the input frame is left alone


def test_bdf_column_names_never_overwrites_an_existing_column() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Voltage / V": [3.0], "voltage_volt": [9.9]})
    out = bdf_column_names(df)
    assert list(out.columns) == ["Voltage / V", "voltage_volt"]
    assert out["voltage_volt"].tolist() == [9.9]


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_catalog_joins_dataset_test_cell_and_spec(reg: Registry) -> None:
    pytest.importorskip("pandas")
    catalog = reg.catalog()
    assert len(catalog) == 1
    row = catalog.iloc[0]
    assert row.dataset_id == DATASET
    assert (row.test_id, row.test_kind) == (TEST, "cycling")
    assert (row.cell_id, row.cell_spec_id) == (CELL, SPEC)
    assert (row.format, row.chemistry, row.positive_electrode_basis) == ("coin", "Li-ion", "NMC")
    assert (row.file_name, row.sha256, row.size_bytes) == ("cell1.bdf.csv", CSV_SHA, len(CSV_BYTES))
    # The cell states no capacity, so the figure comes from its spec, in Ah.
    assert row.nominal_capacity_ah == pytest.approx(2.5)
    assert row.nominal_capacity_source == "rated_capacity"


def test_catalog_prefers_the_capacity_stated_on_the_cell(reg: Registry, fake: FakeRegistry) -> None:
    pytest.importorskip("pandas")
    fake.summaries["cell"][0]["metadata"]["properties"] = {"nominal_capacity": {"value": 2.4, "unit": "Ah"}}
    row = reg.catalog().iloc[0]
    assert row.nominal_capacity_ah == pytest.approx(2.4)
    assert row.nominal_capacity_source == "nominal_capacity"


def test_catalog_is_cached_until_the_registry_changes(reg: Registry, fake: FakeRegistry) -> None:
    pytest.importorskip("pandas")
    reg.catalog()
    fake.calls.clear()
    reg.catalog()
    assert not any("/resources/dataset/" in u for u in fake.calls)  # no record was re-read

    fake.revision = 2
    fake.calls.clear()
    reg.catalog()
    assert any("/resources/dataset/" in u for u in fake.calls)

    fake.calls.clear()
    reg.catalog(refresh=True)
    assert any("/resources/dataset/" in u for u in fake.calls)


def test_catalog_keeps_a_dataset_whose_record_cannot_be_read(reg: Registry, fake: FakeRegistry) -> None:
    pytest.importorskip("pandas")
    fake.details.clear()
    row = reg.catalog().iloc[0]
    assert row.dataset_id == DATASET
    assert row.file_url == f"{FILES}/cell1.bdf.csv"  # from the summary
    assert row.test_id is None


def test_download_shortens_a_name_that_would_exceed_the_path_limit(tmp_path: Path) -> None:
    folder = tmp_path / "files" / "aaaa-bbbb-cccc-dddd"
    short = _cache_file(folder, "cell1.bdf.parquet")
    assert short == folder / "cell1.bdf.parquet"

    long_name = "x" * 300 + ".bdf.parquet"
    shortened = _cache_file(folder, long_name)
    assert shortened.parent == folder
    assert shortened.name.endswith(".bdf.parquet")
    assert len(shortened.name) < 40
    assert _cache_file(folder, long_name) == shortened  # stable, so the cache is reused


def test_bdf_column_names_keeps_legacy_labels_under_their_published_name() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Step Index / 1": [1], "Step Capacity / Ah": [0.1], "Cumulative Capacity / Ah": [0.1]})
    assert list(bdf_column_names(df).columns) == ["step_index", "step_capacity_ah", "cumulative_capacity_ah"]
