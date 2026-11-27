"""A cell spec or parameter set is submitted with its own JSON-LD.

The registry serves its own envelope at a record's IRI. So that it can serve
the record's own statements there too, each cell spec and parameter set
submission carries ``resource.record_jsonld``: ``record_to_jsonld(record)``
with its default context, beside ``semantic_payload``. Its ``@id`` is the
record's IRI as sent, also after an ``/id/1001/`` IRI is adopted in the old
form. Other resource types carry none. A record that cannot be exported is
refused before anything is sent; the emitter's warnings stop nothing.

The registry is answered in memory; nothing goes on the network.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
import battinfo.api  # noqa: E402
import battinfo.jsonld  # noqa: E402
from battinfo import api  # noqa: E402
from battinfo.api import build_curated_cell_spec_submission, build_submission_envelope  # noqa: E402
from battinfo.api._staging import _RECORD_JSONLD_KINDS, _submission_record_jsonld  # noqa: E402
from battinfo.entities import ENTITY_KINDS, cell_spec_uid  # noqa: E402
from battinfo.interop import bpx_file_distribution, from_bpx_parameters  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.namespace import parse_record_iri, record_iri  # noqa: E402
from battinfo.ws import (  # noqa: E402
    AuthoringWorkspace,
    SubmitError,
    _cell_instance_submission_payload,
    _cell_spec_submission_payload,
    _record_jsonld_error,
    _simple_submission_payload,
)

EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
CELL_SPEC_FILE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
BPX_FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
SOURCE_URL = "https://files.example.org/parameter_sets/x/source.bpx.json"
CONTEXT_URL = "https://w3id.org/battinfo/context/records/v1.json"
REGISTRY = "https://registry.example"
CREDS = {"registry_url": REGISTRY, "api_key": "k", "workspace_id": "w", "publisher_id": "p"}
SPEC_FIELDS = {"manufacturer": "Example Lab", "model": "R2032", "format": "coin", "chemistry": "li-ion"}
SPEC_UID = cell_spec_uid({**SPEC_FIELDS, "size_code": None})
SPEC_OLD = record_iri("spec", SPEC_UID)
SPEC_NEW = record_iri("spec", SPEC_UID, "1001")
ENVELOPE_ARGS = {"wid": "w", "pid": "p", "ver": "v1", "source_local_id": "x", "title": "t"}


def _example(folder: str) -> dict:
    path = sorted((EXAMPLES / folder).glob("*.json"))[0]
    return json.loads(path.read_text(encoding="utf-8"))


def _cell_spec() -> dict:
    return json.loads(CELL_SPEC_FILE.read_text(encoding="utf-8"))


def _parameter_set(**kwargs: Any) -> dict:
    """A file-backed parameter set: the BPX fixture's record with its source file."""
    source = bpx_file_distribution(BPX_FIXTURE, content_url=SOURCE_URL)
    kwargs.setdefault("virtual_cell", True)
    return from_bpx_parameters(BPX_FIXTURE).to_parameter_set(distributions=[source], **kwargs)


def _parameter_set_payload(record: dict) -> dict:
    return _simple_submission_payload(
        record, resource_type="parameter_set", rdf_type="ParameterSet", record_key="parameter_set", **ENVELOPE_ARGS
    )


class _Reply(io.BytesIO):
    def __init__(self, payload: object) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def getcode(self) -> int:
        return 200


class FakeRegistry:
    """Holds the records in ``held`` (``"segment/uid"`` -> IRI) and keeps the packages POSTed to it."""

    def __init__(self) -> None:
        self.held: dict[str, str] = {}
        self.lookups: list[str] = []
        self.posted: list[dict] = []

    def __call__(self, request: Any, timeout: float | None = None) -> _Reply:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        method = request.get_method() if isinstance(request, urllib.request.Request) else "GET"
        assert url.startswith(REGISTRY), f"unexpected request: {method} {url}"
        path = urllib.parse.urlparse(url).path
        if method == "POST" and path == "/publication-packages":
            self.posted.append(json.loads(request.data))
            return _Reply({"status": "validated", "resources": [{"canonical_iri": "iri"}]})
        self.lookups.append(path)
        key = path.removeprefix("/resources/")
        if key in self.held:
            return _Reply({"canonical_iri": self.held[key], "canonical_id": key.rsplit("/", 1)[1]})
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b'{"detail": "Resource not found."}'))  # type: ignore[arg-type]

    def resources(self, resource_type: str) -> list[dict]:
        return [p["resource"] for p in self.posted if p["resource"]["resource_type"] == resource_type]


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeRegistry:
    fake = FakeRegistry()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(battinfo.api, "urlopen", fake)
    monkeypatch.delenv("BATTINFO_REGISTRY_URL", raising=False)
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", tmp_path / "home" / ".battinfo" / "config.yaml")
    return fake


