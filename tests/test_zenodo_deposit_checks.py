"""ws.zenodo() deposits every record or none, and checks the deposit's files before it publishes.

- A record the deposit graph cannot convert, or a distribution entry that is
  not an object with a ``content_url``, is named in a refusal before anything
  is sent, for a draft as for a publish. ``ws.preview_jsonld()`` lists it as
  an error, and the graph builder behind the package builders refuses it.
- A Unix time in milliseconds is left out of the graph with a warning, not the
  test that holds it. An ISO 8601 time is kept as it is. Validation under the
  strict policy reports a time no date can be made of as an error.
- After the upload, the deposit's file list is compared with what was sent
  and with the graph. A publish is refused before the DOI is minted when a
  file is missing or its md5 differs; a draft gets a warning that lists the
  problems. A distribution hosted elsewhere on the web passes.

All offline: Zenodo's HTTP API is answered in memory, so the real client runs.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import pytest

import battinfo
from battinfo import zenodo as zmod
from battinfo._deposit_files import Omission, deposit_file_problems, distribution_problem
from battinfo.validate.semantic import validate_semantic_report
from battinfo.ws import AuthoringWorkspace, _read_deposit_record_sets, _unix_to_iso

pytestmark = pytest.mark.usefixtures("registry_holds_none")  # deposits ask the registry first (#483)

API = "https://zenodo.org/api"
BUCKET = f"{API}/files/bucket-7"
RECORD_URL = "https://zenodo.org/records/7"
CREATORS = [{"name": "Doe, Jane", "affiliation": "Example Lab"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
MS_START, MS_END = 1772442000000, 1772442600000  # 2 March 2026, in milliseconds
PUBLISH_REQUEST = "POST /deposit/depositions/7/actions/publish"


class _Reply:
    def __init__(self, payload: object) -> None:
        self._body = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Zenodo's file checksum


class _ZenodoAPI:
    """Zenodo's deposit API for one deposit (id 7), answered in memory.

    Logs each request as ``"METHOD path"``, the path relative to the API root,
    and keeps the files the bucket receives. A name in ``lose`` is accepted
    but not kept, and one in ``corrupt`` is kept with other bytes, as if the
    upload had gone wrong without an error.
    """

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.files: dict[str, bytes] = {}
        self.published = False
        self.lose: set[str] = set()
        self.corrupt: set[str] = set()
        self.on: dict[str, Callable[[], None]] = {}

    def _deposit(self) -> dict:
        return {
            "id": 7,
            "record_id": 7,
            "state": "done" if self.published else "unsubmitted",
            "submitted": self.published,
            "links": {"bucket": BUCKET},
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}},
        }

    def urlopen(self, request, timeout: float | None = None) -> _Reply:  # noqa: ANN001
        method, url = request.get_method(), request.full_url
        assert url.startswith(f"{API}/"), url
        path = url[len(API) :]
        line = f"{method} {path}"
        self.requests.append(line)
        if line in self.on:
            self.on[line]()
        if url.startswith(f"{BUCKET}/") and method == "PUT":
            name = unquote(url[len(BUCKET) + 1 :])
            if name not in self.lose:
                self.files[name] = request.data + (b"!" if name in self.corrupt else b"")
            return _Reply({"key": name, "links": {"self": url}})
        if line in ("POST /deposit/depositions", "GET /deposit/depositions/7"):
            return _Reply(self._deposit())
        if line == "PUT /deposit/depositions/7":
            return _Reply({**self._deposit(), "metadata": json.loads(request.data)["metadata"]})
        if line == "GET /deposit/depositions/7/files":
            return _Reply([{"id": name, "filename": name, "checksum": _md5(data)} for name, data in self.files.items()])
        if method == "DELETE" and path.startswith("/deposit/depositions/7/files/"):
            self.files.pop(unquote(path.rsplit("/", 1)[-1]), None)
            return _Reply(None)
        if line == PUBLISH_REQUEST:
            self.published = True
            return _Reply({**self._deposit(), "doi": "10.5281/zenodo.7"})
        raise AssertionError(f"unexpected request: {method} {url}")

    def graph(self) -> dict:
        return json.loads(self.files["battinfo.json"])


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> _ZenodoAPI:
    fake = _ZenodoAPI()
    monkeypatch.setattr(zmod.urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


@pytest.fixture(autouse=True)
def user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI's ~/.battinfo/config.yaml, moved into the test's folder, so no real one is read."""
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", tmp_path / "home" / ".battinfo" / "config.yaml")


