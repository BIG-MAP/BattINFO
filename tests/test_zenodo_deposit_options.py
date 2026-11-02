"""The options ``ws.zenodo()`` takes for the Zenodo form and the deposit graph.

- ``access_right`` (with ``embargo_date`` and ``access_conditions``),
  ``version``, ``related_identifiers`` and ``publication_date`` reach the
  form; a value Zenodo cannot take is refused before anything is sent, and
  without them the form is what it was.
- A description of several paragraphs goes to the form as HTML paragraphs,
  and the deposit graph keeps the text as given.
- ``auto_keywords=False`` leaves out the keywords the form builder adds, and a
  keyword that differs from an earlier one only in case or punctuation is
  given once.
- ``publisher=`` names the publisher node of the deposit graph.
- ``preview_jsonld()`` takes the concept record and the previous version,
  which it has no deposit to read them from.

All offline: Zenodo is faked.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import types
from pathlib import Path

import pytest

import battinfo
from battinfo.validate import validate_publication_report
from battinfo.ws import AuthoringWorkspace
from battinfo.zenodo import _file_md5

pytestmark = pytest.mark.usefixtures("registry_holds_none")  # deposits ask the registry first (#483)

CREATORS = [{"name": "Doe, Jane", "affiliation": "Example University"}]
SPEC = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
CORDIS = "https://cordis.europa.eu/project/id/101103997"
PLACEHOLDER = "https://zenodo.org/records/RECORD_ID"
ORGANIZATION = "https://w3id.org/battinfo/id/1001/organization/sb9y-681a-mprq-1nfj"


class _RecordingZenodo:
    """Stands in for ZenodoClient: keeps the uploaded files and the metadata."""

    def __init__(self) -> None:
        self.uploaded: dict[str, str] = {}
        self.md5: dict[str, str] = {}
        self.metadata: dict = {}

    def client(self, *args: object, **kwargs: object) -> _RecordingZenodo:
        return self

    def create_empty_deposit(self) -> dict:
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict, *, keep: dict | None = None) -> dict:
        self.uploaded = {name: Path(path).read_text(encoding="utf-8") for path, name in upload_map.items()}
        self.md5 = {name: _file_md5(Path(path)) for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def list_files(self, deposit_id: int) -> list[dict]:
        return [{"filename": name, "checksum": md5} for name, md5 in self.md5.items()]

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        self.metadata = metadata
        return {}

    def graph(self) -> dict:
        return json.loads(self.uploaded["battinfo.json"])


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _RecordingZenodo:
    fake = _RecordingZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


@pytest.fixture()
def no_zenodo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Zenodo that fails the test when it is contacted."""
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", lambda *a, **k: pytest.fail("Zenodo was contacted"))


def _workspace(root: Path) -> AuthoringWorkspace:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.bdf.csv").write_text(
        "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n", encoding="utf-8"
    )
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    ws.add("cell", spec=SPEC.model_copy(), serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="run.bdf.csv")
    ws.save()
    return ws


def _form(ws: AuthoringWorkspace, **kwargs: object) -> dict:
    """The Zenodo form ws.zenodo() would send, with these options."""
    options: dict = {
        "title": None,
        "description": None,
        "creators": CREATORS,
        "license": "cc-by-4.0",
        "community": None,
        "extra_keywords": None,
        **kwargs,
    }
    return ws._build_zenodo_metadata(**options)


def _catalog(graph: dict) -> dict:
    return next(node for node in graph["@graph"] if "dcat:Catalog" in node["@type"])


def _node(graph: dict, iri: str) -> dict:
    return next(node for node in graph["@graph"] if node.get("@id") == iri)


def _errors(graph: dict) -> list[str]:
    report = validate_publication_report(graph, policy="publisher")
    return [issue.message for issue in report.issues if issue.severity == "error"]


# ── The form ──────────────────────────────────────────────────────────────────


def test_without_the_options_the_form_is_what_it_was(tmp_path: Path) -> None:
    form = _form(_workspace(tmp_path), description="One paragraph.\nA second line of it.", extra_keywords=["LFP"])
    assert form["access_right"] == "open"
    for key in ("embargo_date", "access_conditions", "version", "publication_date", "related_identifiers"):
        assert key not in form
    assert form["description"] == "One paragraph.\nA second line of it."
    keywords = form["keywords"]
    assert keywords[:3] == ["BattINFO", "battery", "electrochemistry"]
    assert {"Example Lab", "R2032", "li-ion"} <= set(keywords) and keywords[-1] == "LFP"


