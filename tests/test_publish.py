from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

publish_module = importlib.import_module("battinfo._publish")
import battinfo
from battinfo import CellSpec, PublishResult, publish
from battinfo.api import publish_record, save_record
from battinfo.entities import entity_files_for_uid, save_entity_path
from battinfo.publication import save_publication_html


def _sample_cell_spec() -> CellSpec:
    return CellSpec(
        manufacturer="Google",
        model="G20M7",
        format="pouch",
        chemistry="Li-ion",
        size_code="P0000",
    )


def test_publish_cell_spec_local_writes_canonical_record(tmp_path: Path) -> None:
    result = publish(_sample_cell_spec(), destination="local", root=tmp_path / "publish-local", force=True)

    assert isinstance(result, PublishResult)
    assert result.status == "ok"
    assert result.destination == "local"
    assert result.resource_type == "cell_spec"
    assert result.canonical_id is not None
    assert result.canonical_iri == f"https://w3id.org/battinfo/id/1001/spec/{result.canonical_id}"

    canonical_record_path = Path(result.debug_paths["canonical_record_path"])
    assert canonical_record_path.exists()
    payload = json.loads(canonical_record_path.read_text(encoding="utf-8"))
    assert payload["cell_spec"]["manufacturer"]["name"] == "Google"
    assert payload["cell_spec"]["model"] == "G20M7"


