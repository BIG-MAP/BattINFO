"""A Zenodo deposit plans its data files before it sends anything.

Each local file is one entry in the plan, named once, and every part of the
deposit takes that name: the upload, the zip archives of a large deposit, the
deposit graph, the RO-Crate and the rewrite of the dataset records. A record
finds its file by its resolved path, never by its name.

- Two files that share a name, or whose names differ only in case or Unicode
  normalisation, are two files in the deposit, in each dataset's own links.
- A file that two distributions name is uploaded once.
- A file inside a zip archive is a node of its own in the deposit graph, named
  by the archive's URL with the file's name there as the fragment, and it
  downloads from the archive's URL.
- A data file never takes the name of the deposit's own metadata files.
- A file name with a space, ``#``, ``?``, ``%`` or a non-ASCII character is
  percent-encoded in every URL, and an upload the HTTP layer refuses is a
  ZenodoError that names the file.

All offline: Zenodo and R2 are faked.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import re
import sys
import types
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pytest

import battinfo
from battinfo import zenodo as zmod
from battinfo._util import url_segment
from battinfo.ws import AuthoringWorkspace
from battinfo.zenodo import ZenodoClient, ZenodoError

pytestmark = pytest.mark.usefixtures("registry_holds_none")  # deposits ask the registry first (#483)

CREATORS = [{"name": "Doe, Jane"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
RECORD_URL = "https://zenodo.org/records/7"
METADATA_FILES = {"battinfo.json", "ro-crate-metadata.json"}
NFC_CAFE = unicodedata.normalize("NFC", "café.csv")
NFD_CAFE = unicodedata.normalize("NFD", "café.csv")
# One URL path segment as RFC 3986 allows it: unreserved and sub-delimiter
# characters, ':' and '@', and percent-escapes.
_SEGMENT = re.compile(r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@]|%[0-9A-F]{2})+")


class _FakeZenodo:
    """Stands in for ZenodoClient: keeps each uploaded file's bytes under its deposit name."""

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def client(self, *args: object, **kwargs: object) -> _FakeZenodo:
        return self

    def create_empty_deposit(self) -> dict:
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict, *, keep: dict | None = None) -> dict:
        self.uploaded = {name: Path(path).read_bytes() for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def list_files(self, deposit_id: int) -> list[dict]:
        return [
            {"filename": name, "checksum": hashlib.md5(data).hexdigest()}  # noqa: S324 - Zenodo's checksum
            for name, data in self.uploaded.items()
        ]

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        return {}

    def publish_deposit(self, deposit_id: int) -> dict:
        return {"doi": "10.5281/zenodo.7"}

    def graph(self) -> dict:
        return json.loads(self.uploaded["battinfo.json"])

    def crate_files(self) -> list[dict]:
        crate = json.loads(self.uploaded["ro-crate-metadata.json"])
        return [node for node in crate["@graph"] if node.get("@type") == "File"]

    def data_names(self) -> list[str]:
        return sorted(set(self.uploaded) - METADATA_FILES)


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _FakeZenodo:
    fake = _FakeZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


def _workspace(root: Path, files: dict[str, str]) -> AuthoringWorkspace:
    """A saved workspace with one cell and one cycling test per entry of *files*.

    *files* maps a serial number to the path of the test's data file inside
    *root*. Each file ends with its serial number, so no two hold the same bytes.
    """
    for serial, relative in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{CSV}# {serial}\n", encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=list(files))
    for serial, relative in files.items():
        ws.add("test", type="cycling", cell=serial, data=relative)
    ws.save()
    return ws


def _dataset_records(ws: AuthoringWorkspace) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted((ws._ws.source_root / "dataset").glob("*.json"))
    ]


def _local_files(ws: AuthoringWorkspace) -> dict[str, Path]:
    """Each dataset's data file, by dataset IRI, as the saved records name it."""
    files: dict[str, Path] = {}
    for record in _dataset_records(ws):
        url = record["dataset"]["distributions"][0]["content_url"]
        files[record["dataset"]["id"]] = Path(url2pathname(urlparse(url).path))
    return files


def _distributions(graph: dict) -> dict[str, list[dict]]:
    """The dcat:distribution nodes of each member dataset of a deposit graph, by dataset IRI."""
    return {
        node["@id"]: node["dcat:distribution"]
        for node in graph["@graph"]
        if "dcat:Dataset" in (node.get("@type") or []) and node.get("dcat:distribution")
    }