def _assert_carries_its_export(resource: dict, record_key: str, record_type: str) -> None:
    """The resource's record_jsonld is the export of the record it carries, under that record's IRI."""
    record = resource["semantic_payload"]["battinfo_records"][record_key]
    export = resource["record_jsonld"]
    assert export["@id"] == record[record_key]["id"]
    assert export["@context"] == CONTEXT_URL
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        assert export == record_to_jsonld(record, record_type)
    assert "record_jsonld" not in resource["semantic_payload"]


# ── The envelope ─────────────────────────────────────────────────────────────


def test_a_parameter_set_envelope_carries_its_own_jsonld() -> None:
    record = _parameter_set()
    before = copy.deepcopy(record)

    resource = _parameter_set_payload(record)["resource"]

    _assert_carries_its_export(resource, "parameter_set", "parameter-set")
    assert resource["record_jsonld"]["@id"] == before["parameter_set"]["id"]
    assert resource["semantic_payload"]["battinfo_records"]["parameter_set"] == before
    assert record == before


def test_a_cell_spec_envelope_carries_its_own_jsonld() -> None:
    record = _cell_spec()

    authoring = _cell_spec_submission_payload(record, **ENVELOPE_ARGS)["resource"]
    curated = build_curated_cell_spec_submission(
        CELL_SPEC_FILE, workspace_id="w", publisher_id="p", source_version="v1", source_local_id="x"
    )["resource"]

    for resource in (authoring, curated):
        _assert_carries_its_export(resource, "cell_spec", "cell-spec")
        assert resource["record_jsonld"]["@id"] == record["cell_spec"]["id"]


def test_other_resource_types_carry_no_jsonld_of_their_own() -> None:
    cell = _cell_instance_submission_payload(_example("cell-instance"), spec_record=_cell_spec(), **ENVELOPE_ARGS)
    assert "cell_spec" in cell["resource"]["semantic_payload"]["battinfo_records"]
    assert "record_jsonld" not in cell["resource"]

    for folder, resource_type in (
        ("test", "test"),
        ("dataset", "dataset"),
        ("test-protocol", "test_spec"),
        ("material-spec", "material_spec"),
    ):
        record = _example(folder)
        record_key = next(key for key, value in record.items() if isinstance(value, dict) and "id" in value)
        resource = _simple_submission_payload(
            record,
            resource_type=resource_type,
            rdf_type="Thing",
            record_key=record_key,
            **ENVELOPE_ARGS,
        )["resource"]
        assert "record_jsonld" not in resource, folder


def test_the_emitter_warnings_stop_nothing() -> None:
    record = _cell_spec()  # its cycle_life has only value_text, which the emitter warns about
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        resource = _cell_spec_submission_payload(record, **ENVELOPE_ARGS)["resource"]
    assert resource["record_jsonld"]["@id"] == record["cell_spec"]["id"]


def test_a_record_that_cannot_be_exported_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(record: dict, record_type: str, **kwargs: Any) -> dict:
        raise ValueError("json-ld validation failed: no such class")

    monkeypatch.setattr(battinfo.jsonld, "record_to_jsonld", broken)
    record = _cell_spec()
    with pytest.raises(ValueError, match="cannot be exported as JSON-LD") as refused:
        build_submission_envelope(
            resource_type="cell_spec",
            records={"cell_spec": record},
            rdf_type="CellSpec",
            workspace_id="w",
            publisher_id="p",
            source_version="v1",
            source_local_id="x",
            title="t",
            publication_mode="staged-publication",
            source_system="s",
            workflow_name="w",
        )
    assert record["cell_spec"]["id"] in str(refused.value)
    assert "no such class" in str(refused.value)