@pytest.mark.parametrize(
    ("options", "fields"),
    [
        (
            {"access_right": "embargoed", "embargo_date": dt.date(2099, 1, 31)},
            {"access_right": "embargoed", "embargo_date": "2099-01-31"},
        ),
        (
            {"access_right": "embargoed", "embargo_date": " 2099-01-31 "},
            {"access_right": "embargoed", "embargo_date": "2099-01-31"},
        ),
        (
            {"access_right": "restricted", "access_conditions": "On request to the data steward."},
            {"access_right": "restricted", "access_conditions": "On request to the data steward."},
        ),
        ({"access_right": "closed"}, {"access_right": "closed"}),
    ],
    ids=["embargoed-date", "embargoed-text", "restricted", "closed"],
)
def test_the_access_right_reaches_the_form(tmp_path: Path, options: dict, fields: dict) -> None:
    form = _form(_workspace(tmp_path), **options)
    assert {key: form[key] for key in fields} == fields
    for key in {"embargo_date", "access_conditions"} - set(fields):
        assert key not in form


def test_version_publication_date_and_related_identifiers_reach_the_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    monkeypatch.setattr(ws, "_get_project", lambda: types.SimpleNamespace(id=CORDIS))
    paper = {"identifier": "10.1234/example", "relation": "isSupplementTo", "resource_type": "publication-article"}
    funding = {"identifier": CORDIS, "relation": "isPartOf", "scheme": "url"}

    form = _form(ws, version="0.2.0", publication_date=dt.date(2026, 11, 1), related_identifiers=[paper])
    assert form["version"] == "0.2.0"
    assert form["publication_date"] == "2026-11-01"
    # The given identifiers come first, then the funding project's page, as before.
    assert form["related_identifiers"] == [paper, funding]
    assert _form(ws)["related_identifiers"] == [funding]
    # A given entry that names the project's page with isPartOf is not doubled.
    own = {"identifier": CORDIS, "relation": "isPartOf", "scheme": "url", "resource_type": "other"}
    assert _form(ws, related_identifiers=[own])["related_identifiers"] == [own]
    assert _form(ws, publication_date="2026-11-01")["publication_date"] == "2026-11-01"


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"access_right": "public"}, "access_right='public' is not one of"),
        ({"access_right": "embargoed"}, "access_right='embargoed' needs embargo_date="),
        ({"access_right": "embargoed", "embargo_date": "31.01.2027"}, "embargo_date='31.01.2027' is not a date"),
        ({"embargo_date": "2099-01-31"}, "embargo_date= applies to access_right='embargoed', not 'open'"),
        ({"access_right": "restricted"}, "access_right='restricted' needs access_conditions="),
        ({"access_right": "closed", "access_conditions": "x"}, "access_conditions= applies to access_right="),
        ({"publication_date": "Nov 2026"}, "publication_date='Nov 2026' is not a date"),
        ({"related_identifiers": [{"identifier": "10.1234/example"}]}, "related identifier 1 needs an identifier"),
        ({"related_identifiers": ["10.1234/example"]}, "related identifier 1 needs an identifier"),
        ({"access_right": "embargoed", "embargo_date": "2020-01-31"}, "is not in the future"),
    ],
)
def test_a_form_option_zenodo_cannot_take_is_refused(tmp_path: Path, options: dict, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        _form(_workspace(tmp_path), **options)


def test_a_description_of_paragraphs_goes_to_the_form_as_html(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    text = "First paragraph, with 5 < 6 & more.\r\n\r\nSecond paragraph,\nwrapped.\n \nThird.\n"
    assert _form(ws, description=text)["description"] == (
        "<p>First paragraph, with 5 &lt; 6 &amp; more.</p><p>Second paragraph,\nwrapped.</p><p>Third.</p>"
    )
    # One paragraph, and text that is HTML already, go as they are.
    assert _form(ws, description="One paragraph.\n")["description"] == "One paragraph.\n"
    html = "<p>One.</p>\n\n<p>Two.</p>"
    assert _form(ws, description=html)["description"] == html


def test_auto_keywords_false_sends_the_given_keywords_alone_and_each_once(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    given = ["LFP", "lfp", "Li-ion", "li ion", "lithium-ion battery", "Lithium ion battery", "calendar_ageing"]
    given += ["calendar ageing", " ", "HPPC"]
    form = _form(ws, extra_keywords=given, auto_keywords=False)
    assert form["keywords"] == ["LFP", "Li-ion", "lithium-ion battery", "calendar_ageing", "HPPC"]
    # The keywords the builder adds cover a given one that differs only in case or punctuation.
    keywords = _form(ws, extra_keywords=["battinfo", "BATTERY", "example-lab", "cycle life"])["keywords"]
    assert keywords.count("BattINFO") == 1 and "battinfo" not in keywords and "BATTERY" not in keywords
    assert "Example Lab" in keywords and "example-lab" not in keywords and keywords[-1] == "cycle life"
    # With nothing to send the form has no keywords.
    assert "keywords" not in _form(ws, auto_keywords=False)
    # Only separators fold: a keyword that differs in other punctuation is its own.
    assert _form(ws, extra_keywords=["Li", "Li+", "Na/Na+"], auto_keywords=False)["keywords"] == ["Li", "Li+", "Na/Na+"]


# ── The deposit ───────────────────────────────────────────────────────────────


def test_zenodo_sends_the_options_to_the_form_and_the_graph(tmp_path: Path, zenodo: _RecordingZenodo) -> None:
    ws = _workspace(tmp_path)
    related = [{"identifier": "10.1234/example", "relation": "isSupplementTo"}]
    ws.zenodo(
        token="placeholder",
        creators=CREATORS,
        description="What the data are.\n\nHow they were made.",
        keywords=["LFP", "lfp"],
        auto_keywords=False,
        access_right="embargoed",
        embargo_date="2099-01-31",
        version="1.0.0",
        related_identifiers=related,
        publication_date="2026-11-01",
        publisher={"name": "Example Lab", "ror": "01abcde23"},
    )

    form = zenodo.metadata
    assert form["access_right"] == "embargoed" and form["embargo_date"] == "2099-01-31"
    assert form["version"] == "1.0.0" and form["publication_date"] == "2026-11-01"
    assert form["related_identifiers"] == related
    assert form["keywords"] == ["LFP"]
    assert form["description"] == "<p>What the data are.</p><p>How they were made.</p>"
    assert "publisher" not in form

    graph = zenodo.graph()
    catalog = _catalog(graph)
    assert catalog["schema:description"] == "What the data are.\n\nHow they were made."
    assert catalog["schema:version"] == "1.0.0"
    assert catalog["schema:publisher"] == {"@id": "https://ror.org/01abcde23"}
    assert _node(graph, "https://ror.org/01abcde23")["schema:name"] == "Example Lab"
    assert _errors(graph) == []


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"access_right": "public"}, "access_right='public'"),
        ({"access_right": "embargoed"}, "needs embargo_date="),
        ({"embargo_date": "2099-01-31"}, "embargo_date= applies to"),
        ({"access_right": "restricted"}, "needs access_conditions="),
        ({"publication_date": "Nov 2026"}, "publication_date='Nov 2026'"),
        ({"related_identifiers": [{"relation": "cites"}]}, "related identifier 1"),
        ({"publisher": {"name": "Example Lab", "ror": "example"}}, "is not a ROR id"),
        ({"publisher": {"ror": "01abcde23"}}, "publisher= takes the organisation's name"),
        ({"publisher": {"name": "Example Lab", "id": "https://example.org/lab"}}, "is not a registry organization IRI"),
        ({"publisher": {"name": "Example Lab", "url": "https://example.org"}}, "not url"),
    ],
)
def test_an_option_zenodo_cannot_take_refuses_the_deposit_before_anything_is_sent(
    tmp_path: Path, no_zenodo: None, options: dict, message: str
) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(ValueError, match=re.escape(message)):
        ws.zenodo(token="placeholder", creators=CREATORS, **options)


