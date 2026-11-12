"""A dataset's table group lists its tables under ``tables``.

``battinfo.metadata.csvw_table_group()`` and the ``Dataset`` model write ``tables``, the key the CSVW metadata vocabulary uses. The dataset schema named the property ``table``, so no table group could be saved. The schema now names it ``tables``, and a record another client wrote with ``table`` still loads, because the reader renames the key.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from pyld import jsonld as _jsonld

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Dataset, save_dataset  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.metadata import TableColumn, TableSchema, csvw_table, csvw_table_group  # noqa: E402
from battinfo.validate import record_fidelity_report  # noqa: E402
from battinfo.validate.jsonld import _inline_local_contexts  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402
from battinfo.validate.schema import schema_for_rel_path, validate_schema_data  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

CSVW = "http://www.w3.org/ns/csvw#"
SCHEMA_ORG = "https://schema.org/"


def _group() -> dict[str, Any]:
    voltage = TableSchema(
        columns=[TableColumn(name="voltage", datatype="number", unit_text="V")], primary_key="voltage"
    )
    current = TableSchema(columns=[TableColumn(name="current", datatype="number", unit_text="A")])
    return csvw_table_group(
        csvw_table("cycle-1.csv", table_schema=voltage, name="first cycle"),
        csvw_table("cycle-2.csv", table_schema=current),
        id="https://example.org/data#tables",
        name="cycles",
        description="One table for each cycle.",
    )


def _saved(dataset: Dataset, root: Path) -> dict[str, Any]:
    result = save_dataset(dataset, source_root=root, resolve_references=False)
    return json.loads(Path(result["path"]).read_text(encoding="utf-8"))


def _schema_errors(record: dict[str, Any]) -> list[str]:
    report = validate_schema_data(record, schema_for_rel_path("dataset.schema.json"))
    return [f"{issue.path}: {issue.message}" for issue in report.issues]


def _record_schema_codes(record: dict[str, Any]) -> list[str]:
    """The schema findings of the package's record validation, which reads older keys first."""
    report = validate_record_report(record, policy="strict")
    return [issue.code for issue in report.issues if issue.code.startswith("schema.")]


def _record_with_old_key(record: dict[str, Any]) -> dict[str, Any]:
    """*record* as a client that followed the schema before would have written it."""
    old = copy.deepcopy(record)
    (group,) = old["dataset"]["main_entity"]
    group["table"] = group.pop("tables")
    return old


def test_the_helpers_table_group_saves_and_validates(tmp_path: Path) -> None:
    group = _group()
    assert "tables" in group and "table" not in group
    record = _saved(Dataset(name="data", access_url="https://example.org/data", main_entity=[group]), tmp_path)
    (entity,) = record["dataset"]["main_entity"]
    assert entity["type"] == "TableGroup"
    assert [table["url"] for table in entity["tables"]] == ["cycle-1.csv", "cycle-2.csv"]
    assert entity["tables"][0]["table_schema"]["primary_key"] == "voltage"
    assert _schema_errors(record) == []
    assert _record_schema_codes(record) == []
    assert validate_record_report(record).ok


def test_a_record_written_with_the_old_key_loads_and_validates(tmp_path: Path) -> None:
    record = _saved(Dataset(name="data", access_url="https://example.org/data", main_entity=[_group()]), tmp_path)
    old = _record_with_old_key(record)
    # The package reads the old key, so its record validation accepts the record.
    assert _record_schema_codes(old) == []
    assert validate_record_report(old).ok
    loaded = Dataset.from_record(old)
    assert loaded.main_entity == record["dataset"]["main_entity"]
    rewritten = loaded.to_record()
    assert rewritten["dataset"]["main_entity"] == record["dataset"]["main_entity"]
    assert _schema_errors(rewritten) == []


def test_the_schema_names_the_list_tables_and_refuses_table(tmp_path: Path) -> None:
    group = schema_for_rel_path("dataset.schema.json")["$defs"]["CsvwTableGroup"]
    assert group["required"] == ["type", "tables"]
    assert "tables" in group["properties"] and "table" not in group["properties"]
    assert group["additionalProperties"] is False
    record = _saved(Dataset(name="data", access_url="https://example.org/data", main_entity=[_group()]), tmp_path)
    assert _schema_errors(_record_with_old_key(record))
    both = copy.deepcopy(record)
    both["dataset"]["main_entity"][0]["table"] = both["dataset"]["main_entity"][0]["tables"]
    assert _schema_errors(both)
    empty = copy.deepcopy(record)
    empty["dataset"]["main_entity"][0]["tables"] = []
    assert _schema_errors(empty)


def test_the_jsonld_of_a_table_group_is_a_csvw_table_group(tmp_path: Path) -> None:
    record = _saved(Dataset(name="data", access_url="https://example.org/data", main_entity=[_group()]), tmp_path)
    node = record_to_jsonld(record, "dataset")
    group = node["schema:mainEntity"]
    assert group["@type"] == "csvw:TableGroup"
    assert group["@id"] == "https://example.org/data#tables"
    assert [table["@type"] for table in group["csvw:table"]] == ["csvw:Table", "csvw:Table"]
    assert [table["csvw:url"] for table in group["csvw:table"]] == ["cycle-1.csv", "cycle-2.csv"]
    # Every term resolves through the document's own context, read from the bundled copy.
    (expanded,) = _jsonld.expand(_inline_local_contexts(node))
    (main_entity,) = expanded[f"{SCHEMA_ORG}mainEntity"]
    assert main_entity["@type"] == [f"{CSVW}TableGroup"]
    tables = main_entity[f"{CSVW}table"]
    assert [table["@type"] for table in tables] == [[f"{CSVW}Table"], [f"{CSVW}Table"]]
    (first_schema,) = tables[0][f"{CSVW}tableSchema"]
    assert first_schema["@type"] == [f"{CSVW}Schema"]
    (column,) = first_schema[f"{CSVW}column"]
    assert column[f"{CSVW}name"] == [{"@value": "voltage"}]
    # The same record read with the old key gives the same node.
    assert record_to_jsonld(_record_with_old_key(record), "dataset") == node


def test_a_deposit_leaves_a_table_group_out_and_the_check_names_it(tmp_path: Path) -> None:
    """The deposit graph carries no main entity of a member dataset, a table or a group, and says so."""
    record = _saved(Dataset(name="data", access_url="https://example.org/data", main_entity=[_group()]), tmp_path)
    dataset_id = record["dataset"]["id"]
    record_sets = {"cell-spec": [], "cell-instance": [], "test": [], "test-protocol": [], "dataset": [record]}
    graph = AuthoringWorkspace._assemble_zenodo_jsonld(
        copy.deepcopy(record_sets),
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="t",
        description="d",
        creators=[{"name": "Deposit Person"}],
        license="cc-by-4.0",
    )
    member = next(node for node in graph["@graph"] if node.get("@id") == dataset_id)
    assert "schema:mainEntity" not in member
    assert "TableGroup" not in json.dumps(graph)
    paths = [issue.path for issue in record_fidelity_report(graph, record_sets).issues]
    assert f"dataset:{dataset_id}.main_entity" in paths