def test_other_warnings_stay_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    def deprecated(record: dict, record_type: str, **kwargs: Any) -> dict:
        warnings.warn("an old key", DeprecationWarning, stacklevel=2)
        return {"@id": "x"}

    monkeypatch.setattr(battinfo.jsonld, "record_to_jsonld", deprecated)
    with pytest.warns(DeprecationWarning, match="an old key"):
        assert _submission_record_jsonld("cell_spec", _cell_spec()) == {"@id": "x"}


def test_the_kinds_that_carry_their_export_come_from_the_entity_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    by_type = {kind.entity_type: kind for kind in ENTITY_KINDS}
    assert sorted(by_type[entity_type].record_key for entity_type in _RECORD_JSONLD_KINDS) == [
        "cell_spec",
        "parameter_set",
    ]
    spec, parameters = _cell_spec(), _parameter_set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        assert _submission_record_jsonld("cell_spec", spec) == record_to_jsonld(spec, "cell-spec")
        assert _submission_record_jsonld("parameter_set", parameters) == record_to_jsonld(parameters, "parameter-set")
    assert _submission_record_jsonld("cell", spec) is None

    # ws.submit() checks the records in exactly the folders of those kinds.
    def broken(record: dict, record_type: str, **kwargs: Any) -> dict:
        raise ValueError("broken")

    monkeypatch.setattr(battinfo.jsonld, "record_to_jsonld", broken)
    checked = {kind.subdir for kind in ENTITY_KINDS if _record_jsonld_error({}, kind.subdir) is not None}
    assert checked == {by_type[entity_type].subdir for entity_type in _RECORD_JSONLD_KINDS}
    assert checked == {"cell-spec", "parameter-set"}


# ── Adoption: the export names the record's IRI as sent ──────────────────────


@pytest.mark.parametrize("kind", ["cell_spec", "parameter_set"])
def test_an_adopted_iri_is_sent_in_the_old_form_in_the_export_too(registry: FakeRegistry, kind: str) -> None:
    if kind == "cell_spec":
        record = _cell_spec()
        record["cell_spec"]["id"] = record_iri("spec", parse_record_iri(record["cell_spec"]["id"]).uid, "1001")  # type: ignore[union-attr]
        payload = _cell_spec_submission_payload(record, **ENVELOPE_ARGS)
        record_type = "cell-spec"
    else:
        record = _parameter_set()
        payload = _parameter_set_payload(record)
        record_type = "parameter-set"
    new = record[kind]["id"]
    parsed = parse_record_iri(new)
    assert parsed is not None and parsed.prefix == "1001"
    old = record_iri(parsed.segment, parsed.uid)
    registry.held[f"{parsed.segment}/{parsed.uid}"] = old
    assert payload["resource"]["record_jsonld"]["@id"] == new

    result = api.submit_publication_package(payload, registry_base_url=REGISTRY, api_key="k")

    assert result["adopted"] == {new: old}
    (posted,) = registry.posted
    resource = posted["resource"]
    assert resource["semantic_payload"]["battinfo_records"][kind][kind]["id"] == old
    _assert_carries_its_export(resource, kind, record_type)
    assert new not in json.dumps(resource["record_jsonld"])
    if kind == "cell_spec":
        assert resource["record_jsonld"]["isDescriptionFor"]["@id"] == f"{old}#described"
    # The export named no IRI the record does not, so nothing more was asked.
    assert registry.lookups == [f"/resources/{parsed.segment}/{parsed.uid}"]


def test_a_curated_cell_spec_is_published_with_its_export(tmp_path: Path, registry: FakeRegistry) -> None:
    record = _cell_spec()
    uid = parse_record_iri(record["cell_spec"]["id"]).uid  # type: ignore[union-attr]
    record["cell_spec"]["id"] = record_iri("spec", uid, "1001")
    source = tmp_path / "a123" / "record.json"
    source.parent.mkdir()
    source.write_text(json.dumps(record), encoding="utf-8")
    registry.held[f"spec/{uid}"] = record_iri("spec", uid)

    result = api.publish_curated_cell_spec(
        source,
        workspace_id="w",
        publisher_id="p",
        source_version="v1",
        registry_base_url=REGISTRY,
        api_key="k",
    )

    assert result["status"] == "ok"
    ((resource,),) = [registry.resources("cell_spec")]
    _assert_carries_its_export(resource, "cell_spec", "cell-spec")
    assert resource["record_jsonld"]["@id"] == record_iri("spec", uid)


