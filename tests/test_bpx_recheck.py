"""BPX import and export: the fixes from the 2026-10-11 re-check.

Each test reproduces one finding of the re-check and pins its fix:

- the cell and state claims of a BPX file carry no provenance class unless
  the caller gives one, and a class can be set per part (N-01);
- a search by material collates only that material's claims (N-03);
- a zero transport value is named in a warning and kept as the file states
  it (B-13);
- every unit a BPX import writes resolves to an EMMO unit (B-10);
- the JSON-LD says what the record does not hold (N-02);
- a parameter set in a deposit graph passes the publication shape checks;
- smaller fixes: missing fields of an export (B-02), unpinned URLs (N-05),
  a runnable copy that changes nothing (N-06), the check_bpx detail (N-07),
  misspelt keywords (B-16), the from_bpx docstring (B-15) and ASCII interop
  docstrings (B-20).
"""

from __future__ import annotations

import json
import pydoc
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
import battinfo.interop  # noqa: E402
from battinfo.api import create_parameter_set, query_parameter_sets, save_parameter_set  # noqa: E402
from battinfo.interop import (  # noqa: E402
    BpxImportResult,
    bpx_file_distribution,
    check_bpx,
    from_bpx,
    from_bpx_parameters,
    to_bpx,
    upgrade_bpx,
)
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.parameters import bpx_field, collate_claims, parameters_vocabulary  # noqa: E402
from battinfo.validate import validate_publication_report, validate_record_report  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
NODE_FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.node.bpx.json"
SOURCE_URL = "https://files.example.org/parameter-sets/x/source.bpx.json"
RUNNABLE_URL = "https://files.example.org/parameter-sets/x/runnable.bpx.json"
MATERIAL_SPEC_IRI = "https://w3id.org/battinfo/spec/cccc-dddd-eeee-ffff"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _parts(record: dict) -> dict[str, list[dict]]:
    return {part["part"]: part["claims"] for part in record["parameter_set"]["parts"]}


def _node(doc: dict) -> dict:
    return doc["@graph"][0] if "@graph" in doc else doc


def _as_list(value) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


# -- N-01: no provenance class BPX does not state ------------------------------


def test_cell_and_state_claims_carry_no_provenance_class() -> None:
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    parts = _parts(record)
    for name in ("cell", "state"):
        assert parts[name], name
        assert all("provenance_class" not in claim for claim in parts[name]), name
    for name in set(parts) - {"cell", "state"}:
        assert {claim["provenance_class"] for claim in parts[name]} == {"fitted"}, name
    assert validate_record_report(record, policy="strict").ok

    # Nor does the JSON-LD state one for them.
    node = _node(record_to_jsonld(record, "parameter-set"))
    for part_node in _as_list(node["schema:hasPart"]):
        facets = {f["schema:name"]: f["schema:value"] for f in _as_list(part_node["schema:additionalProperty"])}
        annotated = [
            claim_node
            for claim_node in _as_list(part_node.get("hasProperty"))
            + _as_list(part_node.get("schema:variableMeasured"))
            if any(
                a.get("schema:name") == "provenance_class"
                for a in _as_list(claim_node.get("schema:additionalProperty"))
            )
        ]
        if facets["part"] in ("cell", "state"):
            assert not annotated, facets["part"]
        else:
            assert annotated, facets["part"]


def test_provenance_classes_set_a_part_by_name() -> None:
    record = from_bpx_parameters(FIXTURE).to_parameter_set(
        virtual_cell=True,
        default_provenance_class="literature",
        provenance_classes={"cell": "measured", "separator": None},
    )
    parts = _parts(record)
    assert {claim["provenance_class"] for claim in parts["cell"]} == {"measured"}
    assert all("provenance_class" not in claim for claim in parts["separator"])
    assert all("provenance_class" not in claim for claim in parts["state"])
    assert {claim["provenance_class"] for claim in parts["negative_material"]} == {"literature"}
    assert validate_record_report(record, policy="strict").ok


