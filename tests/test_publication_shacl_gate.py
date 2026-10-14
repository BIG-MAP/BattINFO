"""A deposit graph the SHACL publication shapes could not check is never published.

ws.zenodo(publish=True) and ws.preview_jsonld() check the deposit graph under
the publisher policy, and part of that check runs the SHACL shapes in
publication.shapes.ttl, whose sh:Violation rules are errors. When the shapes
cannot be checked (pyshacl cannot be imported, the shapes file is missing, or
pyshacl fails), the publisher policy reports an error, so the publish gate
fails closed, and the other policies report a warning.

pyshacl's absence is simulated by poisoning sys.modules with None, as in
test_optional_extras.py; monkeypatch restores the real modules afterwards.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate import validate_publication_report  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

_NOT_RUN_CODES = {"publication.shacl_unavailable", "publication.shapes_not_found", "publication.shacl_runtime_error"}


def _poison_pyshacl(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(sys.modules):
        if name == "pyshacl" or name.startswith("pyshacl."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "pyshacl", None)  # type: ignore[arg-type]


def _workspace(root: Path) -> AuthoringWorkspace:
    """A saved workspace with a cell spec, a cell, a test and its dataset."""
    ws = AuthoringWorkspace(root=root, registry_url=None)
    (root / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"pouch","chemistry":"nmc"}', encoding="utf-8"
    )
    spec = ws.load(root / "d.cell-spec.json")
    ws.add("cell", spec=spec, names=["c1"])
    (root / "c1.bdf.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    (root / "c1.ndax").write_bytes(b"RAW")
    ws.add("test", type="capacity_check", cell="c1", data="c1.bdf.csv", raw="c1.ndax")
    ws.save()
    return ws


_DEPOSIT_METADATA = {
    "title": "t",
    "description": "d",
    "creators": [{"name": "A", "affiliation": "Org"}],
    "license": "CC-BY-4.0",
}


def _deposit_graph(ws: AuthoringWorkspace) -> dict:
    return ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://sandbox.zenodo.org/records/1",
        data_filenames=["c1.bdf.csv", "c1.ndax"],
        **_DEPOSIT_METADATA,
    )


@pytest.fixture(scope="module")
def clean_graph(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """A deposit graph with no errors under the publisher policy, SHACL included."""
    graph = _deposit_graph(_workspace(tmp_path_factory.mktemp("deposit")))
    report = validate_publication_report(graph, policy="publisher")
    assert report.ok, [(i.code, i.message) for i in report.errors]
    return graph


def _not_run(report) -> list:
    return [issue for issue in report.issues if issue.code in _NOT_RUN_CODES]


def test_publisher_policy_errors_when_pyshacl_is_missing(clean_graph: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    _poison_pyshacl(monkeypatch)
    report = validate_publication_report(copy.deepcopy(clean_graph), policy="publisher")
    assert not report.ok
    [issue] = _not_run(report)
    assert issue.code == "publication.shacl_unavailable"
    assert issue.severity == "error"
    assert "pip install pyshacl" in issue.message


@pytest.mark.parametrize("policy", ["default", "strict", "ingest"])
def test_other_policies_warn_when_pyshacl_is_missing(
    clean_graph: dict, monkeypatch: pytest.MonkeyPatch, policy: str
) -> None:
    _poison_pyshacl(monkeypatch)
    report = validate_publication_report(copy.deepcopy(clean_graph), policy=policy)
    assert report.ok
    [issue] = _not_run(report)
    assert issue.code == "publication.shacl_unavailable"
    assert issue.severity == "warning"


def test_publisher_policy_errors_when_the_shapes_file_is_missing(
    clean_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import battinfo.validate.shacl as shacl

    monkeypatch.setattr(shacl, "_shapes_path", lambda filename: None)
    report = validate_publication_report(copy.deepcopy(clean_graph), policy="publisher")
    [issue] = _not_run(report)
    assert issue.code == "publication.shapes_not_found"
    assert issue.severity == "error"
    assert not report.ok


def test_publisher_policy_errors_when_pyshacl_fails(clean_graph: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import pyshacl

    def _fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(pyshacl, "validate", _fail)
    report = validate_publication_report(copy.deepcopy(clean_graph), policy="publisher")
    [issue] = _not_run(report)
    assert issue.code == "publication.shacl_runtime_error"
    assert issue.severity == "error"
    assert "parser exploded" in issue.message
    assert not report.ok

    report = validate_publication_report(copy.deepcopy(clean_graph), policy="default")
    assert [i.severity for i in _not_run(report)] == ["warning"]


def test_graph_without_a_catalog_is_not_held_to_the_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    # The publication shapes describe a deposit catalog; a single resolver node
    # is outside them, so no SHACL run is missed when pyshacl is absent.
    _poison_pyshacl(monkeypatch)
    node = {
        "@context": {"schema": "https://schema.org/"},
        "@id": "https://w3id.org/battinfo/spec/x",
        "@type": "schema:Thing",
    }
    report = validate_publication_report(node, policy="publisher")
    assert _not_run(report) == []


def test_publish_gate_refuses_when_pyshacl_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _workspace(tmp_path)
    graph = _deposit_graph(ws)
    ws._missing_data_files = []
    ws._assert_publishable(copy.deepcopy(graph))  # SHACL ran: the graph is publishable

    _poison_pyshacl(monkeypatch)
    with pytest.raises(RuntimeError, match="Refusing to publish") as excinfo:
        ws._assert_publishable(graph, nothing_sent=True)
    assert "pip install pyshacl" in str(excinfo.value)
    assert "Nothing was sent to Zenodo" in str(excinfo.value)


def test_preview_does_not_report_pass_when_pyshacl_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    ws.preview_jsonld(**_DEPOSIT_METADATA)
    assert "Gold-standard: PASS" in capsys.readouterr().out

    _poison_pyshacl(monkeypatch)
    out_path = ws.preview_jsonld(**_DEPOSIT_METADATA)
    out = capsys.readouterr().out
    assert "PASS" not in out
    assert "1 error(s)" in out
    assert "pip install pyshacl" in out
    assert out_path.exists()  # the preview still writes the file to review