def _workspace(root: Path, *, second_file: bool = False) -> AuthoringWorkspace:
    """Cell C01 with a cycling test on C01/cycling.csv and a capacity check without data.

    With *second_file*, an HPPC test on C01/hppc.csv as well, so the
    workspace has two datasets.
    """
    (root / "C01").mkdir(parents=True)
    (root / "C01" / "cycling.csv").write_text(CSV, encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    if second_file:
        (root / "C01" / "hppc.csv").write_text(CSV + "120,3.6,0.001\n", encoding="utf-8")
        ws.add("test", type="hppc", cell="C01", data="C01/hppc.csv")
    ws.add("test", type="capacity_check", cell="C01")
    ws.save()
    return ws


def _saved(ws: AuthoringWorkspace, folder: str) -> list[tuple[Path, dict]]:
    return [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((ws._ws.source_root / folder).glob("*.json"))
    ]


def _edit_test(ws: AuthoringWorkspace, kind: str, **fields: object) -> str:
    """Set *fields* on the saved test of *kind*, as a tool that writes records itself would; return its IRI."""
    for path, record in _saved(ws, "test"):
        if record["test"]["kind"] == kind:
            record["test"].update(fields)
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            return record["test"]["id"]
    raise AssertionError(f"no {kind} test")


def _edit_dataset(ws: AuthoringWorkspace, data_file: str, edit: Callable[[dict], None]) -> str:
    """Apply *edit* to the saved dataset whose first file is *data_file*; return its IRI."""
    for path, record in _saved(ws, "dataset"):
        if record["dataset"]["distributions"][0]["content_url"].endswith(data_file):
            edit(record["dataset"])
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            return record["dataset"]["id"]
    raise AssertionError(f"no dataset for {data_file}")


def _content_urls(ws: AuthoringWorkspace) -> list[str]:
    return [
        dist["content_url"] for _path, record in _saved(ws, "dataset") for dist in record["dataset"]["distributions"]
    ]


def _state(ws: AuthoringWorkspace) -> dict | None:
    path = ws._root / ".battinfo" / "zenodo.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _node(graph: dict, iri: str) -> dict | None:
    return next((node for node in graph["@graph"] if node.get("@id") == iri), None)


# ── Records the graph cannot convert ──────────────────────────────────────────


@pytest.mark.parametrize("publish", [False, True], ids=["draft", "publish"])
def test_a_record_the_graph_cannot_convert_is_refused_before_anything_is_sent(
    tmp_path: Path, api: _ZenodoAPI, publish: bool
) -> None:
    ws = _workspace(tmp_path)
    # Not a conformance object, so the test cannot be converted. It used to be
    # left out of the deposit without a word: nothing else points at it.
    test_iri = _edit_test(ws, "capacity_check", conformance=["conformant"])

    with (
        pytest.warns(UserWarning, match=f"test record {test_iri} could not be converted"),
        pytest.raises(RuntimeError) as excinfo,
    ):
        ws.zenodo(token="placeholder", creators=CREATORS, publish=publish)

    message = str(excinfo.value)
    assert message.startswith(f"Refusing to {'publish' if publish else 'deposit'}: 1 record(s) ")
    assert f"test {test_iri}: AttributeError" in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert api.requests == [] and _state(ws) is None


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ("file:///nowhere/extra.csv", "distribution 2 is not an object ('file:///nowhere/extra.csv')"),
        ({"encoding_format": "text/csv"}, "distribution 2 has no content_url"),
        ({"content_url": 42, "encoding_format": "text/csv"}, "distribution 2 has a content_url that is not text (42)"),
    ],
    ids=["text", "no-content-url", "number"],
)
def test_a_malformed_distribution_entry_is_refused(tmp_path: Path, api: _ZenodoAPI, entry: object, reason: str) -> None:
    ws = _workspace(tmp_path, second_file=True)
    # The dataset used to leave the deposit graph, and its files the deposit,
    # without a word: the other dataset kept the graph valid.
    dataset_iri = _edit_dataset(ws, "cycling.csv", lambda ds: ds["distributions"].append(entry))

    with pytest.raises(RuntimeError) as excinfo:
        ws.zenodo(token="placeholder", creators=CREATORS)

    message = str(excinfo.value)
    assert message.startswith("Refusing to deposit: 1 record(s) ")
    assert f"dataset {dataset_iri}: {reason}" in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert api.requests == []