def test_no_default_class_leaves_every_claim_unclassed() -> None:
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, default_provenance_class=None)
    assert all("provenance_class" not in claim for claims in _parts(record).values() for claim in claims)


def test_the_provenance_class_does_not_change_the_export() -> None:
    result = from_bpx_parameters(FIXTURE)
    plain = result.to_parameter_set(virtual_cell=True)
    classed = result.to_parameter_set(virtual_cell=True, provenance_classes={"cell": "measured", "state": "assumed"})
    assert plain["parameter_set"]["id"] == classed["parameter_set"]["id"]
    assert to_bpx(plain).bpx == to_bpx(classed).bpx


def test_the_packaged_bpx_examples_state_no_class_bpx_does_not_give() -> None:
    examples = ROOT / "src" / "battinfo" / "data" / "examples" / "parameter-set"
    files = 0
    for path in sorted(examples.glob("parameter-set-*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))["parameter_set"]
        if (body.get("model_context") or {}).get("tool") != "BPX" or not body.get("parts"):
            continue
        files += 1
        for part in body["parts"]:
            if part["part"] in ("cell", "state"):
                assert all("provenance_class" not in claim for claim in part["claims"]), (path.name, part["part"])
    assert files == 5


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"provenance_classes": {"negative": "fitted"}}, ValueError, "keys are part names"),
        ({"provenance_classes": {"cell": "guessed"}}, ValueError, r"provenance_classes\['cell'\]"),
        ({"default_provenance_class": "vibes"}, ValueError, "default_provenance_class"),
        ({"provenance_classes": ["cell"]}, TypeError, "maps part names"),
    ],
)
def test_bad_provenance_classes_are_refused(kwargs: dict, error: type, match: str) -> None:
    with pytest.raises(error, match=match):
        from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, **kwargs)


# -- N-03: a material search collates that material only -----------------------


def _file_record(materials: dict) -> dict:
    return from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True, materials=materials)


def _graphite_batch() -> dict:
    return create_parameter_set(
        name="Example 2020 - graphite",
        material_kind="graphite",
        claims=[
            {
                "parameter": "particle_radius",
                "quantity": {"value": 5.86e-6, "unit": "m"},
                "provenance_class": "literature",
            }
        ],
    )


def test_collate_by_material_keeps_only_that_material() -> None:
    file_record = _file_record({"negative": "graphite", "positive": "nmc111"})
    batch = _graphite_batch()

    everything = collate_claims([file_record, batch])
    assert len(everything["particle_radius"]) == 3  # both electrodes of the file, and the batch

    for spelling in ("graphite", "MCMB"):  # a kind key or an alias
        graphite = collate_claims([file_record, batch], material_kind=spelling)
        assert [claim["source"].get("part") for claim in graphite["particle_radius"]] == [
            "negative_material",
            None,
        ]
        assert all(c["source"]["material_kind"] == "graphite" for claims in graphite.values() for c in claims)
        assert "electrode_area" not in graphite  # a cell claim
        assert "thickness" not in graphite  # an electrode-build claim


def test_collate_by_material_spec() -> None:
    file_record = _file_record({"negative": MATERIAL_SPEC_IRI, "positive": "nmc111"})
    collated = collate_claims([file_record, _graphite_batch()], material_spec_id=MATERIAL_SPEC_IRI)
    assert {c["source"]["part"] for claims in collated.values() for c in claims} == {"negative_material"}


def test_query_then_collate_by_material(tmp_path: Path) -> None:
    # The re-check's reproduction: a material search, then collation.
    save_parameter_set(_file_record({"negative": "graphite", "positive": "nmc111"}), source_root=tmp_path)
    save_parameter_set(_graphite_batch(), source_root=tmp_path)
    rows = query_parameter_sets(material_kind="graphite", parameter="particle_radius", source_root=tmp_path)
    assert len(rows) == 2
    records = [row["record"] for row in rows]
    assert len(collate_claims(records)["particle_radius"]) == 3
    radii = collate_claims(records, material_kind="graphite")["particle_radius"]
    assert sorted(str(claim["source"].get("part")) for claim in radii) == ["None", "negative_material"]


