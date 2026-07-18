from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    build_cell_spec_library_rdf,
    build_curated_cell_spec_submission,
    build_index,
    create_cell_instance,
    index_stats,
    promote_staging_cell_spec,
    publish_batch,
    publish_record,
    query,
    query_cell_instances,
    query_cell_specs,
    query_datasets,
    query_library_cell_specs,
    query_test_specs,
    query_tests,
    resolve_cell_spec_id,
    save_batch,
    save_cell_instance,
    save_cell_spec,
    save_dataset,
    save_library_cell_spec,
    save_record,
    save_test,
    save_test_spec,
    template_cell_instance,
    template_cell_spec,
    template_cell_spec_draft,
    template_dataset,
    template_library_cell_spec,
    template_test,
    template_test_spec,
    template_test_spec_draft,
    validate_staging_cell_spec,
)
from battinfo.bundle import Cell, CellSpec, Dataset, Test, TestSpec
from battinfo.validate import validate_references_report


def test_query_cell_specs_by_manufacturer_and_chemistry() -> None:
    rows = query_cell_specs(manufacturer="A123", chemistry="Li-ion", limit=20)
    assert rows
    assert all(r["manufacturer"] == "A123" for r in rows)
    assert all(r["chemistry"] == "Li-ion" for r in rows)