def _name_of(url: str, record_url: str = RECORD_URL) -> str:
    """The deposit file a deposit URL points at, checking that the URL is well formed."""
    parsed = urlparse(url)
    assert url.startswith(f"{record_url}/files/"), url
    assert not parsed.query and not parsed.fragment, url
    segment = url[len(f"{record_url}/files/") :]
    assert _SEGMENT.fullmatch(segment), url
    return unquote(segment)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Files that share a name ──────────────────────────────────────────────────


def test_two_files_with_one_name_are_two_files_in_the_deposit(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    names = zenodo.data_names()
    assert len(names) == 2 and "cycling.csv" in names
    renamed = next(name for name in names if name != "cycling.csv")
    assert re.fullmatch(r"[0-9a-f]{8}-cycling\.csv", renamed)
    assert sorted(zenodo.uploaded[name] for name in names) == sorted(p.read_bytes() for p in local.values())

    # The graph links each dataset to its own file.
    distributions = _distributions(zenodo.graph())
    for iri, path in local.items():
        [dist] = distributions[iri]
        name = _name_of(dist["dcat:downloadURL"])
        assert zenodo.uploaded[name] == path.read_bytes()
        assert dist["@id"] == dist["dcat:downloadURL"]
        assert dist["schema:name"] == name

    # So do the rewritten records, with the file's own checksum and provenance.
    for record in _dataset_records(ws):
        dataset = record["dataset"]
        [dist] = dataset["distributions"]
        data = local[dataset["id"]].read_bytes()
        assert zenodo.uploaded[_name_of(dist["content_url"])] == data
        assert dist["checksum"] == {"algorithm": "sha256", "value": _sha256(data)}
        assert dataset["access_url"] == dist["content_url"] == record["provenance"]["source_url"]

    # And the RO-Crate lists both, each with its own digest.
    crate = {unquote(node["@id"]): node for node in zenodo.crate_files()}
    assert sorted(crate) == names
    for name in names:
        assert crate[name]["name"] == name
        assert crate[name]["sha256"] == _sha256(zenodo.uploaded[name])
        assert crate[name]["contentSize"] == str(len(zenodo.uploaded[name]))


def test_two_files_with_one_name_stay_apart_in_a_zipped_deposit(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)  # two files are zipped
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cycling.zip"]
    with zipfile.ZipFile(io.BytesIO(zenodo.uploaded["cycling.zip"])) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    assert len(members) == 2 and "cycling.csv" in members
    assert sorted(members.values()) == sorted(p.read_bytes() for p in local.values())

    # Each dataset points at the archive and names its own member.
    distributions = _distributions(zenodo.graph())
    for iri, path in local.items():
        [dist] = distributions[iri]
        assert dist["dcat:downloadURL"] == f"{RECORD_URL}/files/cycling.zip"
        assert members[dist["schema:name"]] == path.read_bytes()
    [entity] = zenodo.crate_files()
    assert entity["@id"] == "cycling.zip"
    assert entity["sha256"] == _sha256(zenodo.uploaded["cycling.zip"])


# ── How the files are packed (bundle=) ───────────────────────────────────────


def _two_kinds(root: Path) -> list[tuple[str, str]]:
    """Three data files under *root*, two of one test kind and one of another, as plan locations."""
    locations = []
    for relative, kind in (("C01/cycling.csv", "cycling"), ("C02/cycling.csv", "cycling"), ("C03/pulse.csv", "hppc")):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{CSV}# {relative}\n", encoding="utf-8")
        locations.append((path.as_uri(), kind))
    return locations


@pytest.mark.parametrize(
    ("bundle", "archive_name", "threshold", "archives"),
    [
        ("by_kind", None, 1, ["cycling.zip", "hppc.zip"]),
        ("by_kind", None, 3, []),  # at the threshold nothing is zipped
        ("single", None, 1, ["data.zip"]),
        ("single", "study__data.zip", 1, ["study__data.zip"]),
        ("single", "study__data.zip", 3, ["study__data.zip"]),  # one archive however few the files
        ("none", None, 1, []),
    ],
)
def test_the_plan_packs_the_files_as_bundle_says(
    tmp_path: Path, bundle: str, archive_name: str | None, threshold: int, archives: list[str]
) -> None:
    from battinfo._deposit_files import build_deposit_file_plan

    plan = build_deposit_file_plan(
        _two_kinds(tmp_path),
        root=tmp_path,
        measure=False,
        zip_threshold=threshold,
        bundle=bundle,
        archive_name=archive_name,
    )
    assert plan.zipped is bool(archives)
    assert sorted(plan.archives()) == archives
    if archives:
        assert plan.deposited_names() == archives
        assert sum(len(members) for members in plan.archives().values()) == 3
    else:
        assert plan.deposited_names() == [entry.name for entry in plan.files]
        assert len(set(plan.deposited_names())) == 3
        assert all(entry.archive == "" for entry in plan.files)


@pytest.mark.parametrize(
    ("bundle", "archive_name", "message"),
    [
        ("tar", None, "is not one of 'by_kind', 'single', 'none'"),
        ("by_kind", "data.zip", "names the archive of bundle='single'"),
        ("none", "data.zip", "names the archive of bundle='single'"),
        ("single", "data.tar", "is not a file name ending in .zip"),
        ("single", "data/all.zip", "is not a file name ending in .zip"),
        ("single", ".zip", "is not a file name ending in .zip"),
        ("single", 7, "is not a file name ending in .zip"),
    ],
)
def test_a_bundle_the_plan_cannot_take_is_refused(
    tmp_path: Path, bundle: str, archive_name: object, message: str
) -> None:
    from battinfo._deposit_files import build_deposit_file_plan

    with pytest.raises(ValueError, match=re.escape(message)):
        build_deposit_file_plan(
            _two_kinds(tmp_path),
            root=tmp_path,
            measure=False,
            bundle=bundle,
            archive_name=archive_name,  # type: ignore[arg-type]
        )


def test_a_replaced_archive_name_still_names_the_archives_of_a_by_kind_deposit(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that replaced battinfo._deposit_files._archive_name keeps its archive names."""
    import battinfo._deposit_files as deposit_files

    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)
    monkeypatch.setattr(deposit_files, "_archive_name", lambda kind: "everything.zip")
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["everything.zip"]
    for dists in _distributions(zenodo.graph()).values():
        assert [dist["dcat:downloadURL"] for dist in dists] == [f"{RECORD_URL}/files/everything.zip"]


def test_a_single_archive_deposit_holds_one_zip_of_every_file(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS, bundle="single", archive_name="cells__data.zip")

    assert zenodo.data_names() == ["cells__data.zip"]
    with zipfile.ZipFile(io.BytesIO(zenodo.uploaded["cells__data.zip"])) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    assert sorted(members.values()) == sorted(p.read_bytes() for p in local.values())
    for iri, path in local.items():
        [dist] = _distributions(zenodo.graph())[iri]
        assert dist["dcat:downloadURL"] == f"{RECORD_URL}/files/cells__data.zip"
        assert members[dist["schema:name"]] == path.read_bytes()
    [entity] = zenodo.crate_files()
    assert entity["@id"] == "cells__data.zip"
    assert entity["sha256"] == _sha256(zenodo.uploaded["cells__data.zip"])


# ── The files of an archive in the deposit graph ─────────────────────────────

_DCAT = "http://www.w3.org/ns/dcat#"
_PROV = "http://www.w3.org/ns/prov#"
_SPDX = "http://spdx.org/rdf/terms#"


def _rdf(graph: dict):  # noqa: ANN202
    """A deposit graph as an RDF reader holds it."""
    from rdflib import Graph

    return Graph().parse(data=json.dumps(graph), format="json-ld")


def _distribution_nodes(rdf) -> set[str]:  # noqa: ANN001
    from rdflib import RDF, URIRef

    return {str(node) for node in rdf.subjects(RDF.type, URIRef(f"{_DCAT}Distribution"))}


@pytest.mark.parametrize(("bundle", "archive"), [("single", "data.zip"), ("by_kind", "cycling.zip")])
def test_each_file_in_an_archive_is_a_node_of_its_own(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch, bundle: str, archive: str
) -> None:
    """Every file of an archive downloads from the archive's URL, so that URL names none of them."""
    from rdflib import URIRef

    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)  # by_kind zips three files
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv", "C03": "C03/cell 03.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS, bundle=bundle)

    archive_url = f"{RECORD_URL}/files/{archive}"
    with zipfile.ZipFile(io.BytesIO(zenodo.uploaded[archive])) as packed:
        members = {info.filename: packed.read(info) for info in packed.infolist()}
    rdf = _rdf(zenodo.graph())

    # One node per file: the archive's URL, then the file's name in the archive.
    nodes = _distribution_nodes(rdf)
    assert len(nodes) == 3 and all(node.startswith(f"{archive_url}#") for node in nodes)
    assert {unquote(node.partition("#")[2]) for node in nodes} == set(members)
    assert {f"{archive_url}#cycling.csv", f"{archive_url}#cell%2003.csv"} < nodes
    # Two files called cycling.csv, in two folders, are two nodes.
    assert sum(node.endswith("-cycling.csv") for node in nodes) == 1

    # Each dataset has its own, which states that file's name, checksum, size and test.
    tests = set()
    for iri, path in local.items():
        data = path.read_bytes()
        [node] = rdf.objects(URIRef(iri), URIRef(f"{_DCAT}distribution"))
        [name] = rdf.objects(node, URIRef("https://schema.org/name"))
        assert str(node) in nodes and unquote(str(node).partition("#")[2]) == str(name)
        assert members[str(name)] == data
        assert [str(url) for url in rdf.objects(node, URIRef(f"{_DCAT}downloadURL"))] == [archive_url]
        [checksum] = rdf.objects(node, URIRef(f"{_SPDX}checksum"))
        assert [str(v) for v in rdf.objects(checksum, URIRef(f"{_SPDX}checksumValue"))] == [_sha256(data)]
        assert [int(size) for size in rdf.objects(node, URIRef(f"{_DCAT}byteSize"))] == [len(data)]
        [test] = rdf.objects(node, URIRef(f"{_PROV}wasGeneratedBy"))
        tests.add(test)
    assert len(tests) == 3
    # The archive is what a reader downloads, and the graph describes it as no file.
    assert not list(rdf.predicate_objects(URIRef(archive_url)))