# -- B-13: zero transport values are placeholders ------------------------------


def test_zero_transport_values_are_named_and_kept() -> None:
    doc = _doc()
    electrolyte = doc["Parameterisation"]["Electrolyte"]
    electrolyte["Conductivity [S.m-1]"] = 0
    electrolyte["Diffusivity [m2.s-1]"] = 0
    electrolyte["Cation transference number"] = 0
    doc["Parameterisation"]["Negative electrode"]["Diffusivity [m2.s-1]"] = -1e-14
    result = from_bpx_parameters(doc)
    warning = " ".join(w for w in result.warnings if "transport values" in w)  # one per block
    for path in (
        "Parameterisation/Electrolyte/Conductivity [S.m-1] = 0",
        "Parameterisation/Electrolyte/Diffusivity [m2.s-1] = 0",
        "Parameterisation/Electrolyte/Cation transference number = 0",
        "Parameterisation/Negative electrode/Diffusivity [m2.s-1] = -1e-14",
    ):
        assert path in warning, path

    # Kept as the file states them, so the export gives the file back.
    record = result.to_parameter_set(virtual_cell=True)
    values = {
        claim["parameter"]: claim["quantity"]["value"] for claim in _parts(record)["electrolyte"] if "quantity" in claim
    }
    assert values["ionic_conductivity"] == 0
    assert values["transference_number"] == 0
    exported = to_bpx(record).bpx["Parameterisation"]
    for field in ("Conductivity [S.m-1]", "Diffusivity [m2.s-1]", "Cation transference number"):
        assert exported["Electrolyte"][field] == 0 and isinstance(exported["Electrolyte"][field], int), field
    assert exported["Negative electrode"]["Diffusivity [m2.s-1]"] == -1e-14


def _placeholder_doc() -> dict:
    """The fixture with the zero electrolyte transport values of the Molicel P45B file."""
    doc = _doc()
    electrolyte = doc["Parameterisation"]["Electrolyte"]
    electrolyte["Conductivity [S.m-1]"] = 0
    electrolyte["Diffusivity [m2.s-1]"] = 0
    electrolyte["Cation transference number"] = 0
    return doc


PLACEHOLDERS = {"ionic_conductivity", "electrolyte_diffusivity", "transference_number"}


def _electrolyte(record: dict) -> dict[str, dict]:
    return {claim["parameter"]: claim for claim in _parts(record)["electrolyte"]}


def test_a_transport_placeholder_gets_no_provenance_class() -> None:
    result = from_bpx_parameters(_placeholder_doc())
    record = result.to_parameter_set(virtual_cell=True)
    claims = _electrolyte(record)
    assert set(claims) == PLACEHOLDERS
    assert all("provenance_class" not in claim for claim in claims.values())

    # A positive value in the same part keeps the default class.
    doc = _placeholder_doc()
    doc["Parameterisation"]["Electrolyte"]["Cation transference number"] = 0.25
    claims = _electrolyte(from_bpx_parameters(doc).to_parameter_set(virtual_cell=True))
    assert claims["transference_number"]["provenance_class"] == "fitted"
    assert "provenance_class" not in claims["ionic_conductivity"]

    # Naming the part states a class for every claim of it, placeholders included.
    named = result.to_parameter_set(virtual_cell=True, provenance_classes={"electrolyte": "fitted"})
    assert {claim["provenance_class"] for claim in _electrolyte(named).values()} == {"fitted"}

    # The collated claims and the JSON-LD say no more than the record does.
    collated = collate_claims([record])
    assert all("provenance_class" not in claim for key in PLACEHOLDERS for claim in collated[key])
    node = _node(record_to_jsonld(record, "parameter-set"))
    for part_node in _as_list(node["schema:hasPart"]):
        facets = {f["schema:name"]: f["schema:value"] for f in _as_list(part_node["schema:additionalProperty"])}
        if facets["part"] != "electrolyte":
            continue
        for claim_node in _as_list(part_node.get("hasProperty")):
            assert not _as_list(claim_node.get("schema:additionalProperty")), claim_node["schema:propertyID"]