# ── ws.submit() ──────────────────────────────────────────────────────────────


def _workspace(root: Path) -> AuthoringWorkspace:
    """A workspace that mints under /id/1001/: a cell spec, a cell, and a parameter file about the spec."""
    ws = AuthoringWorkspace(root=root, registry_url=REGISTRY)
    ws.license("cc-by-4.0")
    ws.add("cell", spec=battinfo.CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    ws.add("parameter_set", record=_parameter_set(virtual_cell=False, cell_spec_id=SPEC_NEW))
    ws.save()
    return ws


def test_submit_sends_each_cell_spec_and_parameter_set_with_its_export(tmp_path: Path, registry: FakeRegistry) -> None:
    ws = _workspace(tmp_path)
    registry.held[f"spec/{SPEC_UID}"] = SPEC_OLD

    outcomes = ws.submit(**CREDS)

    assert outcomes and all(outcome["ok"] for outcome in outcomes)
    ((spec,),) = [registry.resources("cell_spec")]
    ((parameters,),) = [registry.resources("parameter_set")]
    _assert_carries_its_export(spec, "cell_spec", "cell-spec")
    _assert_carries_its_export(parameters, "parameter_set", "parameter-set")
    # The spec IRI the registry holds in the old form is the one each export names.
    assert spec["record_jsonld"]["@id"] == SPEC_OLD
    assert parameters["semantic_payload"]["battinfo_records"]["parameter_set"]["parameter_set"]["cell_spec_id"] == (
        SPEC_OLD
    )
    assert SPEC_NEW not in json.dumps(registry.posted)
    assert all("record_jsonld" not in resource for resource in registry.resources("cell"))
    # Each IRI was asked about once: the exports added none to ask about.
    assert len(registry.lookups) == len(set(registry.lookups))


@pytest.mark.parametrize("broken_kind", ["cell-spec", "parameter-set"])
def test_submit_refuses_a_record_it_cannot_export_before_anything_is_sent(
    tmp_path: Path, registry: FakeRegistry, monkeypatch: pytest.MonkeyPatch, broken_kind: str
) -> None:
    ws = _workspace(tmp_path)
    exported = battinfo.jsonld.record_to_jsonld

    def broken_for_one_kind(record: dict, record_type: str, **kwargs: Any) -> dict:
        if record_type == broken_kind:
            raise TypeError("cannot read the record")
        return exported(record, record_type, **kwargs)

    monkeypatch.setattr(battinfo.jsonld, "record_to_jsonld", broken_for_one_kind)

    with pytest.raises(SubmitError) as refused:
        ws.submit(**CREDS)

    (failed,) = refused.value.failed
    assert failed["status"] == "invalid"
    assert f"the {broken_kind} record" in failed["error"]
    assert "cannot be exported as JSON-LD" in failed["error"]
    assert "cannot read the record" in failed["error"]
    if broken_kind == "cell-spec":
        assert failed["iri"] == SPEC_NEW
    else:
        assert failed["iri"].startswith("https://w3id.org/battinfo/id/1001/dataset/")
    assert registry.posted == []
    assert registry.lookups == []


def test_an_export_that_fails_after_the_iri_lookups_fails_that_record_only(
    tmp_path: Path, registry: FakeRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The up-front check passed, and the export of the record as adopted fails: it is reported, not raised."""
    ws = _workspace(tmp_path)
    registry.held[f"spec/{SPEC_UID}"] = SPEC_OLD
    exported = battinfo.jsonld.record_to_jsonld

    def broken_once_adopted(record: dict, record_type: str, **kwargs: Any) -> dict:
        if record_type == "cell-spec" and record["cell_spec"]["id"] == SPEC_OLD:
            raise TypeError("cannot read the record")
        return exported(record, record_type, **kwargs)

    monkeypatch.setattr(battinfo.jsonld, "record_to_jsonld", broken_once_adopted)

    with pytest.raises(SubmitError) as refused:
        ws.submit(**CREDS)

    (failed,) = refused.value.failed
    assert failed["status"] == "invalid"
    assert failed["iri"] == SPEC_OLD
    assert "cannot be exported as JSON-LD" in failed["error"]
    assert registry.resources("cell_spec") == []
    assert [len(registry.resources(kind)) for kind in ("parameter_set", "cell")] == [1, 1]