def test_publish_cell_spec_registry_builds_submission_and_returns_registry_url(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_submit(payload, *, registry_base_url, api_key, api_key_header="X-Battinfo-API-Key", timeout_sec=30.0):
        captured["payload"] = payload
        captured["registry_base_url"] = registry_base_url
        captured["api_key"] = api_key
        captured["api_key_header"] = api_key_header
        captured["timeout_sec"] = timeout_sec
        source_local_id = payload["resource"]["source_local_id"]
        return {
            "status": "ok",
            "response": {
                "canonical_id_map": {source_local_id: "registry-cell-spec-001"},
                "canonical_iri_map": {
                    source_local_id: "https://w3id.org/battinfo/cell/registry-cell-spec-001",
                },
            },
        }

    monkeypatch.setattr(publish_module, "submit_publication_package", _fake_submit)

    result = publish(
        _sample_cell_spec(),
        destination="registry",
        root=tmp_path / "publish-registry",
        force=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        workspace_id="hello-world",
        publisher_id="demo-lab",
        source_version="2026-03-24",
    )

    assert isinstance(result, PublishResult)
    assert result.status == "ok"
    assert result.destination == "registry"
    assert result.canonical_id == "registry-cell-spec-001"
    assert result.canonical_iri == "https://w3id.org/battinfo/cell/registry-cell-spec-001"
    assert result.registry_resource_url == "https://registry.example.org/resources/cell-spec/registry-cell-spec-001"
    assert result.page_url is None
    assert result.workspace_id == "hello-world"
    assert result.publisher_id == "demo-lab"
    assert result.source_version == "2026-03-24"

    submission_path = Path(result.debug_paths["submission_package_path"])
    assert submission_path.exists()
    submission_payload = json.loads(submission_path.read_text(encoding="utf-8"))
    assert submission_payload["workspace_id"] == "hello-world"
    assert submission_payload["publisher_id"] == "demo-lab"
    assert "metadata" not in submission_payload["resource"]["semantic_payload"]
    assert "battinfo_records" in submission_payload["resource"]["semantic_payload"]

    captured_payload = captured["payload"]
    assert isinstance(captured_payload, dict)
    assert captured["registry_base_url"] == "https://registry.example.org"
    assert captured["api_key"] == "secret"
    assert captured_payload["resource"]["source_local_id"] == result.source_local_id


def test_publish_cell_spec_battery_genome_returns_page_url(tmp_path: Path, monkeypatch) -> None:
    def _fake_submit(payload, *, registry_base_url, api_key, api_key_header="X-Battinfo-API-Key", timeout_sec=30.0):
        source_local_id = payload["resource"]["source_local_id"]
        return {
            "status": "ok",
            "response": {
                "canonical_id_map": {source_local_id: "registry-cell-spec-002"},
                "canonical_iri_map": {
                    source_local_id: "https://w3id.org/battinfo/cell/registry-cell-spec-002",
                },
            },
        }

    monkeypatch.setattr(publish_module, "submit_publication_package", _fake_submit)

    result = publish(
        _sample_cell_spec(),
        destination="battery-genome",
        root=tmp_path / "publish-battery-genome",
        force=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        platform_base_url="https://battery-genome.org",
        workspace_id="hello-world",
        publisher_id="demo-lab",
        source_version="2026-03-24",
    )

    assert result.destination == "battery-genome"
    assert result.canonical_id == "registry-cell-spec-002"
    assert result.registry_resource_url == "https://registry.example.org/resources/cell-spec/registry-cell-spec-002"
    assert result.page_url == "https://battery-genome.org/registry/cell-spec/registry-cell-spec-002"


def test_publish_preserves_legacy_publication_package_call_shape(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _fake_legacy_publish(**kwargs):
        calls.append(dict(kwargs))
        return {"status": "ok", "kind": "legacy-publication-package"}

    monkeypatch.setattr(publish_module, "_legacy_publish", _fake_legacy_publish)

    result = publish(
        cell_spec="cell-spec",
        cell_instance="cell-instance",
        test="test",
        dataset="dataset",
    )

    assert result == {"status": "ok", "kind": "legacy-publication-package"}
    assert calls == [
        {
            "cell_spec": "cell-spec",
            "cell_instance": "cell-instance",
            "test": "test",
            "dataset": "dataset",
        }
    ]


def test_publish_requires_object_or_legacy_keywords() -> None:
    with pytest.raises(TypeError, match="needs a CellSpec"):
        publish()


def test_publish_lists_its_parameters_as_keyword_only() -> None:
    parameters = inspect.signature(publish).parameters
    for name in (
        "root",
        "force",
        "validation_policy",
        "registry_base_url",
        "api_key",
        "api_key_header",
        "platform_base_url",
        "workspace_id",
        "publisher_id",
        "source_version",
    ):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name


def test_publish_rejects_an_unknown_keyword() -> None:
    with pytest.raises(TypeError, match="roots"):
        publish(_sample_cell_spec(), destination="local", roots="publish-out")


def test_publish_rejects_a_legacy_keyword_next_to_an_object() -> None:
    with pytest.raises(TypeError, match="cell_instance"):
        publish(_sample_cell_spec(), destination="local", cell_instance="cell-instance")


def test_legacy_publish_warns_that_it_is_removed_in_0_9_0(monkeypatch) -> None:
    monkeypatch.setattr(publish_module, "_legacy_publish", lambda **kwargs: {"status": "ok"})

    with pytest.warns(DeprecationWarning, match=r"removed in 0\.9\.0"):
        publish(cell_spec="cell-spec", cell_instance="cell-instance", test="test", dataset="dataset")


def test_legacy_publish_forwards_its_own_keywords_and_validation_policy(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(publish_module, "_legacy_publish", lambda **kwargs: calls.append(kwargs) or {"status": "ok"})

    publish(
        cell_spec="cell-spec",
        cell_instance="cell-instance",
        test="test",
        dataset="dataset",
        emit_html_page=True,
        validation_policy="strict",
    )

    assert calls == [
        {
            "cell_spec": "cell-spec",
            "cell_instance": "cell-instance",
            "test": "test",
            "dataset": "dataset",
            "emit_html_page": True,
            "validation_policy": "strict",
        }
    ]


@pytest.mark.parametrize("extra", [{"root": "out"}, {"force": True}, {"api_key": "secret"}, {"bogus": 1}])
def test_legacy_publish_rejects_keywords_it_does_not_take(monkeypatch, extra: dict[str, object]) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(publish_module, "_legacy_publish", lambda **kwargs: calls.append(kwargs) or {"status": "ok"})

    with pytest.raises(TypeError, match=next(iter(extra))):
        publish(cell_spec="cell-spec", cell_instance="cell-instance", test="test", dataset="dataset", **extra)
    assert calls == []


# ---------------------------------------------------------------------------
# publish() takes a CellSpec; every other record model has a save_* function
# ---------------------------------------------------------------------------

_SPEC_IRI = "https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0"
_CELL_IRI = "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"

# (model name, fields of a draft without an id, the function that saves and mints it)
_OTHER_MODELS = [
    ("Cell", {"cell_spec_id": _SPEC_IRI, "serial_number": "S1"}, "save_cell_instance"),
    ("TestSpec", {"name": "CC discharge C/5", "test_type": "capacity_check"}, "save_test_spec"),
    ("Test", {"cell_instance_id": _CELL_IRI, "kind": "cycling", "name": "S1 cycling"}, "save_test"),
    ("Dataset", {"name": "Run 1", "access_url": "https://example.org/run-1"}, "save_dataset"),
]
_OTHER_MODEL_IDS = [name for name, _, _ in _OTHER_MODELS]


@pytest.mark.parametrize(("model", "fields", "save_function"), _OTHER_MODELS, ids=_OTHER_MODEL_IDS)
def test_publish_sends_another_record_model_to_its_save_function(
    tmp_path: Path, model: str, fields: dict, save_function: str
) -> None:
    root = tmp_path / "publish-out"

    with pytest.raises(TypeError) as excinfo:
        publish(getattr(battinfo, model)(**fields), destination="local", root=root)

    message = str(excinfo.value)
    assert "CellSpec" in message and model in message, message
    assert f"battinfo.{save_function}(" in message, message
    assert "battinfo.workspace(" in message, message
    # The publication-package forms take a cell spec, cell, test and dataset together.
    assert "publication_package" not in message, message
    assert not root.exists()


@pytest.mark.parametrize(("model", "fields", "save_function"), _OTHER_MODELS, ids=_OTHER_MODEL_IDS)
def test_the_save_function_publish_names_saves_the_draft(
    tmp_path: Path, model: str, fields: dict, save_function: str
) -> None:
    result = getattr(battinfo, save_function)(
        getattr(battinfo, model)(**fields), source_root=tmp_path / "records", resolve_references=False
    )

    assert result["status"] == "created"
    assert result["id"].startswith("https://w3id.org/battinfo/")


def test_publish_names_the_save_functions_for_an_object_that_is_not_a_record_model() -> None:
    with pytest.raises(TypeError) as excinfo:
        publish({"cell_spec": {"name": "A123 ANR26650M1-B"}}, destination="local")

    message = str(excinfo.value)
    assert "CellSpec" in message and "dict" in message, message
    assert "battinfo.save_record(" in message and "battinfo.workspace(" in message, message
    assert "publication_package" not in message, message


@pytest.mark.parametrize(("model", "fields", "save_function"), _OTHER_MODELS, ids=_OTHER_MODEL_IDS)
def test_a_record_model_without_an_id_names_the_function_that_mints_one(
    model: str, fields: dict, save_function: str
) -> None:
    with pytest.raises(ValueError) as excinfo:
        getattr(battinfo, model)(**fields).to_record()

    message = str(excinfo.value)
    assert f"battinfo.{save_function}(" in message, message
    assert "battinfo.workspace(" in message, message
    assert "build_publication_package" not in message and "battinfo.publish(" not in message, message


def test_publish_docstring_says_it_takes_a_cell_spec_only() -> None:
    doc = inspect.getdoc(publish) or ""

    assert "CellSpec" in doc
    for _, _, save_function in _OTHER_MODELS:
        assert save_function in doc, save_function
    for parameter in ("obj", "destination"):
        assert re.search(rf"^{parameter}\b", doc, re.MULTILINE), f"the docstring does not describe {parameter}"


# The pages that say what battinfo.publish() takes. A mention of the function sits
# in a paragraph, list item or table row that names CellSpec, and names the save_*
# function of any other record model it lists.
_PUBLISH_DOCS = [
    "AGENTS.md",
    "QUICKSTART.md",
    "docs/scope.md",
    "docs/workspace-authoring.md",
    "docs/how-battinfo-is-built.md",
    "docs/pages/api-reference.rst",
]
_PUBLISH_MENTION = re.compile(r"battinfo\.publish(?![\w.])|``publish``")


def _logical_lines(text: str) -> list[str]:
    """Paragraphs, list items and table rows, each joined onto one line."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
        elif lines and lines[-1] and not re.match(r"([-*+]|\d+\.)\s|\|", line):
            lines[-1] += " " + line
        else:
            lines.append(line)
    return [line for line in lines if line and not line.startswith(".. ")]


@pytest.mark.parametrize("rel", _PUBLISH_DOCS)
def test_docs_hand_publish_a_cell_spec_only(rel: str) -> None:
    claims = [
        line for line in _logical_lines((ROOT / rel).read_text(encoding="utf-8")) if _PUBLISH_MENTION.search(line)
    ]
    assert claims, f"{rel} no longer mentions battinfo.publish; drop it from this check"
    for claim in claims:
        assert "CellSpec" in claim, f"{rel}: publish() takes a CellSpec only, but this does not say so:\n{claim}"
        assert "linked graph" not in claim, f"{rel}: publish() takes one CellSpec:\n{claim}"
        for model, _, save_function in _OTHER_MODELS:
            if f"`{model}`" in claim:
                assert save_function in claim, (
                    f"{rel}: names `{model}` next to publish() but not {save_function}:\n{claim}"
                )


# ---------------------------------------------------------------------------
# publish_record() — low-level API
# ---------------------------------------------------------------------------

_EXAMPLE_CELL_TYPE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
_EXAMPLE_CELL_INSTANCE = ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json"
_EXAMPLE_DATASET = ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json"
_EXAMPLE_TEST_PROTOCOL = ROOT / "examples" / "test-protocol" / "test-protocol-8r2m-4v6k-9p3t-7n5x.json"


def test_publish_record_cell_spec_writes_three_files(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)

    assert result["status"] == "published"
    assert result["entity_type"] == "cell-spec"
    files = result["files"]
    assert any(f.endswith("index.json") for f in files)
    assert any(f.endswith("index.jsonld") for f in files)
    assert any(f.endswith("index.html") for f in files)
    out_dir = Path(result["output_dir"])
    assert (out_dir / "index.json").exists()
    assert (out_dir / "index.jsonld").exists()
    assert (out_dir / "index.html").exists()


def test_publish_record_jsonld_is_valid_json_ld(tmp_path: Path) -> None:
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    assert jsonld_files, "No index.jsonld produced"
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    assert "@context" in doc


def test_publish_record_cell_spec_is_battery_cell_specification(tmp_path: Path) -> None:
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    types = doc["@type"] if isinstance(doc["@type"], list) else [doc["@type"]]
    assert "BatteryCellSpecification" in types, "@type must include BatteryCellSpecification"
    assert "schema:CreativeWork" in types, "@type must include schema:CreativeWork for schema.org alignment"


def test_descriptor_instance_nodes_have_dual_type() -> None:
    """Cell instance nodes must carry both BatteryCell (EMMO) and schema:IndividualProduct (schema.org)."""
    from battinfo.transform.json_to_jsonld import _descriptor_instances_to_jsonld

    nodes = _descriptor_instances_to_jsonld(
        [
            {"id": "https://w3id.org/battinfo/cell/test1", "name": "cell-1"},
        ]
    )
    assert len(nodes) == 1
    types = nodes[0]["@type"]
    if isinstance(types, str):
        types = [types]
    assert "BatteryCell" in types, "BatteryCell (EMMO) must be in @type"
    assert "schema:IndividualProduct" in types, "schema:IndividualProduct (schema.org) must be in @type"


def _value_references(node: object) -> list[object]:
    found: list[object] = []
    if isinstance(node, dict):
        refs = node.get("schema:valueReference")
        if refs is not None:
            found.extend(refs if isinstance(refs, list) else [refs])
        for value in node.values():
            found.extend(_value_references(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_value_references(value))
    return found


def test_publish_record_jsonld_value_references_are_named_qualifiers(tmp_path: Path) -> None:
    """schema:valueReference carries named qualifiers only, never a bare value.

    The descriptor emitter once hung range bounds on schema:valueReference. A
    declared value's conditions ride it on purpose, as named
    schema:PropertyValue nodes: the example's 10 s pulse duration is one.
    """
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    refs = _value_references(doc)
    assert refs, "the example's pulse duration should be a named qualifier"
    for ref in refs:
        assert isinstance(ref, dict), ref
        assert ref.get("@type") == "schema:PropertyValue" and ref.get("schema:propertyID"), ref


def test_publish_record_skip_jsonld(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path, build_jsonld=False)
    files = result["files"]
    assert any(f.endswith("index.json") for f in files)
    assert not any(f.endswith("index.jsonld") for f in files)


def test_publish_record_skip_html(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path, build_html=False)
    files = result["files"]
    assert not any(f.endswith("index.html") for f in files)


def test_publish_record_returns_correct_uid(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = publish_record(doc, target_root=tmp_path)
    assert result["uid"] == doc["cell_spec"]["id"].split("/")[-1]


def test_publish_record_dataset(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_DATASET, target_root=tmp_path)
    assert result["status"] == "published"
    assert result["entity_type"] == "dataset"


def test_publish_record_test_protocol(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_TEST_PROTOCOL, target_root=tmp_path)
    assert result["status"] == "published"
    assert result["entity_type"] == "test-protocol"


# ---------------------------------------------------------------------------
# save_record() — dry-run and duplicate handling
# ---------------------------------------------------------------------------


def test_save_record_dry_run_does_not_write(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = save_record(doc, source_root=tmp_path / "src", dry_run=True)
    assert result["status"] == "dry-run"
    # Nothing written
    assert not any(tmp_path.rglob("*.json"))


def test_save_record_creates_file(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = save_record(doc, source_root=tmp_path / "src")
    assert result["status"] == "created"
    assert Path(result["path"]).exists()


def test_save_record_duplicate_error_by_default(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    with pytest.raises(ValueError, match="already exists"):
        save_record(doc, source_root=tmp_path / "src")


def test_save_record_upsert_mode_updates(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    result = save_record(doc, source_root=tmp_path / "src", mode="upsert")
    assert result["status"] == "updated"


def test_save_record_duplicate_policy_return_existing(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    result = save_record(doc, source_root=tmp_path / "src", duplicate_policy="return_existing")
    assert result["status"] == "exists"


# ---------------------------------------------------------------------------
# A record's files are named after the uid that ends its IRI, and only a uid
# ---------------------------------------------------------------------------
#
# Record IRIs come from records and registry responses that someone else may
# have written. On Windows an IRI ending in "..\..\..\..\x" named a file
# outside the records folder: the file name's "cell-spec-" prefix takes the
# first "..", and the other three climb out of cell-spec/ and records/.

_CLIMBING_TAIL = "\\".join(["..", "..", "..", "..", "x"])


def _cell_spec_with_id(iri: str) -> dict:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    doc["cell_spec"]["id"] = iri
    return doc


def _files_under(top: Path) -> list[Path]:
    return [path for path in top.rglob("*") if path.is_file()]


@pytest.mark.parametrize(
    "uid",
    ["../../x", _CLIMBING_TAIL, "C:x", "", "..", "AAAA-BBBB-CCCC-DDDD", "aaaabbbbccccdddd", "aaaa-bbbb-cccc-dddd\n"],
)
def test_save_entity_path_takes_only_a_dashed_uid(tmp_path: Path, uid: str) -> None:
    with pytest.raises(ValueError, match="not a record uid"):
        save_entity_path("cell-spec", uid, tmp_path)


def test_save_entity_path_names_the_file_after_the_uid(tmp_path: Path) -> None:
    assert save_entity_path("cell-spec", "pge5-wer6-2q82-v9k0", tmp_path) == (
        tmp_path / "cell-spec" / "cell-spec-pge5-wer6-2q82-v9k0.json"
    )


def test_save_record_refuses_an_id_that_does_not_end_in_a_uid(tmp_path: Path) -> None:
    doc = _cell_spec_with_id(f"https://w3id.org/battinfo/spec/{_CLIMBING_TAIL}")

    with pytest.raises(ValueError, match="not a record uid"):
        save_record(doc, source_root=tmp_path / "a" / "b" / "records", validate=False)

    assert _files_under(tmp_path) == []


def test_a_lookup_by_an_id_that_is_not_a_uid_opens_only_the_kinds_files(tmp_path: Path) -> None:
    """A record may sit under any file name, so the lookup still lists the kind's files."""
    source_root = tmp_path / "a" / "b" / "records"
    saved = source_root / "cell-spec" / "written-by-hand.json"
    saved.parent.mkdir(parents=True)
    saved.write_text("{}", encoding="utf-8")
    # Where the file named after that uid would land on Windows.
    (tmp_path / "a" / "b" / "x.json").write_text("{}", encoding="utf-8")

    assert entity_files_for_uid("cell-spec", _CLIMBING_TAIL, source_root) == [saved]
    assert entity_files_for_uid("parameter-set", _CLIMBING_TAIL, source_root) == []


@pytest.mark.parametrize("iri", ["https://w3id.org/battinfo/../..", "https://w3id.org/battinfo/../pge5-wer6-2q82-v9k0"])
def test_publish_record_refuses_an_id_that_names_a_folder_outside(tmp_path: Path, iri: str) -> None:
    target_root = tmp_path / "a" / "b" / "site"

    with pytest.raises(ValueError, match="must end in"):
        publish_record(_cell_spec_with_id(iri), target_root=target_root, validate=False)

    assert _files_under(tmp_path) == []


# ---------------------------------------------------------------------------
# The publication page embeds the record as data, never as markup
# ---------------------------------------------------------------------------


class _ScriptBodies(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.bodies: list[str] = []
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._inside = True
            self.bodies.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.bodies[-1] += data


def test_the_publication_page_keeps_record_text_inside_its_script(tmp_path: Path) -> None:
    payload = {
        "@context": {"schema": "https://schema.org/"},
        "@graph": [
            {
                "@id": "https://w3id.org/battinfo/dataset/pge5-wer6-2q82-v9k0",
                "@type": "schema:Dataset",
                "schema:name": "Cycling <b>data</b> & more",
                "schema:description": "</script><script>alert(document.domain)</script><!-- -->",
            }
        ],
    }

    page = save_publication_html(payload, tmp_path / "index.html").read_text(encoding="utf-8")

    parser = _ScriptBodies()
    parser.feed(page)
    assert len(parser.bodies) == 1
    assert json.loads(parser.bodies[0]) == payload
    assert "<script>alert" not in page
    assert "<title>Cycling &lt;b&gt;data&lt;/b&gt; &amp; more</title>" in page