@pytest.mark.parametrize("policy", ["default", "strict", "publisher"])
def test_record_validation_warns_on_a_transport_placeholder(policy: str) -> None:
    record = from_bpx_parameters(_placeholder_doc()).to_parameter_set(virtual_cell=True)
    issues = [
        issue
        for issue in validate_record_report(record, policy=policy).issues
        if issue.code == "semantic.parameter_transport_not_positive"
    ]
    assert len(issues) == 3
    assert all(issue.severity == "warning" for issue in issues)
    named = " ".join(issue.message for issue in issues)
    for key in PLACEHOLDERS:
        assert f"claim '{key}'" in named, key
    assert all(
        issue.path.startswith("parameter_set.parts[") and issue.path.endswith(".quantity.value") for issue in issues
    )

    # A claim batch gets the same warning, and a positive value none.
    for value, expected in ((0.0, 1), (-1e-14, 1), (3.3e-14, 0)):
        batch = create_parameter_set(
            name="Example 2020 - graphite",
            material_kind="graphite",
            claims=[
                {
                    "parameter": "solid_diffusivity",
                    "quantity": {"value": value, "unit": "m2/s"},
                    "provenance_class": "literature",
                }
            ],
        )
        codes = [issue.code for issue in validate_record_report(batch, policy=policy).issues]
        assert codes.count("semantic.parameter_transport_not_positive") == expected, value


def test_a_transport_table_that_reaches_zero_is_not_a_placeholder() -> None:
    # The fixture's conductivity and diffusivity tables start at zero concentration.
    assert not any("transport values" in w for w in from_bpx_parameters(FIXTURE).warnings)
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    codes = {issue.code for issue in validate_record_report(record, policy="strict").issues}
    assert "semantic.parameter_transport_not_positive" not in codes


# -- B-10: BPX units are EMMO units --------------------------------------------

# Symbol -> EMMO 1.0.2 unit class added for the BPX parameter units.
BPX_UNITS = {
    "m2": "SquareMetre",
    "m3": "CubicMetre",
    "mol/m3": "MolePerCubicMetre",
    "m2/s": "SquareMetrePerSecond",
    "J/mol": "JoulePerMole",
    "V/K": "VoltPerKelvin",
    "S/m": "SiemensPerMetre",
    "1/m": "PerMetre",
    "mol.m-2.s-1": "MolePerSquareMetrePerSecond",
    "J/(kg.K)": "JoulePerKilogramKelvin",
    "W/(m.K)": "WattPerMetreKelvin",
    "W/(m2.K)": "WattPerSquareMetreKelvin",
}


def test_every_unit_a_bpx_import_writes_has_an_emmo_unit() -> None:
    from battinfo.transform.json_to_jsonld import _unit_iri

    units = {"mol/m3", "K", "1"}  # the x axes of BPX tables
    for key, entry in parameters_vocabulary()["parameters"].items():
        for block in entry.get("bpx") or {}:
            mapping = bpx_field(key, block)
            if mapping is not None:
                units.add(mapping["unit"])
    assert not sorted(unit for unit in units if not _unit_iri(unit))


def test_the_bpx_units_are_published_emmo_units() -> None:
    """Each IRI is an EMMO 1.0.2 unit class in the bundled domain-battery
    context, and the map's 0.5.2 note names every one."""
    data = ROOT / "src" / "battinfo" / "data"
    context = json.loads((data / "context" / "domain-battery.context.json").read_text(encoding="utf-8"))["@context"]
    published = {value if isinstance(value, str) else value.get("@id") for value in context.values()}
    unit_map = json.loads((data / "mappings" / "domain-battery" / "unit_map.curated.json").read_text(encoding="utf-8"))
    entries = {entry["symbol"]: entry for entry in unit_map["mappings"]}
    assert tuple(int(part) for part in unit_map["version"].split(".")) >= (0, 5, 2)
    (note,) = [note for note in unit_map["notes"] if note.startswith("0.5.2:")]
    for symbol, name in BPX_UNITS.items():
        entry = entries[symbol]
        assert entry["unit_iri"] == f"https://w3id.org/emmo#{name}", symbol
        assert entry["unit_iri"] in published, symbol
        assert symbol in note and name in note, symbol