def test_the_preview_lists_what_the_deposit_would_leave_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = _workspace(tmp_path, second_file=True)
    # The cycling test's dataset points at it, so the graph has a reference to
    # a test it left out.
    test_iri = _edit_test(ws, "cycling", conformance=["conformant"])
    dataset_iri = _edit_dataset(ws, "hppc.csv", lambda ds: ds["distributions"].append("hppc-raw.ndax"))
    capsys.readouterr()

    with pytest.warns(UserWarning):
        graph = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))

    out = capsys.readouterr().out
    assert f"ERROR   left out of the deposit: test {test_iri}: AttributeError" in out
    assert f"ERROR   left out of the deposit: dataset {dataset_iri}: distribution 2 is not an object" in out
    # Each problem is listed once (the plan's WARNING line, then the ERROR), and
    # the test left out is not reported as not found locally.
    assert out.count(f"dataset {dataset_iri}: distribution 2") == 2
    assert f"WARNING: left out of the deposit: dataset {dataset_iri}: distribution 2" in out
    assert "Not found locally" not in out
    # The rest of the dataset stays in the preview.
    assert _node(graph, test_iri) is None and _node(graph, dataset_iri) is not None


def test_the_graph_builder_refuses_unless_asked_to_collect(tmp_path: Path) -> None:
    """The package and local publication builders call it without a list, so they refuse."""
    ws = _workspace(tmp_path, second_file=True)
    test_iri = _edit_test(ws, "capacity_check", conformance=["conformant"])
    record_sets, _ = _read_deposit_record_sets(ws._ws.source_root)
    common = {"zenodo_record_id": 7, "prereserved_doi": "10.5281/zenodo.7", "record_url": RECORD_URL}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match=r"1 record\(s\) could not be converted") as excinfo:
            AuthoringWorkspace._assemble_zenodo_jsonld(record_sets, **common)
        assert f"test {test_iri}: AttributeError" in str(excinfo.value)

        omissions: list[Omission] = []
        graph = AuthoringWorkspace._assemble_zenodo_jsonld(record_sets, omissions=omissions, **common)
    assert [(o.kind, o.record) for o in omissions] == [("test", test_iri)]
    assert _node(graph, test_iri) is None


def test_the_zenodo_package_builder_refuses_a_record_it_cannot_convert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battinfo import Cell, CellSpec, Dataset, Test, publication
    from battinfo.bundle import ProvenanceInfo, ZenodoCellRecord, ZenodoDatasetEntry
    from battinfo.publication import build_zenodo_package

    spec_id = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
    cell_id, test_id = "https://w3id.org/battinfo/cell/ci-001", "https://w3id.org/battinfo/test/t-001"
    record = ZenodoCellRecord(
        cell_spec=CellSpec(
            id=spec_id,
            name="Energizer CR2032",
            manufacturer="Energizer",
            model="CR2032",
            format="coin",
            chemistry="Li-primary",
            source=ProvenanceInfo(type="datasheet"),
        ),
        datasets=[
            ZenodoDatasetEntry(
                cell_instances=[
                    Cell(
                        id=cell_id,
                        name="sn-001",
                        cell_spec_id=spec_id,
                        serial_number="sn-001",
                        source=ProvenanceInfo(type="measurement"),
                    )
                ],
                test=Test(
                    id=test_id,
                    name="test 001",
                    test_kind="capacity_check",
                    cell_instance_id=cell_id,
                    source=ProvenanceInfo(type="measurement"),
                ),
                dataset=Dataset(
                    id="https://w3id.org/battinfo/dataset/d-001",
                    name="dataset 001",
                    cell_instance_id=cell_id,
                    test_id=test_id,
                    source=ProvenanceInfo(type="measurement"),
                ),
            )
        ],
    )
    real = publication._record_sets_from_zenodo_record

    def _with_a_bad_test(*args: object, **kwargs: object) -> tuple[dict, list[str]]:
        record_sets, names = real(*args, **kwargs)
        record_sets["test"][0]["test"]["conformance"] = ["conformant"]
        return record_sets, names

    monkeypatch.setattr(publication, "_record_sets_from_zenodo_record", _with_a_bad_test)
    raw = tmp_path / "raw.csv"
    raw.write_text("t,V\n0,3.0\n", encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match=f"test {test_id}: AttributeError"):
            build_zenodo_package(record, tmp_path / "staging", [(raw, None)])


