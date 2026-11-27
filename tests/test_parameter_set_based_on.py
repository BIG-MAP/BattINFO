"""What a parameter set, or one of its values, was derived from (``is_based_on``).

Rules under test:
- v2 of the parameter-set schema (``schema/v2/parameter-set.schema.json``)
  takes ``is_based_on`` on the body and on every claim, with the shape a
  dataset's has (an array of unique URIs); it is the 0.8.0 schema and that
  field, so every record the 0.8.0 schema takes stays valid, and the 0.8.0
  schema keeps refusing the field at its own URL (IDENTIFIER_POLICY 11.1);
- parameter sets validate against v2 wherever a schema is chosen per record
  type, and every schema is served at its path, its relative ``$ref``s naming
  schemas that are served too;
- the builder turns a bare string into a one-item list, keeps a URI given
  twice once, and refuses what is not an absolute URI;
- the field passes through every authoring path (the builder, a save, the
  workspace, a BPX import) and never enters the IRI;
- the JSON-LD carries it as ``schema:isBasedOn`` references, on the
  parameter-set node for the whole set and on each claim node for one value,
  in a claim batch and in a parameter file, and the deposit graph checks pass;
- a record or claim that names the record itself is flagged
  (``semantic.parameter_set_based_on_itself``), a warning under the default
  policy and an error under strict and publisher;
- a BPX export is the same with or without it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

import battinfo
from battinfo.api import EXAMPLES_ROOT, create_parameter_set, save_parameter_set, supersede_parameter_set
from battinfo.entities import kind_for_type
from battinfo.interop import bpx_file_distribution, from_bpx_parameters, to_bpx
from battinfo.jsonld import record_to_jsonld
from battinfo.namespace import OLD_FORM_BASE
from battinfo.validate import validate_jsonld, validate_publication_report, validate_record_report
from battinfo.validate.schema import build_validator, schema_for_rel_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "src" / "battinfo" / "data" / "schemas"
SCHEMA_BASE = "https://w3id.org/battinfo/schema/"
V1 = "parameter-set.schema.json"
V2 = "v2/parameter-set.schema.json"
SCHEMA_IS_BASED_ON = URIRef("https://schema.org/isBasedOn")
SELF_CODE = "semantic.parameter_set_based_on_itself"

DATASET_A = "https://w3id.org/battinfo/id/1001/dataset/aaaa-bbbb-cccc-0001"
DATASET_B = "https://w3id.org/battinfo/id/1001/dataset/aaaa-bbbb-cccc-0002"
OTHER_SET = "https://w3id.org/battinfo/id/1001/dataset/aaaa-bbbb-cccc-0003"
DOI_URL = "https://doi.org/10.5281/zenodo.1234567"

OCP_CLAIM = {
    "parameter": "ocp",
    "curve": {"x_quantity": "stoichiometry", "x": [0.0, 0.5, 1.0], "y": [1.2, 0.2, 0.1], "y_unit": "V"},
    "provenance_class": "derived",
}
DENSITY_CLAIM = {"parameter": "density", "quantity": {"value": 2.26, "unit": "g/cm3"}, "provenance_class": "literature"}

BPX_DOCUMENT = {
    "Header": {"BPX": "1.1.0", "Title": "Example pouch cell", "Model": "Partial"},
    "Parameterisation": {
        "Cell": {"Nominal cell capacity [A.h]": 5.0, "Electrode area [m2]": 0.1},
        "Negative electrode": {"Particle radius [m]": 5.86e-6, "Thickness [m]": 8.52e-5},
    },
    "State": {"Initial conditions": {"Initial state-of-charge": 1.0}},
}


def _claim_batch(**fields: object) -> dict:
    defaults: dict = {
        "name": "OCP from p-OCV measurements - graphite",
        "material_kind": "graphite",
        "is_based_on": [OTHER_SET, DOI_URL],
        "claims": [
            {**OCP_CLAIM, "is_based_on": [DATASET_A, DATASET_B]},
            {**DENSITY_CLAIM, "is_based_on": [DATASET_A]},
        ],
    }
    return create_parameter_set(**{**defaults, **fields})


def _bpx_raw() -> bytes:
    return json.dumps(BPX_DOCUMENT, indent=2).encode("utf-8")


def _parameter_file(**record_kwargs: object) -> dict:
    raw = _bpx_raw()
    return from_bpx_parameters(raw).to_parameter_set(
        virtual_cell=True,
        materials={"negative": "graphite"},
        distributions=[
            bpx_file_distribution(
                raw, name="example-cell.bpx.json", content_url="https://files.example.org/example-cell.bpx.json"
            )
        ],
        retrieved_at=1750000000,
        **record_kwargs,
    )


def _codes(report, severity: str) -> list[str]:
    return [issue.code for issue in report.issues if issue.severity == severity]


def _schema_errors(record: dict, schema: str = V2) -> list[str]:
    validator = build_validator(schema_for_rel_path(schema))
    return [f"{'/'.join(map(str, error.absolute_path))}: {error.validator}" for error in validator.iter_errors(record)]


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else [value]


def _based_on_ids(node: dict) -> list[str]:
    return [ref["@id"] for ref in node.get("schema:isBasedOn", [])]


# ── schema ───────────────────────────────────────────────────────────────────


def _without_annotations(schema: object) -> object:
    from test_schema_freeze import validation_content

    return validation_content(schema)


def test_parameter_sets_validate_against_v2() -> None:
    kind = kind_for_type("parameter-set")
    assert kind is not None and kind.schema_file == V2
    v2 = schema_for_rel_path(V2)
    assert v2["$id"] == SCHEMA_BASE + V2
    assert schema_for_rel_path(V1)["$id"] == SCHEMA_BASE + V1


def test_v2_is_the_0_8_0_schema_and_is_based_on_at_both_levels() -> None:
    v1 = _without_annotations(schema_for_rel_path(V1))
    v2 = json.loads(json.dumps(_without_annotations(schema_for_rel_path(V2))))
    assert v2["$id"] == SCHEMA_BASE + V2
    v2["$id"] = SCHEMA_BASE + V1
    expected = {"type": "array", "items": {"type": "string", "format": "uri"}, "uniqueItems": True}
    assert v2["properties"]["parameter_set"]["properties"].pop("is_based_on") == expected
    assert v2["$defs"]["Claim"]["properties"].pop("is_based_on") == expected
    # The one other difference: the module refs climb out of v2/ to the same files.
    restored = json.loads(json.dumps(v2).replace('"../modules/', '"modules/'))
    assert restored == v1


def _shipped_parameter_set_records() -> list[Path]:
    trees = [ROOT / "examples" / "parameter-set", EXAMPLES_ROOT / "parameter-set", ROOT / "tests" / "fixtures"]
    paths = sorted({path for tree in trees for path in tree.rglob("*.json")})
    records = [path for path in paths if '"parameter_set"' in path.read_text(encoding="utf-8")]
    assert len(records) >= 11, records
    return records


@pytest.mark.parametrize("path", _shipped_parameter_set_records(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_shipped_parameter_set_valid_under_0_8_0_is_valid_under_v2(path: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    assert _schema_errors(record, V1) == []
    assert _schema_errors(record, V2) == []
    assert validate_record_report(record, policy="default").ok


def test_the_0_8_0_schema_still_refuses_is_based_on() -> None:
    record = _claim_batch()
    assert _schema_errors(record, V2) == []
    errors = _schema_errors(record, V1)
    assert "parameter_set: additionalProperties" in errors
    assert "parameter_set/claims/0: additionalProperties" in errors


def test_every_schema_is_served_at_its_path_and_its_refs_name_served_schemas() -> None:
    from urllib.parse import urljoin

    ids: dict[str, str] = {}
    for path in sorted(SCHEMA_ROOT.rglob("*.json")):
        relative = path.relative_to(SCHEMA_ROOT).as_posix()
        schema_id = json.loads(path.read_text(encoding="utf-8")).get("$id")
        # The registry serves each vendored file at schema/<its path>.
        assert schema_id == SCHEMA_BASE + relative
        ids[schema_id] = relative
    assert SCHEMA_BASE + V2 in ids
    unresolved = []

    def walk(node: object, base: str) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                target = urljoin(base, ref.split("#", 1)[0])
                if target not in ids:
                    unresolved.append((base, ref))
            for value in node.values():
                walk(value, base)
        elif isinstance(node, list):
            for value in node:
                walk(value, base)

    for schema_id, relative in ids.items():
        walk(json.loads((SCHEMA_ROOT / relative).read_text(encoding="utf-8")), schema_id)
    assert unresolved == []


def test_the_schema_takes_is_based_on_on_the_body_and_on_each_claim() -> None:
    record = _claim_batch()
    assert record["parameter_set"]["is_based_on"] == [OTHER_SET, DOI_URL]
    assert _schema_errors(record) == []

    parameter_file = _parameter_file(is_based_on=[OTHER_SET])
    parameter_file["parameter_set"]["parts"][0]["claims"][0]["is_based_on"] = [DATASET_A]
    assert _schema_errors(parameter_file) == []


@pytest.mark.parametrize(
    "value,validator",
    [
        (DATASET_A, "type"),
        ([DATASET_A, DATASET_A], "uniqueItems"),
        (["not a uri"], "format"),
        ([42], "type"),
    ],
    ids=["bare-string", "duplicate", "relative", "number"],
)
@pytest.mark.parametrize("level", ["set", "claim"])
def test_the_schema_refuses_a_malformed_is_based_on(level: str, value: object, validator: str) -> None:
    record = copy.deepcopy(_claim_batch(is_based_on=None, claims=[DENSITY_CLAIM]))
    holder = record["parameter_set"] if level == "set" else record["parameter_set"]["claims"][0]
    holder["is_based_on"] = value
    errors = _schema_errors(record)
    assert errors, errors
    assert any(error.endswith(validator) for error in errors), errors
    assert not validate_record_report(record, policy="default").ok


# ── the builder ──────────────────────────────────────────────────────────────


def test_a_bare_string_is_one_uri_not_a_list_of_characters() -> None:
    record = _claim_batch(
        is_based_on=DOI_URL,
        claims=[{**DENSITY_CLAIM, "is_based_on": DATASET_A}],
    )
    assert record["parameter_set"]["is_based_on"] == [DOI_URL]
    assert record["parameter_set"]["claims"][0]["is_based_on"] == [DATASET_A]


def test_a_uri_given_twice_is_kept_once_in_its_first_place() -> None:
    record = _claim_batch(
        is_based_on=[DOI_URL, OTHER_SET, DOI_URL],
        claims=[{**DENSITY_CLAIM, "is_based_on": [DATASET_B, DATASET_A, DATASET_B]}],
    )
    assert record["parameter_set"]["is_based_on"] == [DOI_URL, OTHER_SET]
    assert record["parameter_set"]["claims"][0]["is_based_on"] == [DATASET_B, DATASET_A]


def test_an_empty_is_based_on_is_left_out() -> None:
    record = _claim_batch(is_based_on=[], claims=[{**DENSITY_CLAIM, "is_based_on": []}])
    assert "is_based_on" not in record["parameter_set"]
    assert "is_based_on" not in record["parameter_set"]["claims"][0]


@pytest.mark.parametrize(
    "value,error",
    [
        ("datasets/a.csv", ValueError),
        ([DATASET_A, ""], ValueError),
        ([DATASET_A, 7], ValueError),
        ({"@id": DATASET_A}, TypeError),
    ],
    ids=["relative", "empty", "number", "mapping"],
)
@pytest.mark.parametrize("level", ["set", "claim"])
def test_the_builder_refuses_what_is_not_a_uri(level: str, value: object, error: type[Exception]) -> None:
    fields: dict = {"is_based_on": value} if level == "set" else {"claims": [{**DENSITY_CLAIM, "is_based_on": value}]}
    with pytest.raises(error, match="is_based_on"):
        _claim_batch(**fields)


def test_is_based_on_never_enters_the_iri() -> None:
    plain = create_parameter_set(name="A - graphite", material_kind="graphite", claims=[DENSITY_CLAIM])
    based = create_parameter_set(
        name="A - graphite",
        material_kind="graphite",
        is_based_on=[DOI_URL],
        claims=[{**DENSITY_CLAIM, "is_based_on": [DATASET_A]}],
    )
    assert based["parameter_set"]["id"] == plain["parameter_set"]["id"]
    assert _parameter_file(is_based_on=[OTHER_SET])["parameter_set"]["id"] == _parameter_file()["parameter_set"]["id"]


def test_supersede_keeps_is_based_on_after_supersedes() -> None:
    legacy = _claim_batch()
    legacy["parameter_set"]["id"] = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-0009"
    replacement = supersede_parameter_set(legacy)["parameter_set"]
    assert replacement["is_based_on"] == [OTHER_SET, DOI_URL]
    keys = list(replacement)
    assert keys.index("supersedes") == keys.index("is_based_on") - 1


# ── saving ───────────────────────────────────────────────────────────────────


def test_a_saved_record_keeps_is_based_on_at_both_levels(tmp_path: Path) -> None:
    record = _claim_batch()
    saved = save_parameter_set(record, source_root=tmp_path, validation_policy="strict")
    stored = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    assert stored["parameter_set"]["is_based_on"] == [OTHER_SET, DOI_URL]
    assert [claim.get("is_based_on") for claim in stored["parameter_set"]["claims"]] == [
        [DATASET_A, DATASET_B],
        [DATASET_A],
    ]


def test_a_kwargs_draft_saves_is_based_on(tmp_path: Path) -> None:
    saved = save_parameter_set(
        {
            "name": "A - graphite",
            "material_kind": "graphite",
            "is_based_on": DOI_URL,
            "claims": [{**DENSITY_CLAIM, "is_based_on": DATASET_A}],
        },
        source_root=tmp_path,
    )
    stored = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    assert stored["parameter_set"]["is_based_on"] == [DOI_URL]
    assert stored["parameter_set"]["claims"][0]["is_based_on"] == [DATASET_A]


def test_the_workspace_takes_is_based_on_and_saves_it(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path / "lab", registry_url=None)
    ws.add(
        "parameter_set",
        name="OCP from p-OCV measurements - graphite",
        material="graphite",
        is_based_on=DOI_URL,
        claims=[{**OCP_CLAIM, "is_based_on": [DATASET_A, DATASET_B]}],
    )
    ws.save()
    files = sorted((tmp_path / "lab" / ".battinfo" / "records" / "parameter-set").glob("*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["parameter_set"]["is_based_on"] == [DOI_URL]
    assert stored["parameter_set"]["claims"][0]["is_based_on"] == [DATASET_A, DATASET_B]


def test_a_bpx_import_keeps_the_is_based_on_the_caller_gives() -> None:
    record = _parameter_file(is_based_on=[OTHER_SET, DOI_URL])
    assert record["parameter_set"]["is_based_on"] == [OTHER_SET, DOI_URL]
    assert validate_record_report(record, policy="publisher").ok


def test_a_bpx_export_is_the_same_with_or_without_is_based_on() -> None:
    plain = _parameter_file()
    based = _parameter_file(is_based_on=[OTHER_SET])
    for part in based["parameter_set"]["parts"]:
        for claim in part["claims"]:
            claim["is_based_on"] = [DATASET_A]
    assert to_bpx(based).bpx == to_bpx(plain).bpx


# ── JSON-LD ──────────────────────────────────────────────────────────────────


def test_a_claim_batch_emits_is_based_on_on_the_set_and_on_each_claim_node() -> None:
    doc = record_to_jsonld(_claim_batch(), "parameter-set")
    assert _based_on_ids(doc) == [OTHER_SET, DOI_URL]
    (quantity,) = _as_list(doc["hasProperty"])
    assert quantity["schema:propertyID"] == "density"
    assert _based_on_ids(quantity) == [DATASET_A]
    (curve,) = _as_list(doc["schema:variableMeasured"])
    assert curve["schema:propertyID"] == "ocp"
    assert _based_on_ids(curve) == [DATASET_A, DATASET_B]
    assert validate_jsonld(doc).ok


def test_a_parameter_file_emits_is_based_on_on_the_set_and_on_its_part_claims() -> None:
    record = _parameter_file(is_based_on=[OTHER_SET])
    negative = next(part for part in record["parameter_set"]["parts"] if part["part"] == "negative_material")
    negative["claims"][0]["is_based_on"] = [DATASET_A]
    assert validate_record_report(record, policy="publisher").ok

    doc = record_to_jsonld(record, "parameter-set")
    assert _based_on_ids(doc) == [OTHER_SET]
    part_node = next(
        node
        for node in _as_list(doc["schema:hasPart"])
        if any(
            facet.get("schema:value") == "negative_material" for facet in _as_list(node["schema:additionalProperty"])
        )
    )
    claim_nodes = _as_list(part_node.get("hasProperty", [])) + _as_list(part_node.get("schema:variableMeasured", []))
    assert [_based_on_ids(node) for node in claim_nodes].count([DATASET_A]) == 1
    assert validate_jsonld(doc).ok


def test_is_based_on_expands_to_schema_is_based_on_references() -> None:
    doc = record_to_jsonld(_claim_batch(), "parameter-set", context="inline")
    graph = Graph().parse(data=json.dumps(doc), format="json-ld")
    objects = list(graph.objects(None, SCHEMA_IS_BASED_ON))
    assert all(isinstance(obj, URIRef) for obj in objects)
    assert {str(obj) for obj in objects} == {OTHER_SET, DOI_URL, DATASET_A, DATASET_B}
    record_node = URIRef(doc["@id"])
    assert {str(obj) for obj in graph.objects(record_node, SCHEMA_IS_BASED_ON)} == {OTHER_SET, DOI_URL}
    # The hosted-context document carries the same references.
    hosted = record_to_jsonld(_claim_batch(), "parameter-set", context="url")
    assert hosted["@context"] == "https://w3id.org/battinfo/context/records/v1.json"
    assert hosted["schema:isBasedOn"] == doc["schema:isBasedOn"]


def test_the_deposit_graph_carries_is_based_on_and_passes_its_checks() -> None:
    from battinfo.ws import AuthoringWorkspace

    records = [_claim_batch(), _parameter_file(is_based_on=[OTHER_SET])]
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        {"parameter-set": records},
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="Parameter sets",
        license="cc-by-4.0",
        creators=[{"name": "Doe, Jane"}],
    )
    nodes = {node.get("@id"): node for node in doc["@graph"] if isinstance(node, dict)}
    claim_batch = nodes[records[0]["parameter_set"]["id"]]
    assert _based_on_ids(claim_batch) == [OTHER_SET, DOI_URL]
    assert _based_on_ids(_as_list(claim_batch["schema:variableMeasured"])[0]) == [DATASET_A, DATASET_B]
    assert _based_on_ids(nodes[records[1]["parameter_set"]["id"]]) == [OTHER_SET]
    report = validate_publication_report(doc, policy="publisher")
    assert report.ok, [issue.render() for issue in report.errors]


# ── a record based on itself ─────────────────────────────────────────────────


def _self_based(level: str, *, old_form: bool = False) -> dict:
    record = _claim_batch(is_based_on=None, claims=[DENSITY_CLAIM])
    own = record["parameter_set"]["id"]
    named = own.replace("/id/1001/", "/") if old_form else own
    holder = record["parameter_set"] if level == "set" else record["parameter_set"]["claims"][0]
    holder["is_based_on"] = [DOI_URL, named]
    return record


@pytest.mark.parametrize("level", ["set", "claim"])
def test_a_record_based_on_itself_warns_by_default_and_fails_strict_and_publisher(level: str) -> None:
    record = _self_based(level)
    default = validate_record_report(record, policy="default")
    assert default.ok
    assert SELF_CODE in _codes(default, "warning")
    for policy in ("strict", "publisher"):
        report = validate_record_report(record, policy=policy)
        assert not report.ok
        assert SELF_CODE in _codes(report, "error")
    (issue,) = [issue for issue in default.issues if issue.code == SELF_CODE]
    expected = "parameter_set.is_based_on[1]" if level == "set" else "parameter_set.claims[0].is_based_on[1]"
    assert issue.path == expected


def test_the_old_form_of_the_records_own_iri_counts_as_itself() -> None:
    report = validate_record_report(_self_based("set", old_form=True), policy="strict")
    assert SELF_CODE in _codes(report, "error")


def test_a_part_claim_based_on_its_own_parameter_file_is_flagged() -> None:
    record = _parameter_file()
    record["parameter_set"]["parts"][0]["claims"][0]["is_based_on"] = [record["parameter_set"]["id"]]
    report = validate_record_report(record, policy="strict")
    assert [issue.path for issue in report.issues if issue.code == SELF_CODE] == [
        "parameter_set.parts[0].claims[0].is_based_on[0]"
    ]


def test_naming_other_records_is_not_flagged() -> None:
    record = _claim_batch()
    for policy in ("default", "strict", "publisher"):
        report = validate_record_report(record, policy=policy)
        assert report.ok, [issue.render() for issue in report.errors]
        assert SELF_CODE not in _codes(report, "warning") + _codes(report, "error")


def test_a_published_example_keeps_validating_with_is_based_on(tmp_path: Path) -> None:
    from battinfo.api import EXAMPLES_ROOT

    path = EXAMPLES_ROOT / "parameter-set" / "parameter-set-rnc6-edv8-m43x-ebnq.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["parameter_set"]["is_based_on"] = [DOI_URL]
    record["parameter_set"]["parts"][0]["claims"][0]["is_based_on"] = [DATASET_A]
    assert validate_record_report(record, policy="publisher").ok
    saved = save_parameter_set(record, source_root=tmp_path, base=OLD_FORM_BASE)
    stored = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    assert stored["parameter_set"]["is_based_on"] == [DOI_URL]