# ── The publisher and the version links in the graph ─────────────────────────


@pytest.mark.parametrize(
    ("publisher", "node"),
    [
        # Without one, the first affiliation among the creators, as before.
        (None, {"@id": f"{PLACEHOLDER}#provider", "schema:name": "Example University"}),
        ("Example Lab", {"@id": f"{PLACEHOLDER}#provider", "schema:name": "Example Lab"}),
        (
            {"name": "Example Lab", "ror": "https://ror.org/01abcde23"},
            {"@id": "https://ror.org/01abcde23", "schema:name": "Example Lab"},
        ),
        (
            {"name": "Example Lab", "id": ORGANIZATION, "ror": "01abcde23"},
            {"@id": ORGANIZATION, "schema:name": "Example Lab", "schema:sameAs": {"@id": "https://ror.org/01abcde23"}},
        ),
    ],
    ids=["affiliation", "name", "ror", "organization-iri"],
)
def test_the_publisher_names_the_graph_publisher(tmp_path: Path, publisher: object, node: dict) -> None:
    ws = _workspace(tmp_path)
    graph = json.loads(ws.preview_jsonld(creators=CREATORS, publisher=publisher).read_text(encoding="utf-8"))
    catalog = _catalog(graph)
    for term in ("schema:publisher", "dcterms:publisher", "prov:wasAttributedTo"):
        assert catalog[term] == {"@id": node["@id"]}
    assert _node(graph, node["@id"]) == {"@type": ["schema:Organization", "prov:Agent"], **node}
    assert _errors(graph) == []


def test_the_preview_names_the_concept_and_the_previous_version(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    concept, previous = "https://zenodo.org/records/100", "https://zenodo.org/records/101"
    graph = json.loads(
        ws.preview_jsonld(
            creators=CREATORS, version="2.0.0", is_version_of=concept, previous_version=previous
        ).read_text(encoding="utf-8")
    )
    catalog = _catalog(graph)
    assert catalog["schema:version"] == "2.0.0"
    assert catalog["dcterms:isVersionOf"] == {"@id": concept}
    assert catalog["dcat:previousVersion"] == {"@id": previous}
    assert _errors(graph) == []

    # is_version_of alone keeps its meaning and adds no previous version.
    catalog = _catalog(json.loads(ws.preview_jsonld(creators=CREATORS, is_version_of=concept).read_text("utf-8")))
    assert catalog["dcterms:isVersionOf"] == {"@id": concept} and "dcat:previousVersion" not in catalog