# ── Times ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1772442000, "2026-03-02T09:00:00Z"),
        (1772442000.75, "2026-03-02T09:00:00Z"),
        ("1772442000", "2026-03-02T09:00:00Z"),
        ("2026-03-01T10:00:00Z", "2026-03-01T10:00:00Z"),
        (" 2026-03-01 ", "2026-03-01"),
        (None, None),
        ("", None),
        (True, None),
    ],
)
def test_unix_to_iso_reads_seconds_and_keeps_iso_strings(value: object, expected: str | None) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # none of these warns
        assert _unix_to_iso(value) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [MS_START, float(MS_START), str(MS_START), float("inf"), -(10**15)])
def test_unix_to_iso_leaves_out_a_time_no_date_can_hold(value: object) -> None:
    with pytest.warns(UserWarning, match=r"started_at of test X = .* is left out"):
        assert _unix_to_iso(value, what="started_at of test X") is None  # type: ignore[arg-type]


def test_a_test_timed_in_milliseconds_keeps_its_node(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    test_iri = _edit_test(ws, "capacity_check", started_at=MS_START, ended_at=MS_END)

    with pytest.warns(UserWarning, match=f"started_at of test {test_iri} = {MS_START}"):
        result = ws.zenodo(token="placeholder", creators=CREATORS)

    assert not result.published
    node = _node(api.graph(), test_iri)
    assert node is not None and "BatteryTest" in node["@type"]
    assert "prov:startedAtTime" not in node and "prov:endedAtTime" not in node


def test_an_iso_deviation_time_is_kept_as_it_is(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    test_iri = _edit_test(
        ws,
        "capacity_check",
        conformance={
            "status": "non-conformant",
            "deviations": [{"category": "power_outage", "occurred_at": "2026-03-01T10:00:00Z"}],
        },
    )
    graph = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
    node = _node(graph, test_iri)
    assert node is not None
    [deviation] = node["prov:wasInfluencedBy"]
    assert deviation["prov:startedAtTime"] == "2026-03-01T10:00:00Z"


def test_strict_validation_reports_a_time_no_date_can_hold() -> None:
    record = {
        "schema_version": "0.2.0",
        "test": {
            "id": "https://w3id.org/battinfo/test/7d9k-2m4p-8t3x-6nq5",
            "started_at": MS_START,
            "ended_at": 1772442600,
        },
    }
    strict = validate_semantic_report(record, policy="strict")
    [issue] = [i for i in strict.issues if i.code.startswith("semantic.timestamp_")]
    assert (issue.code, issue.severity, issue.path) == ("semantic.timestamp_out_of_range", "error", "test.started_at")
    assert "milliseconds" in issue.message
    for policy in ("default", "ingest"):
        [lenient] = [
            i
            for i in validate_semantic_report(record, policy=policy).issues
            if i.code.startswith("semantic.timestamp_")
        ]
        assert (lenient.code, lenient.severity) == ("semantic.timestamp_out_of_range", "warning")


# ── The deposit's files, checked before the publish ───────────────────────────


@pytest.mark.parametrize("problem", ["lose", "corrupt"])
def test_a_publish_is_refused_when_the_deposit_lacks_a_file_or_its_md5_differs(
    tmp_path: Path, api: _ZenodoAPI, problem: str
) -> None:
    ws = _workspace(tmp_path)
    local_urls = _content_urls(ws)
    getattr(api, problem).add("cycling.csv")

    with pytest.raises(RuntimeError) as excinfo:
        ws.zenodo(token="placeholder", creators=CREATORS, publish=True)

    message = str(excinfo.value)
    assert message.startswith("Refusing to publish: the deposit does not hold the files its records point at: ")
    if problem == "lose":
        assert "cycling.csv was uploaded but is not on the deposit" in message
    else:
        data = (tmp_path / "C01" / "cycling.csv").read_bytes()
        assert f"cycling.csv is on the deposit with md5 {_md5(data + b'!')}" in message
        assert f"the file uploaded has md5 {_md5(data)}" in message
    assert "https://zenodo.org/deposit/7" in message
    # The deposit's files were listed after the upload, and nothing was published.
    assert api.requests[-1] == "GET /deposit/depositions/7/files" and PUBLISH_REQUEST not in api.requests
    assert not api.published
    state = _state(ws)
    assert state is not None and state["record_id"] == "7" and state["published"] is False
    assert _content_urls(ws) == local_urls


def test_a_draft_reports_what_the_deposit_lacks(
    tmp_path: Path, api: _ZenodoAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    api.lose.add("cycling.csv")
    capsys.readouterr()

    with pytest.warns(UserWarning, match="does not hold the files its records point at: cycling.csv was uploaded"):
        result = ws.zenodo(token="placeholder", creators=CREATORS)

    assert not result.published and not api.published
    out = capsys.readouterr().out
    assert "WARNING: the draft does not hold the files its records point at (1):" in out
    assert "    cycling.csv was uploaded but is not on the deposit" in out


def test_a_distribution_hosted_elsewhere_passes(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    external = "https://data.example.org/C01/cycling%20raw.ndax"
    _edit_dataset(
        ws,
        "cycling.csv",
        lambda ds: ds["distributions"].append(
            {"content_url": external, "encoding_format": "application/octet-stream", "role": "raw"}
        ),
    )

    result = ws.zenodo(token="placeholder", creators=CREATORS, publish=True)

    assert result.published and api.published
    assert set(api.files) == {"cycling.csv", "battinfo.json", "ro-crate-metadata.json"}
    urls = [
        dist["dcat:downloadURL"]
        for node in api.graph()["@graph"]
        if "dcat:Dataset" in (node.get("@type") or [])
        for dist in node["dcat:distribution"]
    ]
    assert sorted(urls) == sorted([f"{RECORD_URL}/files/cycling.csv", external])


def test_a_draft_then_a_publish_keeps_the_data_file(tmp_path: Path, api: _ZenodoAPI) -> None:
    """The draft points the records at its files; the publish that follows still carries them.

    The second run finds the local file behind the record's Zenodo URL
    through .battinfo/deposit-files.json, sees that the draft holds it
    unchanged, and publishes the draft with it.
    """
    ws = _workspace(tmp_path)
    ws.zenodo(token="placeholder", creators=CREATORS)
    assert _content_urls(ws) == [f"{RECORD_URL}/files/cycling.csv"]
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()

    with pytest.warns(UserWarning, match="unpublished draft"):
        result = ws.zenodo(token="placeholder", creators=CREATORS, publish=True)

    assert result.published and api.published
    assert api.files["cycling.csv"] == data
    assert [line for line in api.requests if line.startswith("PUT /files/")].count(
        "PUT /files/bucket-7/cycling.csv"
    ) == 1
    assert _content_urls(ws) == [f"{RECORD_URL}/files/cycling.csv"]


# ── The check itself ──────────────────────────────────────────────────────────


def _distribution(url: str, name: str, *, md5: str = "") -> dict:
    dist: dict = {"@type": "dcat:Distribution", "dcat:downloadURL": url, "schema:name": name}
    if md5:
        dist["spdx:checksum"] = {
            "@type": "spdx:Checksum",
            "spdx:checksumAlgorithm": {"@id": "spdx:checksumAlgorithm_md5"},
            "spdx:checksumValue": md5,
        }
    return dist


def _graph(*distributions: dict) -> dict:
    return {
        "@graph": [
            {"@id": RECORD_URL, "@type": ["dcat:Catalog", "schema:Dataset"]},
            {
                "@id": "https://w3id.org/battinfo/dataset/d-001",
                "@type": ["dcat:Dataset", "schema:Dataset"],
                "dcat:distribution": list(distributions),
            },
        ]
    }


def test_the_check_compares_names_and_md5s() -> None:
    a, b = "0" * 32, "1" * 32
    listing = [
        {"filename": "cell 01.csv", "checksum": f"md5:{a}"},
        {"key": "all.zip", "checksum": b},
        {"filename": "battinfo.json", "checksum": "sha256:" + "2" * 64},
    ]
    files = f"{RECORD_URL}/files"
    graph = _graph(
        _distribution(f"{files}/cell%2001.csv", "cell 01.csv", md5=b),  # the record states another md5
        _distribution(f"{files}/all.zip", "inside.csv", md5=a),  # in an archive: its md5 is not the archive's
        _distribution(f"{files}/gone.csv", "gone.csv"),  # not on the deposit
        _distribution("https://data.example.org/raw.ndax", "raw.ndax"),  # elsewhere on the web
        _distribution("", "empty.csv"),  # no download URL
        _distribution("s3://bucket/key.csv", "key.csv"),  # not a web address
    )
    problems = deposit_file_problems(
        graph,
        files_base=files,
        listing=listing,
        sent={"cell 01.csv": a, "all.zip": a, "battinfo.json": "3" * 32},
    )
    dataset = "dataset https://w3id.org/battinfo/dataset/d-001"
    assert problems == [
        f"all.zip is on the deposit with md5 {b}, but the file uploaded has md5 {a}",
        f"battinfo.json is on the deposit without an md5, but the file uploaded has md5 {'3' * 32}",
        f"{dataset}: cell 01.csv is on the deposit with md5 {a}, but the record states md5 {b}",
        f"{dataset}: links to gone.csv, which is not on the deposit",
        f"{dataset}: empty.csv has no download URL",
        f"{dataset}: key.csv has the download URL s3://bucket/key.csv, which is neither on the deposit nor on the web",
    ]


def test_the_check_compares_a_stated_sha256_and_size_with_the_file_planned(tmp_path: Path) -> None:
    from battinfo._deposit_files import measured_file

    data_file = tmp_path / "cycling.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    entry = measured_file(data_file, "cycling.csv")
    files = f"{RECORD_URL}/files"
    stale = _distribution(f"{files}/cycling.csv", "cycling.csv")
    stale["spdx:checksum"] = {
        "@type": "spdx:Checksum",
        "spdx:checksumAlgorithm": {"@id": "spdx:checksumAlgorithm_sha256"},
        "spdx:checksumValue": "4" * 64,
    }
    stale["dcat:byteSize"] = entry.size + 3
    listing = [{"filename": "cycling.csv", "checksum": f"md5:{entry.md5}"}]

    problems = deposit_file_problems(
        _graph(stale),
        files_base=files,
        listing=listing,
        sent={"cycling.csv": entry.md5},
        planned={"cycling.csv": entry},
    )

    dataset = "dataset https://w3id.org/battinfo/dataset/d-001"
    assert problems == [
        f"{dataset}: cycling.csv has sha256 {entry.sha256}, but the record states sha256 {'4' * 64}",
        f"{dataset}: cycling.csv is {entry.size} bytes, but the record states {entry.size + 3}",
    ]
    stale["spdx:checksum"]["spdx:checksumValue"] = entry.sha256
    stale["dcat:byteSize"] = entry.size
    assert (
        deposit_file_problems(
            _graph(stale),
            files_base=files,
            listing=listing,
            sent={"cycling.csv": entry.md5},
            planned={"cycling.csv": entry},
        )
        == []
    )


def test_the_check_passes_a_deposit_that_holds_what_it_sent() -> None:
    a = "0" * 32
    files = f"{RECORD_URL}/files"
    graph = _graph(_distribution(f"{files}/cell%2001.csv", "cell 01.csv", md5=a))
    listing = [{"filename": "cell 01.csv", "checksum": a}]
    assert deposit_file_problems(graph, files_base=files, listing=listing, sent={"cell 01.csv": a}) == []
    # A listing Zenodo could not give is a problem in itself.
    assert deposit_file_problems(graph, files_base=files, listing={"message": "error"}, sent={"cell 01.csv": a}) == [
        "cell 01.csv was uploaded but is not on the deposit",
    ]


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ({"content_url": "file:///data/a.csv", "encoding_format": "text/csv"}, None),
        ({"content_url": "https://example.org/a.csv"}, None),
        (None, "distribution 3 is not an object (None)"),
        ({"content_url": "  "}, "distribution 3 has no content_url"),
        ({"content_url": ["a.csv"]}, "distribution 3 has a content_url that is not text (['a.csv'])"),
    ],
)
def test_distribution_problem(entry: object, problem: str | None) -> None:
    assert distribution_problem(entry, 3) == problem