def test_query_cell_instances_and_datasets() -> None:
    instances = query_cell_instances(has_dataset=True, limit=10)
    datasets = query_datasets(related_cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", limit=10)
    tests = query_tests(cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", limit=10)
    assert instances
    assert datasets
    assert tests


def test_query_tests_by_new_kind() -> None:
    rows = query_tests(kind="hppc", limit=10)
    assert rows
    assert all(row["kind"] == "hppc" for row in rows)


def test_query_test_protocols_by_kind() -> None:
    rows = query_test_specs(kind="cycling", limit=10)
    assert rows
    assert all(row["kind"] == "cycling" for row in rows)


def test_query_dispatches_by_explicit_kind() -> None:
    dataset_rows = query(
        "datasets",
        related_cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
        limit=10,
    )
    assert dataset_rows

    test_rows = query(
        "tests",
        cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
        limit=10,
    )
    assert test_rows

    cell_rows = query("cells", has_dataset=True, limit=10)
    assert cell_rows

    protocol_rows = query("test_specs", kind="cycling", limit=10)
    assert protocol_rows


def test_query_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        query("unknown-kind")


def test_template_test_accepts_new_kinds() -> None:
    for kind in ("hppc", "ici", "gitt", "dcir", "eis", "formation", "rate_capability"):
        record = template_test(kind=kind)
        assert record["test"]["kind"] == kind


def test_template_test_protocol_accepts_new_kinds() -> None:
    for kind in ("hppc", "ici", "gitt", "dcir", "eis", "formation", "rate_capability"):
        record = template_test_spec(kind=kind)
        assert record["test_spec"]["kind"] == kind


def test_shipped_example_chain_is_consistent() -> None:
    # The canonical A123 cell-spec anchors the linked chain. The research/ detailed
    # and extended/minimal descriptors are separate example records (own IRIs).
    cell_spec = json.loads(
        (ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8")
    )
    cell_instance = json.loads(
        (ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json").read_text(
            encoding="utf-8"
        )
    )
    test_record = json.loads(
        (ROOT / "examples" / "test" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
    )
    dataset = json.loads(
        (ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json").read_text(
            encoding="utf-8"
        )
    )

    assert cell_spec["cell_spec"]["id"] == cell_instance["cell_instance"]["cell_spec_id"]
    assert cell_instance["cell_instance"]["id"] == test_record["test"]["cell_id"]
    assert test_record["test"]["id"] in dataset["dataset"]["about"]
    assert cell_instance["cell_instance"]["id"] in dataset["dataset"]["about"]
    assert test_record["test"]["dataset_ids"] == [dataset["dataset"]["id"]]


def test_resolve_cell_spec_id_from_metadata() -> None:
    resolved = resolve_cell_spec_id(model_name="ANR26650M1-B", manufacturer="A123")
    assert resolved.startswith("https://w3id.org/battinfo/spec/")


def test_template_cell_spec_and_create_cell_instance(tmp_path: Path) -> None:
    cell_spec = template_cell_spec(
        manufacturer="A123",
        model_name="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        iec_code="IFpR26650",
        country_of_origin="United States",
        year=2012,
        uid="7d9k2m4p8t3x6nq5",
        source_file="A123__ANR26650M1-B.pdf",
    )
    assert cell_spec["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"
    assert cell_spec["cell_spec"]["model"] == "ANR26650M1-B"
    assert cell_spec["cell_spec"]["iec_code"] == "IFpR26650"
    assert cell_spec["cell_spec"]["country_of_origin"] == "United States"
    assert cell_spec["cell_spec"]["year"] == 2012

    out_path = tmp_path / "cell-instance.json"
    inst = create_cell_instance(
        cell_spec_id=cell_spec["cell_spec"]["id"],
        uid="3m6k9t2p7x4h9nq8",
        serial_number="LAB-001",
        dataset_id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        out_path=out_path,
    )
    assert inst["cell_instance"]["id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert "dataset_id" not in inst["provenance"]
    assert inst["datasets"] == [{"id": "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x", "role": "raw"}]
    assert out_path.exists()


def test_query_cell_specs_exposes_iec_code(tmp_path: Path) -> None:
    record = template_cell_spec(
        manufacturer="A123",
        model_name="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        iec_code="IFpR26650",
        country_of_origin="United States",
        year=2012,
        uid="7d9k2m4p8t3x6nq5",
        source_file="A123__ANR26650M1-B.pdf",
    )
    save_cell_spec(record, source_root=tmp_path)

    rows = query_cell_specs(source_root=tmp_path)

    assert len(rows) == 1
    assert rows[0]["iec_code"] == "IFpR26650"
    assert rows[0]["country_of_origin"] == "United States"
    assert rows[0]["year"] == 2012


def test_template_cell_spec_draft_omits_canonical_fields() -> None:
    draft = template_cell_spec_draft(
        manufacturer="A123",
        model_name="ANR26650M1-B",
        chemistry="Li-ion",
        format="cylindrical",
        size_code="R26650",
        iec_code="IFpR26650",
        country_of_origin="United States",
        year=2012,
    )

    assert draft["manufacturer"] == "A123"
    assert draft["model"] == "ANR26650M1-B"
    assert draft["size_code"] == "R26650"
    assert draft["iec_code"] == "IFpR26650"
    assert draft["country_of_origin"] == "United States"
    assert draft["year"] == 2012
    assert "cell_spec" not in draft
    assert "provenance" not in draft


def test_template_test_protocol_draft_omits_canonical_fields() -> None:
    draft = template_test_spec_draft(
        name="1C Cycle Life at 25 C",
        kind="cycling",
        version="1.0",
        protocol_url="https://example.org/protocols/cycle-life-1c",
    )

    assert draft["name"] == "1C Cycle Life at 25 C"
    assert draft["kind"] == "cycling"
    assert draft["version"] == "1.0"
    assert "test_spec" not in draft
    assert "provenance" not in draft


def test_validate_staging_cell_spec_accepts_single_file_authoring_draft(tmp_path: Path) -> None:
    draft_path = tmp_path / "GOOGLE__G20M7.json"
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Google",
                "model": "G20M7",
                "year": 2025,
                "format": "prismatic",
                "chemistry": "Li-ion",
                "size_code": "P6/65/75",
                "iec_code": "ICP6/65/75",
                "positive_electrode_basis": "LCO",
                "negative_electrode_basis": "Graphite",
                "country_of_origin": "Vietnam",
                "properties": {
                    "nominal_voltage": {"value": 3.9, "unit": "V"},
                    "nominal_energy": {"value": 19.39, "unit": "Wh"},
                },
                "provenance": {"source_type": "label"},
                "comment": "Taken from the printed product label.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = validate_staging_cell_spec(draft_path, validation_policy="strict")

    assert payload["ok"] is True
    assert payload["record_id"] == "google--g20m7--2025"
    assert payload["record_id_basis"] == "year"
    assert payload["requires_record_id"] is False
    assert payload["record"]["cell_spec"]["model"] == "G20M7"
    assert payload["record"]["cell_spec"]["manufacturer"]["name"] == "Google"
    assert payload["record"]["provenance"]["source_type"] == "label"
    assert payload["record"]["provenance"]["source_file"] == "GOOGLE__G20M7.json"
    assert payload["record"]["notes"] == ["Taken from the printed product label."]


def test_promote_staging_cell_spec_writes_curated_record_json(tmp_path: Path) -> None:
    draft_path = tmp_path / "staging" / "SUNWODA__BM68.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Sunwoda",
                "model": "BM68",
                "year": 2024,
                "format": "prismatic",
                "chemistry": "Li-ion",
                "positive_electrode_basis": "NMC",
                "negative_electrode_basis": "Graphite",
                "properties": {"nominal_capacity": {"value": 5.0, "unit": "Ah"}},
                "provenance": {"source_type": "label"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = promote_staging_cell_spec(
        draft_path,
        curated_root=tmp_path / "records" / "cell-spec",
        validation_policy="strict",
    )

    target_path = Path(payload["target_path"])
    assert payload["record_id"] == "sunwoda--bm68--2024"
    assert payload["record_id_basis"] == "year"
    assert target_path == tmp_path / "records" / "cell-spec" / "sunwoda--bm68--2024" / "record.json"
    assert target_path.exists()

    record = json.loads(target_path.read_text(encoding="utf-8"))
    assert record["cell_spec"]["name"] == "Sunwoda BM68"
    assert record["cell_spec"]["identifier"].startswith("cell-spec:")
    assert record["provenance"]["source_type"] == "label"
    assert record["provenance"]["source_file"] == "SUNWODA__BM68.json"


def test_promote_staging_cell_spec_reuses_existing_curated_identifier(tmp_path: Path) -> None:
    draft_path = tmp_path / "staging" / "GOOGLE__G20M7.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Google",
                "model": "G20M7",
                "year": 2025,
                "format": "prismatic",
                "chemistry": "Li-ion",
                "positive_electrode_basis": "LCO",
                "negative_electrode_basis": "Graphite",
                "properties": {"nominal_voltage": {"value": 3.9, "unit": "V"}},
                "provenance": {"source_type": "label"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    curated_root = tmp_path / "records" / "cell-spec"
    target_path = curated_root / "google--g20m7--2025" / "record.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cell_spec": {
                    "id": "https://w3id.org/battinfo/spec/1234-5678-9abc-def0",
                    "short_id": "123456",
                    "identifier": "cell-spec:1234-5678-9abc-def0",
                    "name": "Google G20M7",
                    "model": "G20M7",
                    "manufacturer": {"type": "Organization", "name": "Google"},
                    "cell_format": "prismatic",
                    "chemistry": "Li-ion",
                    "positive_electrode_basis": "LCO",
                    "negative_electrode_basis": "Graphite",
                    "year": 2025,
                },
                "properties": {"nominal_voltage": {"value": 3.9, "unit": "V"}},
                "provenance": {
                    "source_type": "label",
                    "source_file": "GOOGLE__G20M7.json",
                    "retrieved_at": 1771804800,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    dry_run_payload = promote_staging_cell_spec(
        draft_path,
        curated_root=curated_root,
        validation_policy="strict",
        dry_run=True,
    )
    assert dry_run_payload["record"]["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/1234-5678-9abc-def0"
    assert dry_run_payload["record"]["cell_spec"]["short_id"] == "123456"

    payload = promote_staging_cell_spec(
        draft_path,
        curated_root=curated_root,
        validation_policy="strict",
    )
    assert payload["record"]["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/1234-5678-9abc-def0"

    record = json.loads(target_path.read_text(encoding="utf-8"))
    assert record["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/1234-5678-9abc-def0"
    assert record["cell_spec"]["short_id"] == "123456"


def test_validate_staging_cell_spec_uses_revision_when_year_missing(tmp_path: Path) -> None:
    draft_path = tmp_path / "GOOGLE__G20M7.json"
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Google",
                "model": "G20M7",
                "format": "prismatic",
                "chemistry": "Li-ion",
                "datasheet_revision": "SD12",
                "positive_electrode_basis": "LCO",
                "negative_electrode_basis": "Graphite",
                "properties": {"nominal_voltage": {"value": 3.9, "unit": "V"}},
                "provenance": {"source_type": "label"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = validate_staging_cell_spec(draft_path, validation_policy="strict")

    assert payload["record_id"] == "google--g20m7--sd12"
    assert payload["record_id_basis"] == "revision"
    assert payload["requires_record_id"] is False


def test_validate_staging_cell_spec_uses_evidence_date_when_year_and_revision_missing(tmp_path: Path) -> None:
    draft_path = tmp_path / "GOOGLE__G20M7.json"
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Google",
                "model": "G20M7",
                "format": "prismatic",
                "chemistry": "Li-ion",
                "positive_electrode_basis": "LCO",
                "negative_electrode_basis": "Graphite",
                "properties": {"nominal_voltage": {"value": 3.9, "unit": "V"}},
                "provenance": {"source_type": "label", "retrieved_at": "2026-03-20T10:00:00Z"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = validate_staging_cell_spec(draft_path, validation_policy="strict")

    assert payload["record_id"] == "google--g20m7--20260320"
    assert payload["record_id_basis"] == "evidence_date"
    assert payload["requires_record_id"] is False


def test_promote_staging_cell_spec_requires_explicit_record_id_when_ambiguous(tmp_path: Path) -> None:
    draft_path = tmp_path / "ENERGIZER__CR2032.json"
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "Energizer",
                "model": "CR2032",
                "format": "coin",
                "chemistry": "Li-primary",
                "positive_electrode_basis": "MnO2",
                "negative_electrode_basis": "Li-metal",
                "properties": {"nominal_voltage": {"value": 3.0, "unit": "V"}},
                "provenance": {"source_type": "label"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = validate_staging_cell_spec(draft_path, validation_policy="strict")
    assert payload["record_id"] is None
    assert payload["requires_record_id"] is True
    assert payload["record_id_hint"] == "energizer--cr2032--<year-or-revision>"

    with pytest.raises(ValueError, match="Provide --record-id explicitly"):
        promote_staging_cell_spec(
            draft_path,
            curated_root=tmp_path / "records" / "cell-spec",
            validation_policy="strict",
        )


def test_save_cell_spec_accepts_label_source_type(tmp_path: Path) -> None:
    payload = save_cell_spec(
        {
            "manufacturer": "Google",
            "model_name": "G20M7",
            "format": "prismatic",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LCO",
            "negative_electrode_basis": "Graphite",
            "source_type": "label",
            "source_file": "GOOGLE__G20M7.json",
            "notes": ["Taken from the printed product label."],
        },
        source_root=tmp_path,
        mode="upsert",
        validation_policy="strict",
    )

    record = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert record["provenance"]["source_type"] == "label"
    assert record["notes"] == ["Taken from the printed product label."]


def test_build_curated_cell_spec_submission_infers_source_local_id_from_record_directory(tmp_path: Path) -> None:
    record_dir = tmp_path / "records" / "cell-spec" / "google--g20m7--2025"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / "record.json"
    record_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cell_spec": {
                    "id": "https://w3id.org/battinfo/spec/1234-5678-9abc-def0",
                    "short_id": "123456",
                    "identifier": "cell-spec:1234-5678-9abc-def0",
                    "name": "Google G20M7",
                    "model": "G20M7",
                    "manufacturer": {"type": "Organization", "name": "Google"},
                    "cell_format": "prismatic",
                    "chemistry": "Li-ion",
                    "positive_electrode_basis": "LCO",
                    "negative_electrode_basis": "Graphite",
                    "size_code": "P6/65/75",
                    "iec_code": "ICP6/65/75",
                    "country_of_origin": "Vietnam",
                    "year": 2025,
                },
                "properties": {
                    "nominal_voltage": {"value": 3.9, "unit": "V"},
                    "nominal_energy": {"value": 19.39, "unit": "Wh"},
                },
                "provenance": {
                    "source_type": "label",
                    "source_file": "google--g20m7--2025.json",
                    "retrieved_at": 1771804800,
                },
                "notes": ["Curated cell type record."],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_curated_cell_spec_submission(
        record_path,
        workspace_id="battinfo-records-cell-spec",
        publisher_id="demo-editorial",
        source_version="demo-2026-03-20",
        validation_policy="strict",
    )

    assert payload["submission_mode"] == "resource"
    assert payload["workspace_id"] == "battinfo-records-cell-spec"
    assert payload["publisher_id"] == "demo-editorial"
    assert payload["source_version"] == "demo-2026-03-20"
    assert payload["resource"]["resource_type"] == "cell_spec"
    assert payload["resource"]["source_local_id"] == "google--g20m7--2025"
    assert "metadata" not in payload["resource"]["semantic_payload"]
    assert payload["resource"]["semantic_payload"]["battinfo_records"]["cell_spec"]["cell_spec"]["model"] == "G20M7"
    assert payload["workspace"]["editorial"]["record_id"] == "google--g20m7--2025"


def test_promote_staging_cell_spec_preserves_double_hyphen_record_id(tmp_path: Path) -> None:
    draft_path = tmp_path / "staging" / "LG__JP3.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "LG",
                "model": "JP3",
                "format": "pouch",
                "chemistry": "Li-ion",
                "positive_electrode_basis": "NMC",
                "negative_electrode_basis": "graphite",
                "properties": {"nominal_voltage": {"value": 3.68, "unit": "V"}},
                "provenance": {"source_type": "datasheet", "source_file": "LG__JP3.pdf"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = promote_staging_cell_spec(
        draft_path,
        curated_root=tmp_path / "records" / "cell-spec",
        record_id="lg--jp3",
        validation_policy="strict",
    )

    assert payload["record_id"] == "lg--jp3"
    assert Path(payload["target_path"]) == tmp_path / "records" / "cell-spec" / "lg--jp3" / "record.json"


def test_save_test_protocol_and_test_with_protocol_reference(tmp_path: Path) -> None:
    cell_spec = save_cell_spec(
        CellSpec(
            uid="7d9k2m4p8t3x6nq5",
            manufacturer="A123",
            model_name="ANR26650M1-B",
            chemistry="Li-ion",
            format="cylindrical",
            source_file="A123__ANR26650M1-B.pdf",
        ),
        source_root=tmp_path,
        mode="upsert",
    )
    cell = save_cell_instance(
        Cell(
            uid="3m6k9t2p7x4h9nq8",
            cell_spec_id=cell_spec["id"],
        ),
        source_root=tmp_path,
        mode="upsert",
    )
    protocol = save_test_spec(
        TestSpec(
            uid="8r2m4v6k9p3t7n5x",
            name="1C Cycle Life at 25 C",
            kind="cycling",
            version="1.0",
            protocol_url="https://example.org/protocols/cycle-life-1c",
        ),
        source_root=tmp_path,
        mode="upsert",
    )
    test = save_test(
        Test(
            uid="5p7v2n8k4m3t6q9r",
            cell_id=cell["id"],
            name="A123 cycle life run",
            kind="cycling",
            protocol_id=protocol["id"],
        ),
        source_root=tmp_path,
        mode="upsert",
    )

    assert protocol["entity_type"] == "test-protocol"
    assert test["entity_type"] == "test"

    protocol_rows = query_test_specs(source_root=tmp_path)
    assert len(protocol_rows) == 1
    assert protocol_rows[0]["id"] == protocol["id"]

    test_rows = query_tests(source_root=tmp_path)
    assert len(test_rows) == 1
    assert test_rows[0]["protocol_id"] == protocol["id"]


def test_publish_record_writes_artifacts(tmp_path: Path) -> None:
    src = ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json"
    result = publish_record(src, target_root=tmp_path)

    out_dir = tmp_path / "cell" / "3m6k-9t2p-7x4h-9nq8"
    assert result["status"] == "published"
    assert out_dir.exists()
    assert (out_dir / "index.json").exists()
    assert (out_dir / "index.jsonld").exists()
    assert (out_dir / "index.html").exists()


def test_publish_record_dataset_jsonld_preserves_rich_metadata(tmp_path: Path) -> None:
    record = {
        "schema_version": "0.1.0",
        "dataset": {
            "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
            "identifier": {"property_id": "doi", "value": "10.1000/rich-dataset"},
            "name": "Rich dataset",
            "description": "Dataset published through the canonical resolver.",
            "access_url": "https://example.org/datasets/rich",
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "same_as": ["https://example.org/datasets/rich/canonical"],
            "keywords": ["battery", "rdf"],
            "creators": [
                {
                    "type": "Person",
                    "name": "Ada Lovelace",
                    "given_name": "Ada",
                    "family_name": "Lovelace",
                    "same_as": "https://orcid.org/0000-0000-0000-0001",
                    "affiliation": {"type": "Organization", "name": "Example Lab"},
                }
            ],
            "publisher": {"type": "Organization", "name": "BattINFO", "same_as": "https://ror.org/03yrm5c26"},
            "funders": [{"type": "Organization", "name": "Battery Data Alliance", "same_as": "https://ror.org/02mhbdp94"}],
            "citations": [{"name": "Example paper", "url": "https://doi.org/10.1000/example-paper", "doi": "10.1000/example-paper"}],
            "measurement_techniques": ["electrochemical cycling"],
            "variable_measured": [{"name": "Voltage", "unit_text": "V"}],
            "included_in_data_catalog": {
                "type": "DataCatalog",
                "id": "https://example.org/catalog",
                "name": "Example Catalog",
                "url": "https://example.org/catalog",
            },
            "main_entity": {
                "type": "Table",
                "id": "https://example.org/datasets/rich#table",
                "url": "https://example.org/datasets/rich/data.csv",
                "table_schema": {
                    "id": "https://example.org/datasets/rich/table-schema",
                    "columns": [
                        {
                            "name": "voltage",
                            "titles": ["Voltage / V"],
                            "same_as": "https://qudt.org/vocab/quantitykind/Voltage",
                            "unit_text": "V",
                        }
                    ],
                },
            },
            "distributions": [
                {
                    "type": "DataDownload",
                    "content_url": "https://example.org/datasets/rich/data.csv",
                    "encoding_format": "text/csv",
                    "checksum": {"algorithm": "sha256", "value": "c" * 64},
                }
            ],
        },
        "provenance": {"source_type": "catalog", "retrieved_at": 1771804800},
    }

    result = publish_record(record, target_root=tmp_path)

    out_dir = tmp_path / "dataset" / "87fr-c4vr-wfyh-21td"
    assert result["status"] == "published"
    payload = json.loads((out_dir / "index.jsonld").read_text(encoding="utf-8"))
    assert payload["@type"] == "schema:Dataset"
    assert payload["schema:identifier"]["schema:value"] == "10.1000/rich-dataset"
    assert payload["schema:creator"][0]["schema:name"] == "Ada Lovelace"
    assert payload["schema:creator"][0]["schema:sameAs"] == "https://orcid.org/0000-0000-0000-0001"
    assert payload["schema:publisher"]["schema:name"] == "BattINFO"
    assert payload["schema:publisher"]["schema:sameAs"] == "https://ror.org/03yrm5c26"
    assert payload["schema:funder"][0]["schema:name"] == "Battery Data Alliance"
    assert payload["schema:variableMeasured"][0]["schema:name"] == "Voltage"
    assert payload["schema:includedInDataCatalog"]["@type"] == "schema:DataCatalog"
    assert payload["schema:includedInDataCatalog"]["schema:name"] == "Example Catalog"
    assert payload["schema:mainEntity"]["@type"] == "csvw:Table"
    assert payload["schema:mainEntity"]["csvw:tableSchema"]["@type"] == "csvw:Schema"
    assert payload["schema:mainEntity"]["csvw:tableSchema"]["@id"] == "https://example.org/datasets/rich/table-schema"
    assert payload["schema:mainEntity"]["csvw:tableSchema"]["csvw:column"][0]["csvw:name"] == "voltage"
    assert payload["schema:distribution"][0]["schema:contentUrl"] == "https://example.org/datasets/rich/data.csv"


def test_publish_batch_summary(tmp_path: Path) -> None:
    summary = publish_batch(
        source_dirs=[
            ROOT / "examples" / "cell-spec",
            ROOT / "examples" / "cell-instance",
            ROOT / "examples" / "test",
            ROOT / "examples" / "dataset",
        ],
        target_root=tmp_path,
    )
    assert summary["processed"] >= 4
    assert summary["processed"] == summary["published"] + summary["failed"]
    assert summary["status"] in {"ok", "partial"}


def test_build_index_and_stats(tmp_path: Path) -> None:
    out = tmp_path / "index.json"
    index = build_index(source_root=ROOT / "examples", out_path=out)
    assert out.exists()
    assert index["cell_spec_count"] >= 1
    assert index["cell_instance_count"] >= 1
    assert index["test_count"] >= 1
    assert index["dataset_count"] >= 1

    stats = index_stats(out)
    assert stats["cell_spec_count"] == index["cell_spec_count"]
    assert stats["cell_instance_count"] == index["cell_instance_count"]
    assert stats["test_count"] == index["test_count"]
    assert stats["dataset_count"] == index["dataset_count"]
    assert isinstance(stats["build_timestamp"], str)


def test_build_index_validate_catches_reference_errors(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    cell_instances_dir = source_root / "cell-instance"
    cell_instances_dir.mkdir(parents=True)
    bad_cell_instance = {
        "schema_version": "0.1.0",
        "cell_instance": {
            "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
            "cell_spec_id": "https://w3id.org/battinfo/spec/eysh-4h5s-k4bx-zkgg",
            "short_id": "1f8r6v",
        },
        "provenance": {
            "source_type": "measurement",
            "retrieved_at": 1771804800,
        },
    }
    (cell_instances_dir / "cell-1f8r-6v2k-9p4m-3t7x.json").write_text(
        json.dumps(bad_cell_instance, indent=2),
        encoding="utf-8",
    )

    index = build_index(source_root=source_root, validate=True)
    assert index["failed"] == 1
    assert "Referenced cell_spec not found" in index["failures"][0]["error"]


def test_save_resource_drafts_and_duplicate_policy(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"

    cell_spec_payload = save_cell_spec(
        CellSpec(
            uid="3m6k9t2p7x4h9nq8",
            model_name="MN1500",
            manufacturer="Duracell",
            chemistry="Zn-air",
            format="cylindrical",
            source_file="manual-mn1500.json",
        ),
        source_root=source_root,
    )
    assert cell_spec_payload["status"] == "created"
    assert cell_spec_payload["id"].startswith("https://w3id.org/battinfo/spec/")

    exists_payload = save_cell_spec(
        CellSpec(
            uid="3m6k9t2p7x4h9nq8",
            model_name="MN1500",
            manufacturer="Duracell",
            chemistry="Zn-air",
            format="cylindrical",
            source_file="manual-mn1500.json",
        ),
        source_root=source_root,
        duplicate_policy="return_existing",
    )
    assert exists_payload["status"] == "exists"

    cell_instance_payload = save_cell_instance(
        Cell(
            uid="1f8r6v2k9p4m3t7x",
            cell_spec_id=cell_spec_payload["id"],
            serial_number="LAB-001",
            source_type="lab",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert cell_instance_payload["status"] == "created"

    test_payload = save_test(
        Test(
            uid="5p7v2n8k4m3t6q9r",
            cell_id=cell_instance_payload["id"],
            name="Duracell MN1500 baseline cycling",
            kind="cycling",
            source_type="measurement",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert test_payload["status"] == "created"

    dataset_payload = save_dataset(
        Dataset(
            uid="8c1h8pk68034vav6",
            title="Duracell MN1500 cycling",
            source_type="measurement",
            access_url="https://data.example.com/mn1500",
            related_cell_ids=[cell_instance_payload["id"]],
            related_test_ids=[test_payload["id"]],
            format="application/x-hdf5",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert dataset_payload["status"] == "created"
    assert dataset_payload["id"].startswith("https://w3id.org/battinfo/dataset/")


def test_save_record_accepts_canonical_records_and_paths(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"

    cell_spec_record = template_cell_spec(
        manufacturer="Duracell",
        model_name="MN1500",
        chemistry="Zn-air",
        format="cylindrical",
        uid="3m6k9t2p7x4h9nq8",
        source_file="manual-mn1500.json",
    )
    cell_spec_payload = save_record(cell_spec_record, source_root=source_root, resolve_references=False)
    assert cell_spec_payload["status"] == "created"

    cell_instance_record = template_cell_instance(
        cell_spec_id=cell_spec_payload["id"],
        uid="1f8r6v2k9p4m3t7x",
        source_type="measurement",
    )
    cell_instance_payload = save_record(cell_instance_record, source_root=source_root, resolve_references=True)
    assert cell_instance_payload["status"] == "created"

    dataset_record = template_dataset(
        title="Duracell MN1500 cycling",
        source_type="measurement",
        uid="8c1h8pk68034vav6",
        related_cell_ids=[cell_instance_payload["id"]],
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset_record, indent=2), encoding="utf-8")

    dataset_payload = save_record(dataset_path, source_root=source_root, resolve_references=True)
    assert dataset_payload["status"] == "created"
    assert dataset_payload["path"].endswith("dataset-8c1h-8pk6-8034-vav6.json")


def test_save_cell_instance_dangling_reference_fails_by_default(tmp_path: Path) -> None:
    """P1 fix 2: a dangling *_spec_id reference is an error at save time (default ON),
    with the missing IRIs named; resolve_references=False remains the staged-workflow
    opt-out, and set-level validation still catches the gap afterwards."""
    source_root = tmp_path / "examples"
    draft = Cell(
        uid="eysh4h5sk4bxzkgg",
        cell_spec_id="https://w3id.org/battinfo/spec/pvn1-43h7-rm3e-mjqq",
        dataset_id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        source_type="measurement",
    )
    with pytest.raises(ValueError) as excinfo:
        save_cell_instance(draft, source_root=source_root, resolve_references=True)
    message = str(excinfo.value)
    assert "Reference validation failed" in message
    assert "https://w3id.org/battinfo/spec/pvn1-43h7-rm3e-mjqq" in message
    assert "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x" in message

    # Staged workflows can opt out explicitly; the set validator still reports the gap.
    payload = save_cell_instance(draft, source_root=source_root, resolve_references=False)
    assert payload["status"] == "created"
    index = build_index(source_root=source_root, validate=True)
    assert index["failed"] == 1
    assert "cell_instance.cell_spec_id" in index["failures"][0]["error"]


def test_save_record_dry_run(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    dry_run_payload = save_record(
        {
            "schema_version": "0.1.0",
            "dataset": {
                "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
                "identifier": "dataset:87fr-c4vr-wfyh-21td",
                "name": "Dry-run dataset",
                "url": "https://example.org/dataset/87fr-c4vr-wfyh-21td",
            },
            "provenance": {
                "source_type": "other",
                "retrieved_at": 1771804800,
            },
        },
        source_root=source_root,
        resolve_references=False,
        dry_run=True,
    )
    assert dry_run_payload["status"] == "dry-run"
    assert not (source_root / "dataset" / "dataset-87fr-c4vr-wfyh-21td.json").exists()


def test_save_record_rejects_invalid_dataset_url_format(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    with pytest.raises(ValueError, match="Schema validation failed"):
        save_record(
            {
                "schema_version": "0.1.0",
                "dataset": {
                    "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
                    "identifier": "dataset:87fr-c4vr-wfyh-21td",
                    "name": "Bad dataset URL",
                    "url": "not-a-uri",
                },
                "provenance": {
                    "source_type": "other",
                    "retrieved_at": 1771804800,
                },
            },
            source_root=source_root,
            resolve_references=False,
            dry_run=True,
        )


def test_save_record_strict_policy_rejects_semantic_issue(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    with pytest.raises(ValueError, match="short_id"):
        save_record(
            {
                "schema_version": "0.1.0",
                "test": {
                    "id": "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
                    "short_id": "xxxxxx",
                    "identifier": "test:5p7v-2n8k-4m3t-6q9r",
                    "cell_id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
                    "name": "Semantic failure",
                    "kind": "cycling",
                },
                "provenance": {
                    "source_type": "measurement",
                    "retrieved_at": 1771804800,
                },
            },
            source_root=source_root,
            resolve_references=False,
            validation_policy="strict",
            dry_run=True,
        )


def test_save_cell_instance_rejects_reference_with_wrong_record_type(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    dataset_payload = save_dataset(
        Dataset(
            uid="8c1h8pk68034vav6",
            title="Dataset only",
            source_type="measurement",
            access_url="https://data.example.com/dataset-only",
            format="application/x-hdf5",
        ),
        source_root=source_root,
        resolve_references=False,
    )
    report = validate_references_report(
        {
            "schema_version": "0.1.0",
            "cell_instance": {
                "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
                "identifier": "cell:1f8r-6v2k-9p4m-3t7x",
                "cell_spec_id": dataset_payload["id"],
            },
            "provenance": {
                "source_type": "measurement",
            },
        },
        source_root,
    )
    assert not report.ok
    assert report.errors[0].code == "reference.type_mismatch"
    assert "cell_spec" in report.errors[0].message


def test_save_batch_summary_and_partial(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    batch_root = tmp_path / "batch"
    cell_specs_dir = batch_root / "cell-spec"
    cell_instances_dir = batch_root / "cell-instance"
    tests_dir = batch_root / "test"
    datasets_dir = batch_root / "dataset"
    cell_specs_dir.mkdir(parents=True)
    cell_instances_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    datasets_dir.mkdir(parents=True)

    cell_spec_record = template_cell_spec(
        manufacturer="Duracell",
        model_name="MN1500",
        chemistry="Zn-air",
        format="cylindrical",
        uid="3m6k9t2p7x4h9nq8",
    )
    cell_spec_path = cell_specs_dir / "cell-spec.json"
    cell_spec_path.write_text(json.dumps(cell_spec_record, indent=2), encoding="utf-8")

    cell_instance_record = template_cell_instance(
        cell_spec_id=cell_spec_record["cell_spec"]["id"],
        source_type="lab",
        uid="1f8r6v2k9p4m3t7x",
    )
    cell_instance_path = cell_instances_dir / "cell-instance.json"
    cell_instance_path.write_text(json.dumps(cell_instance_record, indent=2), encoding="utf-8")

    test_record = template_test(
        cell_id=cell_instance_record["cell_instance"]["id"],
        name="MN1500 baseline cycling",
        kind="cycling",
        source_type="measurement",
        uid="5p7v2n8k4m3t6q9r",
    )
    test_path = tests_dir / "test.json"
    test_path.write_text(json.dumps(test_record, indent=2), encoding="utf-8")

    dataset_record = template_dataset(
        title="MN1500 dataset",
        source_type="measurement",
        uid="8c1h8pk68034vav6",
        related_cell_ids=[cell_instance_record["cell_instance"]["id"]],
        related_test_ids=[test_record["test"]["id"]],
    )
    dataset_path = datasets_dir / "dataset.json"
    dataset_path.write_text(json.dumps(dataset_record, indent=2), encoding="utf-8")

    summary = save_batch(
        source_dirs=[cell_specs_dir, cell_instances_dir, tests_dir, datasets_dir],
        source_root=source_root,
        resolve_references=True,
    )
    assert summary["status"] == "ok"
    assert summary["processed"] == 4
    assert summary["created"] == 4
    assert summary["failed"] == 0

    idempotent = save_batch(
        source_dirs=[cell_specs_dir, cell_instances_dir, tests_dir, datasets_dir],
        source_root=source_root,
        duplicate_policy="return_existing",
        resolve_references=True,
    )
    assert idempotent["status"] == "ok"
    assert idempotent["exists"] == 4
    assert idempotent["failed"] == 0

    bad_path = cell_specs_dir / "bad.json"
    bad_path.write_text('{"not_a_resource": true}', encoding="utf-8")
    partial = save_batch(
        source_dirs=[cell_specs_dir],
        source_root=source_root,
        duplicate_policy="return_existing",
        resolve_references=False,
    )
    assert partial["status"] == "partial"
    assert partial["failed"] == 1
    assert partial["failures"][0]["file"].endswith("bad.json")


def test_save_batch_handles_circular_linked_examples_as_a_set(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    batch_root = tmp_path / "batch"
    cell_specs_dir = batch_root / "cell-spec"
    cell_instances_dir = batch_root / "cell-instance"
    tests_dir = batch_root / "test"
    datasets_dir = batch_root / "dataset"
    cell_specs_dir.mkdir(parents=True)
    cell_instances_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    datasets_dir.mkdir(parents=True)

    (cell_specs_dir / "A123__ANR26650M1-B.json").write_text(
        (ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (cell_instances_dir / "cell-3m6k-9t2p-7x4h-9nq8.json").write_text(
        (ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (datasets_dir / "dataset-1f8r-6v2k-9p4m-3t7x.json").write_text(
        (ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Only the tests linked to this A123 cell instance (other cells' tests, e.g. the
    # NMC811 fleet showcase, link to different instances and aren't part of this batch).
    a123_cell_id = "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    for path in sorted((ROOT / "examples" / "test").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("test", {}).get("cell_id") != a123_cell_id:
            continue
        (tests_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    summary = save_batch(
        source_dirs=[
            cell_specs_dir,
            cell_instances_dir,
            tests_dir,
            datasets_dir,
        ],
        source_root=source_root,
        resolve_references=True,
        duplicate_policy="return_existing",
    )

    assert summary["status"] == "ok"
    assert summary["failed"] == 0
    assert summary["processed"] == 11


def test_template_builders_are_saveable(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"

    cell_spec_record = template_cell_spec(
        manufacturer="Duracell",
        model_name="MN1500",
        chemistry="Zn-air",
        format="cylindrical",
        uid="3m6k9t2p7x4h9nq8",
    )
    reg_type = save_record(cell_spec_record, source_root=source_root, resolve_references=False)
    assert reg_type["status"] == "created"

    cell_instance_record = template_cell_instance(
        cell_spec_id=cell_spec_record["cell_spec"]["id"],
        source_type="lab",
        uid="1f8r6v2k9p4m3t7x",
    )
    reg_cell = save_record(cell_instance_record, source_root=source_root, resolve_references=True)
    assert reg_cell["status"] == "created"

    test_record = template_test(
        cell_id=cell_instance_record["cell_instance"]["id"],
        name="MN1500 baseline cycling",
        kind="cycling",
        source_type="measurement",
        uid="5p7v2n8k4m3t6q9r",
    )
    reg_test = save_record(test_record, source_root=source_root, resolve_references=True)
    assert reg_test["status"] == "created"

    dataset_record = template_dataset(
        title="MN1500 dataset",
        source_type="measurement",
        uid="8c1h8pk68034vav6",
        related_cell_ids=[cell_instance_record["cell_instance"]["id"]],
        related_test_ids=[test_record["test"]["id"]],
    )
    reg_dataset = save_record(dataset_record, source_root=source_root, resolve_references=True)
    assert reg_dataset["status"] == "created"


def test_save_query_and_build_library_cell_spec(tmp_path: Path) -> None:
    library_root = tmp_path / "library" / "cell-spec"
    packaged_root = tmp_path / "package" / "cell-spec"
    rdf_root = tmp_path / "library-rdf" / "cell-spec"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-spec.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-spec.index.json"

    payload = save_library_cell_spec(
        {
            "uid": "9qfb4wrnynwcayjw",
            "manufacturer": "A123",
            "model": "ANR26650M1-B",
            "format": "cylindrical",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": "graphite",
            "size_code": "R26650",
            "property": {
                "nominal_capacity": {"typical_value": 2.5, "unit": "Ah"},
                "nominal_voltage": {"value": 3.3, "unit": "V"},
            },
            "source_type": "datasheet",
            "source_file": "A123__ANR26650M1-B.pdf",
            "citation": "https://doi.org/10.17632/kxsbr4x3j2.2",
        },
        library_root=library_root,
        package_root=packaged_root,
    )
    assert payload["status"] == "created"
    assert Path(payload["path"]).exists()
    assert Path(payload["package_path"]).exists()
    assert payload["synced_package"] is True
    stored = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert stored["provenance"]["citation"] == "https://doi.org/10.17632/kxsbr4x3j2.2"

    duplicate = save_library_cell_spec(
        {
            "uid": "9qfb4wrnynwcayjw",
            "manufacturer": "A123",
            "model": "ANR26650M1-B",
            "format": "cylindrical",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": "graphite",
            "source_file": "A123__ANR26650M1-B.pdf",
        },
        library_root=library_root,
        package_root=packaged_root,
        duplicate_policy="return_existing",
    )
    assert duplicate["status"] == "exists"

    rows = query_library_cell_specs(
        manufacturer="A123",
        chemistry="Li-ion",
        nominal_capacity_min=2.4,
        nominal_voltage_max=3.4,
        directory=library_root,
    )
    assert len(rows) == 1
    assert rows[0]["model"] == "ANR26650M1-B"
    assert rows[0]["nominal_capacity"] == 2.5

    build_result = build_cell_spec_library_rdf(
        input_dir=library_root,
        output_jsonld_dir=rdf_root,
        aggregate_jsonld=aggregate_jsonld,
        manifest_json=manifest_json,
    )
    assert build_result["status"] == "ok"
    assert build_result["entry_count"] == 1
    assert aggregate_jsonld.exists()
    assert manifest_json.exists()
    assert (rdf_root / "A123__ANR26650M1-B.jsonld").exists()

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 1
    assert manifest["entries"][0]["manufacturer"] == "A123"


def test_template_library_cell_spec_is_saveable(tmp_path: Path) -> None:
    library_root = tmp_path / "library" / "cell-spec"
    packaged_root = tmp_path / "package" / "cell-spec"

    record = template_library_cell_spec(
        manufacturer="Energizer",
        model="CR2032",
        chemistry="Li-primary",
        format="coin",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        uid="7r2m4q8vk6ntc3pj",
    )
    payload = save_library_cell_spec(
        record,
        library_root=library_root,
        package_root=packaged_root,
    )
    assert payload["status"] == "created"
    stored = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert stored["specification"]["model"] == "CR2032"


def test_save_library_cell_spec_persists_construction_metadata(tmp_path: Path) -> None:
    library_root = tmp_path / "library" / "cell-spec"
    packaged_root = tmp_path / "package" / "cell-spec"

    payload = save_library_cell_spec(
        {
            "uid": "4p7m2q8v6n3t9k5r",
            "manufacturer": "ExampleCells",
            "model": "SLP-001",
            "format": "pouch",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "NMC",
            "negative_electrode_basis": "graphite",
            "construction": {
                "assembly_type": "stacked",
                "layering": "single_layer",
                "layer_count": 1,
            },
            "source_file": "SLP-001.json",
        },
        library_root=library_root,
        package_root=packaged_root,
    )

    assert payload["status"] == "created"
    stored = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert stored["specification"]["construction"]["layering"] == "single_layer"

    rows = query_library_cell_specs(directory=library_root)
    assert rows[0]["construction"]["assembly_type"] == "stacked"


def test_library_flat_dict_carries_full_physical_structure(tmp_path: Path) -> None:
    # The retired CellDatasheetInput could only carry construction + property. The flat-dict
    # path (_library_record_from_input) must carry the FULL physical structure — electrodes,
    # electrolyte, separator, and housing — so a detailed spec authored as a plain dict is not lossy.
    library_root = tmp_path / "library" / "cell-spec"
    packaged_root = tmp_path / "package" / "cell-spec"
    payload = save_library_cell_spec(
        {
            "uid": "5h8k2m9q4v6n3t7r",
            "manufacturer": "ExampleLab",
            "model": "COIN-LFP-2032",
            "format": "coin",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": "graphite",
            "size_code": "2032",
            "positive_electrode": {
                "coating": {
                    "component": {
                        "active_material": [
                            {"name": "LFP", "property": {"mass_fraction": {"value": 0.92, "unit": "1"}}}
                        ],
                        "binder": [
                            {"name": "PVDF", "property": {"mass_fraction": {"value": 0.08, "unit": "1"}}}
                        ],
                    },
                    "property": {"thickness": {"value": 55.0, "unit": "um"}},
                },
                "current_collector": {"name": "Al foil"},
            },
            "negative_electrode": {
                "coating": {
                    "component": {
                        "active_material": [
                            {"name": "Graphite", "property": {"mass_fraction": {"value": 0.95, "unit": "1"}}}
                        ],
                        "binder": [
                            {"name": "CMC/SBR", "property": {"mass_fraction": {"value": 0.05, "unit": "1"}}}
                        ],
                    },
                },
                "current_collector": {"name": "Cu foil"},
            },
            "electrolyte": {
                "family": "organic",
                "salt": {"name": "LiPF6", "property": {"concentration": {"value": 1.0, "unit": "mol/L"}}},
            },
            "separator": {"material": "PP membrane", "property": {"thickness": {"value": 20.0, "unit": "um"}}},
            "housing": {"case": {"size_code": "2032", "material": "Stainless steel"}},
            "source_file": "coin-detailed.json",
        },
        library_root=library_root,
        package_root=packaged_root,
    )
    assert payload["status"] == "created"
    spec = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))["specification"]
    # All five physical sub-structures survive the flat-dict path (not just construction/property).
    assert spec["positive_electrode"]["current_collector"]["name"] == "Al foil"
    assert spec["negative_electrode"]["current_collector"]["name"] == "Cu foil"
    assert spec["electrolyte"]["salt"]["name"] == "LiPF6"
    assert spec["separator"]["material"] == "PP membrane"
    assert spec["housing"]["case"]["size_code"] == "2032"