@pytest.mark.parametrize("fixture", [FIXTURE, NODE_FIXTURE], ids=["python", "node"])
def test_a_bpx_file_imports_with_no_free_text_unit(fixture: Path) -> None:
    record = from_bpx_parameters(fixture).to_parameter_set(virtual_cell=True)
    free_text: list[tuple] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            if "schema:unitText" in value and not ("hasMeasurementUnit" in value or "schema:unitCode" in value):
                free_text.append((value.get("schema:propertyID"), value["schema:unitText"]))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(record_to_jsonld(record, "parameter-set"))
    assert free_text == []


# -- N-02: the graph says what the record does not hold ------------------------


def test_the_jsonld_says_what_the_record_does_not_hold() -> None:
    from rdflib import Graph, Namespace, URIRef

    schema = Namespace("https://schema.org/")
    record = from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True)
    body = record["parameter_set"]
    assert body["not_imported"] == ["Validation"]
    assert body["annex"]

    graph = Graph().parse(
        data=json.dumps(record_to_jsonld(record, "parameter-set", context="inline")), format="json-ld"
    )
    stated: dict[str, list[str]] = {}
    for value_node in graph.objects(URIRef(body["id"]), schema.additionalProperty):
        stated[str(graph.value(value_node, schema.name))] = sorted(
            str(v) for v in graph.objects(value_node, schema.value)
        )
    assert stated["not_imported"] == ["Validation"]
    assert stated["annex"] == sorted(body["annex"])


def _not_imported_description(record: dict) -> str:
    node = _node(record_to_jsonld(record, "parameter-set"))
    (value,) = [v for v in _as_list(node["schema:additionalProperty"]) if v["schema:name"] == "not_imported"]
    return value["schema:description"]


def test_the_not_imported_note_points_at_the_file_only_when_there_is_one() -> None:
    result = from_bpx_parameters(FIXTURE)
    with_file = result.to_parameter_set(
        virtual_cell=True, distributions=[bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)]
    )
    assert "schema:distribution is the complete copy" in _not_imported_description(with_file)
    without = _not_imported_description(result.to_parameter_set(virtual_cell=True))
    assert "this record does not hold" in without
    assert "distribution" not in without


def test_a_record_that_holds_everything_says_nothing_more() -> None:
    doc = _doc()
    doc.pop("Validation")
    doc["Parameterisation"].pop("User-defined")
    node = _node(record_to_jsonld(from_bpx_parameters(doc).to_parameter_set(virtual_cell=True), "parameter-set"))
    names = {value["schema:name"] for value in _as_list(node.get("schema:additionalProperty"))}
    assert not names & {"not_imported", "annex"}


# -- A parameter set in a deposit graph -----------------------------------------


def test_the_validator_takes_one_object_for_about_and_distribution() -> None:
    node = {
        "@context": {"schema": "https://schema.org/"},
        "@id": "https://example.org/set",
        "@type": "schema:Dataset",
        "schema:about": {"@id": "https://example.org/cell"},
        "schema:distribution": {
            "@type": "schema:DataDownload",
            "schema:contentUrl": "https://example.org/set.bpx.json",
            "schema:encodingFormat": "application/json",
            "schema:isPartOf": {"@id": "https://example.org/set"},
        },
    }
    codes = {issue.code for issue in validate_publication_report(node, policy="publisher").issues}
    assert not codes & {"publication.reference_invalid", "publication.distribution_invalid"}
    node["schema:about"] = "https://example.org/cell"  # a string is still not a reference
    node["schema:distribution"] = "https://example.org/set.bpx.json"
    codes = {issue.code for issue in validate_publication_report(node, policy="publisher").issues}
    assert {"publication.reference_invalid", "publication.distribution_invalid"} <= codes


