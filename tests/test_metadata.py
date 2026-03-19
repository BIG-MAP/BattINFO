from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    BatteryTestType,
    Cell,
    CellType,
    Test,
    checksum,
    csvw_table,
    csvw_table_group,
    data_catalog,
    distribution,
    infer_variable_measured,
    measured_variable,
    Dataset,
    organization,
    person,
    TableColumn,
    TableSchema,
)


def test_metadata_helpers_build_native_battinfo_shapes() -> None:
    lab = organization("Example Lab", ror="03yrm5c26")
    researcher = person(
        "Ada Lovelace",
        orcid="0000-0000-0000-0001",
        given_name="Ada",
        family_name="Lovelace",
        affiliation=lab,
    )
    catalog = data_catalog("Example Catalog", id="https://example.org/catalog", url="https://example.org/catalog")
    variable = measured_variable("Voltage", property_id="https://qudt.org/vocab/quantitykind/Voltage", unit_text="V")
    schema = TableSchema(
        id="https://example.org/table-schema",
        columns=[TableColumn(name="Voltage / V", same_as="https://qudt.org/vocab/quantitykind/Voltage")],
    )
    csvw = csvw_table("measurements/run.csv", table_schema=schema)
    group = csvw_table_group(csvw, name="tables")
    download = distribution(
        "https://example.org/data.csv",
        encoding_format="text/csv",
        checksum_value=checksum("sha256", "a" * 64),
    )

    assert lab["sameAs"] == "https://ror.org/03yrm5c26"
    assert researcher["sameAs"] == "https://orcid.org/0000-0000-0000-0001"
    assert researcher["affiliation"]["name"] == "Example Lab"
    assert catalog["type"] == "DataCatalog"
    assert variable["sameAs"] == "https://qudt.org/vocab/quantitykind/Voltage"
    assert csvw["type"] == "Table"
    assert csvw["tableSchema"]["id"] == "https://example.org/table-schema"
    assert group["table"][0]["tableSchema"]["columns"][0]["sameAs"] == "https://qudt.org/vocab/quantitykind/Voltage"
    assert download["checksum"]["value"] == "a" * 64


def test_infer_variable_measured_from_columns_and_metadata() -> None:
    variables = infer_variable_measured(
        columns=["Voltage / V", "Current / A", "Voltage / V"],
        column_metadata={
            "Voltage / V": {"iri": "https://qudt.org/vocab/quantitykind/Voltage"},
            "Current / A": {"iri": "https://qudt.org/vocab/quantitykind/ElectricCurrent"},
        },
    )

    assert variables == [
        {
            "name": "Voltage",
            "sameAs": "https://qudt.org/vocab/quantitykind/Voltage",
            "unit_text": "V",
        },
        {
            "name": "Current",
            "sameAs": "https://qudt.org/vocab/quantitykind/ElectricCurrent",
            "unit_text": "A",
        },
    ]


def test_dataset_with_tabular_data_populates_variables_and_csvw() -> None:
    cell_type = CellType(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
    )
    cell = Cell(cell_type, serial_number="alpha-001")
    test = Test(cell, test_type=BatteryTestType.CYCLE_LIFE)
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        name="Tabular dataset",
        description="Dataset with inferred tabular metadata.",
        distributions=[{"type": "DataDownload", "contentUrl": "https://example.org/data.csv", "encodingFormat": "text/csv"}],
        test=test,
    )

    schema = TableSchema(
        id="https://example.org/table-schema",
        columns=[
            TableColumn(name="Voltage", titles=["Voltage / V"], same_as="https://qudt.org/vocab/quantitykind/Voltage"),
            TableColumn(name="Current", titles=["Current / A"]),
        ],
    )

    enriched = dataset.with_tabular_data(table_schema=schema)

    assert enriched.variable_measured == [
        {
            "name": "Voltage",
            "sameAs": "https://qudt.org/vocab/quantitykind/Voltage",
            "unit_text": "V",
        },
        {
            "name": "Current",
            "unit_text": "A",
        },
    ]
    assert enriched.main_entity == [
        {
            "type": "Table",
            "url": "https://example.org/data.csv",
            "tableSchema": {
                "id": "https://example.org/table-schema",
                "columns": [
                    {
                        "name": "Voltage",
                        "titles": ["Voltage / V"],
                        "sameAs": "https://qudt.org/vocab/quantitykind/Voltage",
                    },
                    {
                        "name": "Current",
                        "titles": ["Current / A"],
                    },
                ],
            },
        }
    ]
    assert enriched.test is not None
    assert enriched.test.test_type == BatteryTestType.CYCLE_LIFE
    assert enriched.test.cell is not None
    assert enriched.test.cell.serial_number == "alpha-001"