def test_a_file_deposited_as_itself_is_the_node_its_download_url_names(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv", "C03": "C03/cell 03.csv"})
    ws.zenodo(token="placeholder", creators=CREATORS)

    names = zenodo.data_names()
    assert len(names) == 3  # under the threshold, so nothing is zipped
    assert _distribution_nodes(_rdf(zenodo.graph())) == {f"{RECORD_URL}/files/{url_segment(name)}" for name in names}
    for dists in _distributions(zenodo.graph()).values():
        [dist] = dists
        assert dist["@id"] == dist["dcat:downloadURL"] and "#" not in dist["@id"]


def test_a_processed_file_in_an_archive_names_the_raw_file_it_was_derived_from(tmp_path: Path) -> None:
    """Both files are in one archive, and the link goes from one file's node to the other's."""
    from rdflib import URIRef

    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    raw = tmp_path / "C01" / "cycling.ndax"
    raw.write_bytes(b"raw instrument file")
    [saved] = (ws._ws.source_root / "dataset").glob("*.json")
    record = json.loads(saved.read_text(encoding="utf-8"))
    record["dataset"]["distributions"].append(
        {"content_url": raw.as_uri(), "encoding_format": "application/octet-stream", "role": "raw"}
    )
    saved.write_text(json.dumps(record), encoding="utf-8")
    preview = json.loads(ws.preview_jsonld(creators=CREATORS, bundle="single").read_text(encoding="utf-8"))

    archive_url = "https://zenodo.org/records/RECORD_ID/files/data.zip"
    rdf = _rdf(preview)
    assert _distribution_nodes(rdf) == {f"{archive_url}#cycling.csv", f"{archive_url}#cycling.ndax"}
    derived = URIRef(f"{_PROV}wasDerivedFrom")
    assert list(rdf.subject_objects(derived)) == [
        (URIRef(f"{archive_url}#cycling.csv"), URIRef(f"{archive_url}#cycling.ndax"))
    ]


def test_a_file_in_a_kind_archive_of_a_package_is_a_node_of_its_own(tmp_path: Path) -> None:
    """Without a file plan, a file whose name is not deposited is in ``<kind>.zip`` when that is."""
    from battinfo.ws import _read_deposit_record_sets

    ws = _workspace(tmp_path, {"C01": "C01/first.csv", "C02": "C02/second 2.csv"})
    record_sets, _replaced = _read_deposit_record_sets(ws._ws.source_root)
    graph = AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=7,
        prereserved_doi="10.5281/zenodo.7",
        record_url=RECORD_URL,
        data_filenames=["cycling.zip"],
        title="Two cells",
        creators=CREATORS,
        license="cc-by-4.0",
    )

    archive_url = f"{RECORD_URL}/files/cycling.zip"
    assert _distribution_nodes(_rdf(graph)) == {f"{archive_url}#first.csv", f"{archive_url}#second%202.csv"}
    for dists in _distributions(graph).values():
        [dist] = dists
        assert dist["dcat:downloadURL"] == archive_url