def test_a_deposit_with_a_bpx_record_passes_the_shape_checks(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = battinfo.workspace(str(root), registry_url=None)
    ws.license("cc-by-4.0")
    (root / "example.cell-spec.json").write_text(
        json.dumps(
            {
                "name": "Example Lab EX-1",
                "manufacturer": "Example Lab",
                "model": "EX-1",
                "format": "pouch",
                "chemistry": "li-ion",
            }
        ),
        encoding="utf-8",
    )
    spec = ws.load("example.cell-spec.json")
    ws.save()
    record = from_bpx_parameters(FIXTURE).to_parameter_set(
        cell_spec_id=spec.id,
        materials={"negative": "graphite", "positive": "nmc111"},
        distributions=[bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)],
    )
    ws.add("parameter_set", record=record)
    ws.save()
    graph = ws._build_zenodo_jsonld(
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.RECORD_ID",
        record_url="https://zenodo.org/records/RECORD_ID",
        data_filenames=[],
        title="t",
        description="d",
        creators=[{"name": "Doe, Jane"}],
        contributors=[],
        license="cc-by-4.0",
        keywords=[],
        version="",
        is_version_of="",
    )
    paths = {
        f"@graph[{i}]": node
        for i, node in enumerate(graph["@graph"])
        if node.get("@id") == record["parameter_set"]["id"]
    }
    assert len(paths) == 1
    (node,) = paths.values()
    # One cell and one file: both are single objects, which the checks must take.
    assert isinstance(node["schema:about"], dict)
    assert node["schema:distribution"]["schema:isPartOf"] == {"@id": record["parameter_set"]["id"]}
    report = validate_publication_report(graph, policy="publisher")
    assert not [issue for issue in report.issues if issue.path.split(".")[0] in paths]


# -- Smaller fixes ---------------------------------------------------------------


def test_missing_required_names_the_fields_the_parser_reports() -> None:
    pytest.importorskip("bpx")
    bpx = {
        "Header": {"BPX": "1.1.0", "Title": "Example cell", "Model": "DFN"},
        "Parameterisation": {
            "Cell": {"Nominal cell capacity [A.h]": 5.0, "Electrode area [m2]": 0.1},
            "Negative electrode": {"Particle radius [m]": 5.86e-6, "Thickness [m]": 8.52e-5},
        },
    }
    record = from_bpx_parameters(bpx).to_parameter_set(virtual_cell=True)
    missing = to_bpx(record).missing_required
    # One format: "<block>.<field>", Cell fields included, and "<block>" for a block missing whole.
    assert "Negative electrode.Minimum stoichiometry" in missing
    assert "Cell.Number of electrode pairs connected in parallel to make a cell" in missing
    assert "Number of electrode pairs connected in parallel to make a cell" not in missing
    assert {"Electrolyte", "Separator", "Positive electrode"} <= set(missing)
    blocks = {"Cell", "Electrolyte", "Negative electrode", "Positive electrode", "Separator", "State", "Header"}
    assert all(path.split(".", 1)[0] in blocks for path in missing), missing
    assert len(missing) == len(set(missing))


@pytest.mark.parametrize(
    ("url", "warned"),
    [
        ("https://raw.githubusercontent.com/org/repo/main/x.bpx.json", True),
        ("https://raw.githubusercontent.com/org/repo/refs/heads/main/x.bpx.json", True),
        ("https://github.com/org/repo/raw/v1.0/x.bpx.json", True),
        ("https://gitlab.com/group/project/-/raw/main/x.bpx.json", True),
        ("https://raw.githubusercontent.com/org/repo/refs/tags/20241015/x.bpx.json", True),
        ("https://raw.githubusercontent.com/org/repo/refs/heads/deadbeef/x.bpx.json", True),
        ("https://github.com/org/repo/blob/refs/tags/1234567/x.bpx.json", True),
        ("https://raw.githubusercontent.com/org/repo/51092701/x.bpx.json", False),
        ("https://raw.githubusercontent.com/org/repo/" + "0123456789abcdef" * 2 + "01234567/x.bpx.json", False),
        ("https://zenodo.org/records/123/files/x.bpx.json", False),
    ],
)
def test_a_url_that_names_a_branch_is_warned(url: str, warned: bool) -> None:
    result = from_bpx_parameters(FIXTURE)
    record = result.to_parameter_set(virtual_cell=True, distributions=[bpx_file_distribution(FIXTURE, content_url=url)])
    assert any("pin the URL to a commit" in w for w in result.warnings) is warned
    codes = {issue.code for issue in validate_record_report(record, policy="publisher").issues}
    assert ("semantic.parameter_file_content_url_unpinned" in codes) is warned


