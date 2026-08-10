"""Regression tests for the three defects found authoring a real corpus for deposit.

Gap IDs are the ones in the Flores half-cell OCV readiness report:

* **G6** - a file digest was published under the sha256 term whatever algorithm
  the record actually stated, so Zenodo's md5 went out as a sha256. A digest is
  an assertion about a file and a deposit is permanent, so this was a wrong
  statement rather than a missing one.
* **G9** - ``ws.add("cell", names=..., serial_numbers=...)`` de-duplicated on the
  display label, so a batch sharing public labels silently collapsed to one cell
  per label.
* **G3** - ``record_to_jsonld`` dropped authored content: a material lot's whole
  ``processing`` block (aqueous vs NMP, the reason instances exist as a level)
  and most of the dataset discovery fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

MD5 = "7e779f63372291ad56b2e01de6639cc7"          # 32 hex chars, a real md5
SHA256 = "b" * 64


# ── G6: the emitted checksum states the algorithm the record carries ───────────

def _dataset_record(algorithm: str, value: str) -> dict:
    return {
        "dataset": {
            "id": "https://w3id.org/battinfo/dataset/d1",
            "name": "DS",
            "distributions": [{
                "name": "cell.parquet",
                "content_url": "https://zenodo.org/api/records/1/files/cell.parquet/content",
                "encoding_format": "application/vnd.apache.parquet",
                "checksum": {"algorithm": algorithm, "value": value},
            }],
        }
    }


def test_record_md5_checksum_is_typed_md5_not_sha256() -> None:
    out = record_to_jsonld(_dataset_record("md5", MD5), "dataset")
    checksum = out["dcat:distribution"][0]["spdx:checksum"]

    assert checksum["spdx:checksumAlgorithm"] == {"@id": "spdx:checksumAlgorithm_md5"}
    assert checksum["spdx:checksumValue"] == MD5
    # The whole document must not claim sha256 anywhere.
    assert "sha256" not in json.dumps(out)


def test_record_sha256_checksum_is_still_typed_sha256() -> None:
    out = record_to_jsonld(_dataset_record("sha256", SHA256), "dataset")
    checksum = out["dcat:distribution"][0]["spdx:checksum"]

    assert checksum["spdx:checksumAlgorithm"] == {"@id": "spdx:checksumAlgorithm_sha256"}
    assert checksum["spdx:checksumValue"] == SHA256


def test_algorithm_term_is_an_iri_reference_not_a_look_alike_string() -> None:
    """The SPDX individual must be a node reference, so it links rather than
    merely resembling the term."""
    out = record_to_jsonld(_dataset_record("md5", MD5), "dataset")
    algorithm = out["dcat:distribution"][0]["spdx:checksum"]["spdx:checksumAlgorithm"]
    assert isinstance(algorithm, dict) and "@id" in algorithm


def test_algorithm_outside_spdx_keeps_its_name_instead_of_inventing_a_term() -> None:
    out = record_to_jsonld(_dataset_record("other", "abc"), "dataset")
    checksum = out["dcat:distribution"][0]["spdx:checksum"]
    assert checksum["spdx:checksumAlgorithm"] == "other"
    assert checksum["spdx:checksumValue"] == "abc"


def _deposit_graph(algorithm: str, value: str) -> dict:
    record_sets = {
        "cell-spec": [{"cell_spec": {
            "id": "https://w3id.org/battinfo/spec/cs1", "name": "Half cell",
            "manufacturer": "M", "model": "HC", "format": "coin", "chemistry": "li-metal"}}],
        "cell-instance": [{"cell": {
            "id": "https://w3id.org/battinfo/cell/c1", "serial_number": "SN-001",
            "cell_spec_id": "https://w3id.org/battinfo/spec/cs1"}}],
        "test": [{"test": {
            "id": "https://w3id.org/battinfo/test/t1", "kind": "ocv",
            "cell_id": "https://w3id.org/battinfo/cell/c1",
            "dataset_ids": ["https://w3id.org/battinfo/dataset/d1"]}}],
        "dataset": [{"dataset": {
            "id": "https://w3id.org/battinfo/dataset/d1", "name": "DS",
            "about": ["https://w3id.org/battinfo/cell/c1"],
            "distributions": [{
                "name": "cell.parquet",
                "content_url": "https://zenodo.org/api/records/1/files/cell.parquet/content",
                "encoding_format": "application/vnd.apache.parquet",
                "role": "processed",
                "checksum": {"algorithm": algorithm, "value": value},
            }]}}],
    }
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=["cell.parquet"],
        title="T",
    )


def test_deposit_graph_never_publishes_an_md5_digest_as_a_sha256() -> None:
    doc = _deposit_graph("md5", MD5)
    blob = json.dumps(doc)

    # This is the exact defect: the digest went out under the sha256 term.
    assert "sha256" not in blob
    assert "spdx:checksumAlgorithm_md5" in blob

    for node in doc["@graph"]:
        for dist in node.get("dcat:distribution") or []:
            checksum = dist.get("spdx:checksum")
            if checksum:
                assert checksum["spdx:checksumAlgorithm"] == {"@id": "spdx:checksumAlgorithm_md5"}
                assert checksum["spdx:checksumValue"] == MD5
        for download in node.get("schema:distribution") or []:
            # schema:sha256 names one algorithm, so an md5 rides a PropertyValue.
            assert "schema:sha256" not in download
            assert download["schema:checksum"]["schema:propertyID"] == "md5"
            assert download["schema:checksum"]["schema:value"] == MD5


def test_deposit_graph_still_uses_the_schema_sha256_term_for_a_real_sha256() -> None:
    doc = _deposit_graph("sha256", SHA256)
    downloads = [d for node in doc["@graph"] for d in (node.get("schema:distribution") or [])]

    assert downloads
    for download in downloads:
        assert download["schema:sha256"] == SHA256
        assert "schema:checksum" not in download


def test_deposit_algorithm_round_trips_back_out_of_the_graph() -> None:
    from battinfo.ws import _spdx_algorithm_name

    doc = _deposit_graph("md5", MD5)
    checksum = next(
        dist["spdx:checksum"]
        for node in doc["@graph"]
        for dist in (node.get("dcat:distribution") or [])
        if dist.get("spdx:checksum")
    )
    assert _spdx_algorithm_name(checksum) == "md5"
    # Tolerates the bare-CURIE form an older document may carry.
    assert _spdx_algorithm_name({"spdx:checksumAlgorithm": "spdx:checksumAlgorithm_sha512"}) == "sha512"


def test_resolver_keeps_a_distribution_whose_checksum_is_not_sha256() -> None:
    """A non-sha256 checksum used to drop the WHOLE distribution - URL, format
    and size with it - from the resolved document."""
    from battinfo.api._resolver import _schema_distribution_value

    node = _schema_distribution_value(
        {"content_url": "https://x/f.parquet", "encoding_format": "application/vnd.apache.parquet",
         "checksum": {"algorithm": "md5", "value": MD5}},
        part_of_id="https://w3id.org/battinfo/dataset/d1",
    )
    assert node is not None
    assert node["schema:contentUrl"] == "https://x/f.parquet"
    assert "schema:sha256" not in node
    assert node["schema:checksum"]["schema:value"] == MD5


def test_resolver_keeps_a_distribution_with_no_checksum_at_all() -> None:
    from battinfo.api._resolver import _schema_distribution_value

    node = _schema_distribution_value(
        {"content_url": "https://x/f.parquet", "encoding_format": "text/csv"},
        part_of_id="https://w3id.org/battinfo/dataset/d1",
    )
    assert node is not None
    assert node["schema:contentUrl"] == "https://x/f.parquet"


# ── G9: a cell instance is identified by its serial, not its display label ─────

def _ws_with_spec(tmp_path: Path) -> tuple[AuthoringWorkspace, object]:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (tmp_path / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"coin","chemistry":"nmc"}', encoding="utf-8"
    )
    return ws, ws.load(tmp_path / "d.cell-spec.json")


def test_batch_sharing_display_labels_creates_one_cell_per_serial(tmp_path: Path) -> None:
    """The corpus shape: 95 physical cells behind 12 public labels."""
    ws, spec = _ws_with_spec(tmp_path)

    cells = ws.add(
        "cell", spec=spec,
        names=[f"L{i % 12}" for i in range(95)],
        serial_numbers=[f"SN-{i:03d}" for i in range(95)],
    )

    assert len(cells) == 95
    assert len({c.serial_number for c in cells}) == 95
    assert len({c.name for c in cells}) == 12


def test_two_cells_may_share_a_name_when_their_serials_differ(tmp_path: Path) -> None:
    ws, spec = _ws_with_spec(tmp_path)
    cells = ws.add("cell", spec=spec, names=["A", "A"], serial_numbers=["x1", "x2"])

    assert [c.serial_number for c in cells] == ["x1", "x2"]
    assert [c.name for c in cells] == ["A", "A"]


def test_re_adding_the_same_serial_and_name_is_a_no_op(tmp_path: Path) -> None:
    ws, spec = _ws_with_spec(tmp_path)
    first = ws.add("cell", spec=spec, names=["A", "A"], serial_numbers=["x1", "x2"])
    again = ws.add("cell", spec=spec, names=["A", "A"], serial_numbers=["x1", "x2"])

    assert len(first) == 2
    assert again == []


def test_a_repeated_serial_in_one_batch_fails_loudly(tmp_path: Path) -> None:
    ws, spec = _ws_with_spec(tmp_path)

    with pytest.raises(ValueError, match="repeated serial"):
        ws.add("cell", spec=spec, names=["A", "B"], serial_numbers=["x1", "x1"])


def test_serial_only_batches_are_unaffected(tmp_path: Path) -> None:
    ws, spec = _ws_with_spec(tmp_path)
    cells = ws.add("cell", spec=spec, serial_numbers=["s1", "s2", "s3"])
    assert len(cells) == 3


def test_a_shared_label_cannot_silently_resolve_to_one_of_its_cells(tmp_path: Path) -> None:
    """Now that a label may name several cells, using it as a reference must
    fail rather than attach a measurement to an arbitrary one."""
    ws, spec = _ws_with_spec(tmp_path)
    ws.add("cell", spec=spec, names=["A", "A"], serial_numbers=["x1", "x2"])

    with pytest.raises(ValueError, match="more than one cell"):
        ws._resolve_cell("A")

    # The serial is unambiguous and still resolves.
    assert ws._resolve_cell("x2").serial_number == "x2"


# ── G3: emission keeps the content the record was authored with ───────────────

NMP_IRI = "https://w3id.org/emmo/domain/chemical-substance#substance_59c65403_b7f9_4852_a37a_e6295c7b026c"


def _material_record(processing: dict) -> dict:
    return {
        "material": {
            "id": "https://w3id.org/battinfo/material/m1",
            "name": "NMC811 coating lot 7",
            "lot_id": "LOT-7",
            "material_spec_id": "https://w3id.org/battinfo/material-spec/s1",
            "processing": processing,
        },
        "notes": ["kept in the dry room"],
    }


def test_nmp_processing_route_emits_the_chemical_substance_iri() -> None:
    out = record_to_jsonld(
        _material_record({"route": "nmp", "detail": "cast at 40 um wet thickness"}), "material"
    )
    process = out["prov:wasGeneratedBy"]

    assert process["@type"] == "Manufacturing"
    assert process["dcterms:type"]["schema:termCode"] == "nmp"
    assert process["hasSolvent"]["@id"] == NMP_IRI
    assert process["schema:description"] == "cast at 40 um wet thickness"


def test_aqueous_and_nmp_lots_are_distinguishable_in_the_semantic_view() -> None:
    """The distinction the whole material-instance level exists to record."""
    aqueous = record_to_jsonld(_material_record({"route": "aqueous", "solvent": "water"}), "material")
    nmp = record_to_jsonld(_material_record({"route": "nmp", "solvent": "NMP"}), "material")

    assert aqueous["prov:wasGeneratedBy"]["dcterms:type"]["schema:termCode"] == "aqueous"
    assert nmp["prov:wasGeneratedBy"]["dcterms:type"]["schema:termCode"] == "nmp"
    # Water has no chemical-substance anchor in the bundled ontology, so it emits
    # as a labeled node - present and readable, rather than dropped.
    assert aqueous["prov:wasGeneratedBy"]["hasSolvent"]["schema:name"] == "water"


def test_material_lot_id_and_notes_survive_emission() -> None:
    out = record_to_jsonld(_material_record({"route": "dry"}), "material")

    assert out["schema:identifier"]["schema:value"] == "LOT-7"
    assert out["schema:comment"] == "kept in the dry room"


def test_a_material_without_processing_emits_no_process_node() -> None:
    record = _material_record({})
    record["material"].pop("processing")
    assert "prov:wasGeneratedBy" not in record_to_jsonld(record, "material")


def test_dataset_discovery_fields_survive_emission() -> None:
    record = {
        "dataset": {
            "id": "https://w3id.org/battinfo/dataset/d1",
            "name": "Cell A pseudo-OCV",
            "description": "Pseudo-OCV of a graphite half cell at C/20.",
            "keywords": ["ocv", "graphite"],
            "published_at": 1750000000,
            "measurement_techniques": ["pseudo-OCV"],
            "measurement_methods": ["GITT"],
            "variable_measured": [{"name": "voltage", "unit_text": "V", "description": "cell voltage"}],
            "citations": [{"name": "Flores et al.", "doi": "10.1000/xyz", "url": "https://doi.org/10.1000/xyz"}],
            "distributions": [{
                "name": "cellA.parquet",
                "content_url": "https://x/cellA.parquet",
                "encoding_format": "application/vnd.apache.parquet",
                "content_size": "10485760",
                "description": "processed BDF table",
            }],
        }
    }
    out = record_to_jsonld(record, "dataset")

    assert out["schema:description"].startswith("Pseudo-OCV")
    assert out["dcterms:description"].startswith("Pseudo-OCV")
    assert out["schema:keywords"] == ["ocv", "graphite"]
    assert out["dcat:keyword"] == ["ocv", "graphite"]
    assert out["schema:datePublished"].startswith("2025-")
    assert out["dcterms:issued"].startswith("2025-")
    assert out["schema:measurementTechnique"] == ["pseudo-OCV"]
    assert out["schema:measurementMethod"] == ["GITT"]
    assert out["schema:variableMeasured"][0]["schema:name"] == "voltage"
    assert out["schema:variableMeasured"][0]["schema:unitText"] == "V"
    assert out["schema:citation"][0]["bibo:doi"] == "10.1000/xyz"

    dist = out["dcat:distribution"][0]
    assert dist["schema:name"] == "cellA.parquet"
    assert dist["schema:description"] == "processed BDF table"
    assert dist["dcat:byteSize"] == 10485760
    assert dist["schema:contentSize"] == "10485760"


def test_dataset_emission_tolerates_a_non_numeric_content_size() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "distributions": [
            {"content_url": "https://x/f", "content_size": "10 MB"}]}},
        "dataset",
    )
    dist = out["dcat:distribution"][0]
    assert "dcat:byteSize" not in dist
    assert "schema:contentSize" not in dist