def test_the_preview_names_the_single_archive_the_deposit_holds(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cell 02.csv"})
    preview = json.loads(
        ws.preview_jsonld(creators=CREATORS, bundle="single", archive_name="all data.zip").read_text(encoding="utf-8")
    )
    placeholder = "https://zenodo.org/records/RECORD_ID"
    urls = {dist["dcat:downloadURL"] for dists in _distributions(preview).values() for dist in dists}
    assert urls == {f"{placeholder}/files/all%20data.zip"}


def test_an_unzipped_deposit_over_the_threshold_keeps_each_file(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)  # by_kind would zip the two files
    ws = _workspace(tmp_path, {"C01": "C01/a.csv", "C02": "C02/b.csv"})
    ws.zenodo(token="placeholder", creators=CREATORS, bundle="none")
    assert zenodo.data_names() == ["a.csv", "b.csv"]


def test_an_unzipped_deposit_over_the_zenodo_limit_warns_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("Zenodo was contacted")

    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", no_client)
    monkeypatch.setattr("battinfo.ws._ZENODO_FILE_LIMIT", 3)  # two data files and the two metadata files
    ws = _workspace(tmp_path, {"C01": "C01/a.csv", "C02": "C02/b.csv"})
    with (
        pytest.warns(UserWarning, match=r"bundle='none' the deposit holds 4 files \(2 data files") as caught,
        pytest.raises(AssertionError, match="Zenodo was contacted"),
    ):
        ws.zenodo(token="placeholder", creators=CREATORS, bundle="none")
    [warning] = [w for w in caught if "bundle='none'" in str(w.message)]
    assert "bundle='by_kind'" in str(warning.message) and "bundle='single'" in str(warning.message)
    assert "at most 3 files in one record" in capsys.readouterr().out

    # by_kind leaves two files unzipped too, so it warns, and names the packing that helps.
    with pytest.warns(UserWarning, match=r"The deposit holds 4 files \(2 data files, .*Pass bundle='single'"):
        ws.preview_jsonld(creators=CREATORS, bundle="by_kind")
    capsys.readouterr()
    # One archive, and a deposit within the limit, do not warn.
    ws.preview_jsonld(creators=CREATORS, bundle="single")
    monkeypatch.setattr("battinfo.ws._ZENODO_FILE_LIMIT", 100)
    ws.preview_jsonld(creators=CREATORS, bundle="none")
    assert "files in one record" not in capsys.readouterr().out


def test_a_bundle_zenodo_cannot_take_is_refused_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", lambda *a, **k: pytest.fail("Zenodo was contacted"))
    ws = _workspace(tmp_path, {"C01": "C01/a.csv"})
    with pytest.raises(ValueError, match="bundle='zip'"):
        ws.zenodo(token="placeholder", creators=CREATORS, bundle="zip")
    with pytest.raises(ValueError, match="archive_name="):
        ws.zenodo(token="placeholder", creators=CREATORS, archive_name="data.zip")
    with pytest.raises(ValueError, match="bundle='zip'"):
        ws.preview_jsonld(creators=CREATORS, bundle="zip")
    with pytest.raises(ValueError, match="bundle='zip'"):
        ws.preview_rocrate(creators=CREATORS, bundle="zip")


@pytest.mark.parametrize(
    ("first", "second"),
    [("Data.csv", "data.csv"), (NFC_CAFE, NFD_CAFE)],
    ids=["case", "unicode-normalisation"],
)
def test_names_a_file_system_takes_for_one_are_told_apart(
    tmp_path: Path, zenodo: _FakeZenodo, first: str, second: str
) -> None:
    """Windows and macOS ignore case, and macOS Unicode normalisation, when they compare names."""
    ws = _workspace(tmp_path, {"C01": f"C01/{first}", "C02": f"C02/{second}"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    names = zenodo.data_names()
    assert len({unicodedata.normalize("NFC", name).casefold() for name in names}) == 2
    assert sorted(zenodo.uploaded[name] for name in names) == sorted(p.read_bytes() for p in local.values())
    for iri, path in local.items():
        [dist] = _distributions(zenodo.graph())[iri]
        assert zenodo.uploaded[_name_of(dist["dcat:downloadURL"])] == path.read_bytes()


def test_a_file_two_distributions_name_is_deposited_once(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    # A second dataset names the same file twice, once as a raw file.
    dataset_dir = ws._ws.source_root / "dataset"
    [saved] = dataset_dir.glob("*.json")
    record = json.loads(saved.read_text(encoding="utf-8"))
    record["dataset"]["id"] = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"
    [dist] = record["dataset"]["distributions"]
    record["dataset"]["distributions"] = [dist, {**dist, "role": "raw"}]
    (dataset_dir / "dataset-aaaa-bbbb-cccc-dddd.json").write_text(json.dumps(record), encoding="utf-8")
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cycling.csv"]
    assert len(zenodo.crate_files()) == 1
    url = f"{RECORD_URL}/files/cycling.csv"
    urls = [d["content_url"] for r in _dataset_records(ws) for d in r["dataset"]["distributions"]]
    assert urls == [url, url, url]


def test_a_data_file_never_takes_the_name_of_the_deposit_metadata(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    # Point the dataset at a data file that happens to be called battinfo.json.
    data = tmp_path / "C01" / "battinfo.json"
    (tmp_path / "C01" / "cycling.csv").rename(data)
    [saved] = (ws._ws.source_root / "dataset").glob("*.json")
    text = saved.read_text(encoding="utf-8").replace("cycling.csv", "battinfo.json")
    saved.write_text(text, encoding="utf-8")
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert "@graph" in zenodo.graph()  # the deposit graph, not the data file
    [name] = zenodo.data_names()
    assert re.fullmatch(r"[0-9a-f]{8}-battinfo\.json", name)
    assert zenodo.uploaded[name] == data.read_bytes()


# ── File names in URLs ────────────────────────────────────────────────────────

_NAMES_TO_ESCAPE = [
    pytest.param("cell 01.csv", id="space"),
    pytest.param("cell#3.csv", id="hash"),
    pytest.param("100%.csv", id="percent"),
    pytest.param(
        "cell?.csv",
        id="question-mark",
        marks=pytest.mark.skipif(sys.platform == "win32", reason="a Windows file name cannot hold '?'"),
    ),
    pytest.param("Zelle_25°C.csv", id="non-ascii"),
    pytest.param(NFD_CAFE, id="nfd"),
]


@pytest.mark.parametrize("name", _NAMES_TO_ESCAPE)
def test_a_file_name_is_percent_encoded_in_every_url(tmp_path: Path, zenodo: _FakeZenodo, name: str) -> None:
    ws = _workspace(tmp_path, {"C01": f"C01/{name}"})
    [path] = _local_files(ws).values()
    ws.zenodo(token="placeholder", creators=CREATORS)

    # The deposit stores the name itself, in composed (NFC) form.
    deposit_name = unicodedata.normalize("NFC", name)
    assert zenodo.data_names() == [deposit_name]
    assert zenodo.uploaded[deposit_name] == path.read_bytes()

    [dists] = _distributions(zenodo.graph()).values()
    [dist] = dists
    url = dist["dcat:downloadURL"]
    assert _name_of(url) == deposit_name
    assert dist["@id"] == url and dist["schema:name"] == deposit_name

    [record] = _dataset_records(ws)
    assert record["dataset"]["distributions"][0]["content_url"] == url
    assert record["provenance"]["source_url"] == url

    [entity] = zenodo.crate_files()
    assert _SEGMENT.fullmatch(entity["@id"]) and ":" not in entity["@id"]
    assert unquote(entity["@id"]) == entity["name"] == deposit_name


def test_the_preview_names_the_files_as_the_deposit_does(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv", "C03": "C03/cell 03.csv"})
    preview = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
    placeholder = "https://zenodo.org/records/RECORD_ID"
    previewed = sorted(
        _name_of(dist["dcat:downloadURL"], placeholder) for dists in _distributions(preview).values() for dist in dists
    )
    ws.zenodo(token="placeholder", creators=CREATORS)
    assert previewed == zenodo.data_names()


def test_an_artifact_in_the_workspace_is_linked_under_its_deposit_name(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    (tmp_path / "protocols").mkdir()
    (tmp_path / "protocols" / "cc protocol.json").write_text("{}", encoding="utf-8")
    protocol_dir = ws._ws.source_root / "test-protocol"
    protocol_dir.mkdir(exist_ok=True)
    (protocol_dir / "test-protocol-aaaa-bbbb-cccc-dddd.json").write_text(
        json.dumps(
            {
                "test_spec": {
                    "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                    "name": "CC",
                    "kind": "capacity_check",
                },
                "artifacts": [
                    {
                        "role": "source_protocol",
                        "format": "aurora-unicycler-json",
                        "locator": "protocols/cc protocol.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cc protocol.json", "cycling.csv"]
    plan = next(node for node in zenodo.graph()["@graph"] if "prov:Plan" in (node.get("@type") or []))
    [dist] = plan["dcat:distribution"]
    assert _name_of(dist["dcat:downloadURL"]["@id"]) == "cc protocol.json"


def test_url_segment_escapes_what_one_path_segment_cannot_hold() -> None:
    from battinfo._util import url_segment

    assert url_segment("cycling.bdf.csv") == "cycling.bdf.csv"
    assert url_segment("Cell 01 #3?.csv") == "Cell%2001%20%233%3F.csv"
    assert url_segment("100%.csv") == "100%25.csv"
    assert url_segment("a/b:c.csv") == "a%2Fb%3Ac.csv"  # one segment, never a scheme
    assert url_segment("Zelle_25°C.csv") == "Zelle_25%C2%B0C.csv"
    assert url_segment(NFD_CAFE) == "cafe%CC%81.csv"
    assert url_segment("run (1)+x.csv") == "run%20(1)+x.csv"


# ── The Zenodo upload ─────────────────────────────────────────────────────────


class _Reply:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _client(monkeypatch: pytest.MonkeyPatch, urlopen) -> ZenodoClient:  # noqa: ANN001
    monkeypatch.setattr(zmod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)  # no real backoff waits
    client = ZenodoClient(token="fake-token", sandbox=True)
    bucket = {"links": {"bucket": "https://sandbox.zenodo.org/api/files/b1"}}
    monkeypatch.setattr(client, "get_deposit", lambda deposit_id: bucket)
    return client


def test_the_bucket_upload_carries_the_name_percent_encoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_text(CSV, encoding="utf-8")
    second.write_text(CSV, encoding="utf-8")
    urls: list[str] = []

    def urlopen(req, timeout=None):  # noqa: ANN001
        urls.append(req.full_url)
        return _Reply(b'{"links": {}}')

    client = _client(monkeypatch, urlopen)
    client.upload_files(1, {first: "Cell 01 #3?.csv", second: "raw/run 1.csv"})
    assert urls == [
        "https://sandbox.zenodo.org/api/files/b1/Cell%2001%20%233%3F.csv",
        # A relative key keeps its folder.
        "https://sandbox.zenodo.org/api/files/b1/raw/run%201.csv",
    ]


@pytest.mark.parametrize(
    "error",
    [
        http.client.InvalidURL("URL can't contain control characters"),
        UnicodeEncodeError("ascii", "Zelle_25°C.csv", 8, 9, "ordinal not in range(128)"),
    ],
    ids=["invalid-url", "unicode"],
)
def test_an_upload_the_http_layer_refuses_is_a_zenodo_error_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    data = tmp_path / "data.csv"
    data.write_text(CSV, encoding="utf-8")
    calls: list[str] = []

    def urlopen(req, timeout=None):  # noqa: ANN001
        calls.append(req.full_url)
        raise error

    client = _client(monkeypatch, urlopen)
    with pytest.raises(ZenodoError, match="Zelle_25°C.csv") as excinfo:
        client.upload_files(1, {data: "Zelle_25°C.csv"})
    assert excinfo.value.__cause__ is error
    assert len(calls) == 1  # the same on every attempt, so not retried


# ── The plan ──────────────────────────────────────────────────────────────────


def test_the_plan_measures_each_file_once_and_finds_records_by_path(tmp_path: Path) -> None:
    from battinfo._deposit_files import build_deposit_file_plan

    data = tmp_path / "C01" / "cycling.csv"
    data.parent.mkdir()
    data.write_text(CSV, encoding="utf-8")
    other = tmp_path / "C02" / "cycling.csv"
    other.parent.mkdir()
    other.write_text(CSV, encoding="utf-8")
    gone = tmp_path / "gone.csv"
    plan = build_deposit_file_plan(
        [(data.as_uri(), "cycling"), (data.as_uri(), "cycling"), (gone.as_uri(), "cycling")],
        root=tmp_path,
    )
    [entry] = plan.files
    content = data.read_bytes()
    assert (entry.name, entry.segment, entry.size) == ("cycling.csv", "cycling.csv", len(content))
    assert entry.md5 == hashlib.md5(content).hexdigest()
    assert entry.sha256 == _sha256(content)
    assert plan.missing == [str(gone)]
    # A record finds the file by its path, spelled either way; a file of the same
    # name elsewhere, and a remote URL, are not it.
    assert plan.entry_for(data.as_uri()) is entry
    assert plan.entry_for("C01/cycling.csv") is entry
    assert plan.entry_for(other.as_uri()) is None
    assert plan.entry_for("https://zenodo.org/records/1/files/cycling.csv") is None


def test_a_name_an_earlier_deposit_gave_a_file_stays_with_it(tmp_path: Path) -> None:
    from battinfo._deposit_files import build_deposit_file_plan, path_key

    first, second = tmp_path / "C01" / "cycling.csv", tmp_path / "C02" / "cycling.csv"
    for path in (first, second):
        path.parent.mkdir()
        path.write_text(CSV, encoding="utf-8")
    # The new file comes first, so it would take the name...
    locations = [(second.as_uri(), "cycling"), (first.as_uri(), "cycling")]
    plan = build_deposit_file_plan(locations, root=tmp_path, measure=False)
    assert plan.entry_for(second.as_uri()).name == "cycling.csv"
    # ...unless the name is recorded for the file that had it.
    plan = build_deposit_file_plan(
        locations, root=tmp_path, measure=False, recorded_names={path_key(first): "cycling.csv"}
    )
    assert plan.entry_for(first.as_uri()).name == "cycling.csv"
    assert re.fullmatch(r"[0-9a-f]{8}-cycling\.csv", plan.entry_for(second.as_uri()).name)


# ── R2 object storage ─────────────────────────────────────────────────────────


class _FakeS3:
    """Stands in for a boto3 S3 client: keeps each object's sha256 under its key."""

    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class ClientError(Exception):
            pass

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if Key not in self.objects:
            raise self.exceptions.ClientError(Key)
        return {"Metadata": {"sha256": self.objects[Key]}}

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict, Config: object) -> None:  # noqa: N803
        self.objects[key] = ExtraArgs["Metadata"]["sha256"]


def test_r2_urls_carry_the_name_percent_encoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = _FakeS3()
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: s3  # type: ignore[attr-defined]
    transfer = types.ModuleType("boto3.s3.transfer")
    transfer.TransferConfig = lambda **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "boto3.s3", types.ModuleType("boto3.s3"))
    monkeypatch.setitem(sys.modules, "boto3.s3.transfer", transfer)
    for name, value in (
        ("R2_ENDPOINT", "https://r2.example"),
        ("R2_ACCESS_KEY_ID", "k"),
        ("R2_SECRET_ACCESS_KEY", "s"),
        ("R2_BUCKET", "b"),
        ("R2_PUBLIC_BASE_URL", "https://pub.example"),
    ):
        monkeypatch.setenv(name, value)
    ws = _workspace(tmp_path, {"C01": "C01/cell 01.csv", "C02": "C02/cell 01.csv"})
    ws.upload()

    for record in _dataset_records(ws):
        dataset = record["dataset"]
        url = f"https://pub.example/datasets/{dataset['short_id']}/cell%2001.csv"
        assert dataset["distributions"][0]["content_url"] == dataset["access_url"] == url
        assert record["provenance"]["source_url"] == url
    assert all(key.endswith("/cell 01.csv") for key in s3.objects) and len(s3.objects) == 2