def test_a_runnable_copy_that_changes_nothing_is_warned() -> None:
    v1 = upgrade_bpx(_doc()).document  # already in the v1 layout, no bpx_parse check
    source_bytes = json.dumps(v1, indent=2).encode("utf-8")
    runnable_bytes = upgrade_bpx(source_bytes).to_json().encode("utf-8")
    source = bpx_file_distribution(source_bytes, name="source.bpx.json", content_url=SOURCE_URL)
    runnable = bpx_file_distribution(
        runnable_bytes,
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion="layout only",
    )
    result = from_bpx_parameters(source_bytes)
    result.to_parameter_set(virtual_cell=True, distributions=[source, runnable], runnable_file=runnable_bytes)
    assert any("it is not needed" in w for w in result.warnings)

    # A runnable copy of a v0.x-layout file is the conversion it should be.
    raw = FIXTURE.read_bytes()
    converted = upgrade_bpx(raw).to_json().encode("utf-8")
    source = bpx_file_distribution(raw, name="source.bpx.json", content_url=SOURCE_URL)
    runnable = bpx_file_distribution(
        converted,
        name="runnable.bpx.json",
        content_url=RUNNABLE_URL,
        role="runnable",
        derived_from=source["checksum"]["value"],
        conversion="layout only",
    )
    result = from_bpx_parameters(raw)
    result.to_parameter_set(virtual_cell=True, distributions=[source, runnable], runnable_file=converted)
    assert not any("it is not needed" in w for w in result.warnings)


def test_check_bpx_writes_no_doubled_period() -> None:
    pytest.importorskip("bpx")
    detail = check_bpx(_doc())["detail"]  # declares BPX 1.0 as a number: the parser warns
    assert detail.startswith("Parser warnings: ")
    assert ".." not in detail.replace("...", "")  # pydantic shortens values with "..."


def test_a_misspelt_keyword_is_named_with_a_suggestion() -> None:
    result = from_bpx_parameters(FIXTURE)
    with pytest.raises(TypeError) as caught:
        result.to_parameter_set(virtual_cell=True, licence="cc-by-4.0")
    message = str(caught.value)
    assert "licence= (did you mean license=?)" in message
    assert "cell_spec_id" in message and "citation" in message
    assert "_record_from_parameter_set" not in message
    assert result.to_parameter_set(virtual_cell=True, license="cc-by-4.0")["license"] == "cc-by-4.0"


def test_from_bpx_does_what_its_docstring_says() -> None:
    assert "cell_spec(" not in (from_bpx.__doc__ or "")
    assert "cell_spec(" not in (BpxImportResult.to_cell_spec_kwargs.__doc__ or "")
    result = from_bpx(FIXTURE)
    assert any("extras" in w for w in result.warnings)
    assert not any("extras" in w for w in from_bpx(FIXTURE, extra_warnings=False).warnings)
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="EX-1",
        format="pouch",
        chemistry="li-ion",
        **result.to_cell_spec_kwargs(),
    )
    assert spec.properties["nominal_capacity"] == {"value": 1.0, "unit": "Ah"}


def test_interop_help_renders_on_a_cp1252_console() -> None:
    text = pydoc.render_doc(battinfo.interop, renderer=pydoc.plaintext)
    text.encode("cp1252")  # raised UnicodeEncodeError on an arrow before
    for obj in (from_bpx, from_bpx_parameters, to_bpx, BpxImportResult, BpxImportResult.to_cell_spec_kwargs):
        assert (obj.__doc__ or "").isascii(), obj
