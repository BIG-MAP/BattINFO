"""A record read into its model and written back says what it said.

``docs/howto/read-registry-data.md`` tells users to make a new version of a published dataset with ``Dataset.from_record(record)``, a change and a save. Whatever the model does not carry is missing from the new version, and nothing warns about it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from battinfo import validate_record
from battinfo._workspace import _content_seed, _legacy_content_seed
from battinfo.bundle import Dataset

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "src" / "battinfo" / "data" / "schemas"

OLD_FORM = "https://w3id.org/battinfo/"
PREFIXED_FORM = "https://w3id.org/battinfo/id/1001/"


def _dataset_record(**body: Any) -> dict[str, Any]:
    """A small valid dataset record, with *body* added to its ``dataset`` object."""
    return {
        "schema_version": "0.2.0",
        "dataset": {
            "id": OLD_FORM + "dataset/aaaa-bbbb-cccc-dddd",
            "short_id": "aaaabb",
            "identifier": "dataset:aaaa-bbbb-cccc-dddd",
            "name": "EIS spectra of cell C01",
            "access_url": "https://example.org/data/c01",
            "about": [OLD_FORM + "cell/aaaa-aaaa-aaaa-aaaa"],
            **copy.deepcopy(body),
        },
        "provenance": {"source_type": "measurement", "retrieved_at": 1767225600, "battinfo_version": "0.8.0"},
    }


def _assert_valid(record: dict[str, Any]) -> None:
    report = validate_record(record)
    assert report.ok, [issue.message for issue in report.errors]


# ── A distribution's fields ───────────────────────────────────────────────────

# One value for every property the dataset schema names for a distribution.
FULL_DISTRIBUTION: dict[str, Any] = {
    "type": "DataDownload",
    "name": "c01_eis_soc50.csv",
    "description": "EIS spectrum at 50 % state of charge.",
    "content_url": "https://example.org/data/c01/c01_eis_soc50.csv",
    "encoding_format": "text/csv",
    "content_size": "12.4 MB",
    "checksum": {"algorithm": "sha256", "value": "a" * 64},
    "access_level": "open",
    "role": "processed",
    "conditions": {"soc": 0.5, "ambient_temperature": {"value": 25, "unit": "degC"}},
}


def test_the_distribution_case_names_every_property_of_the_schema() -> None:
    schema = json.loads((SCHEMAS / "dataset.schema.json").read_text(encoding="utf-8"))
    assert set(FULL_DISTRIBUTION) == set(schema["$defs"]["DataDistribution"]["properties"])


def test_a_distribution_keeps_every_field_through_the_model() -> None:
    record = _dataset_record(distributions=[FULL_DISTRIBUTION, {**FULL_DISTRIBUTION, "conditions": {}}])
    _assert_valid(record)
    assert Dataset.from_record(record).to_record() == record


def test_a_dataset_built_with_distribution_conditions_keeps_them() -> None:
    given = copy.deepcopy(FULL_DISTRIBUTION)
    dataset = Dataset(
        id=OLD_FORM + "dataset/aaaa-bbbb-cccc-dddd",
        name="EIS spectra of cell C01",
        access_url="https://example.org/data/c01",
        distributions=[given],
    )
    assert dataset.to_record()["dataset"]["distributions"] == [FULL_DISTRIBUTION]
    # The model holds its own copy: a later change to what the caller passed does not reach it.
    given["conditions"]["soc"] = 0.9
    assert dataset.distributions[0]["conditions"] == FULL_DISTRIBUTION["conditions"]


def test_the_model_leaves_the_keys_of_distribution_conditions_to_validation() -> None:
    record = _dataset_record(distributions=[{**FULL_DISTRIBUTION, "conditions": {"SOC": 0.5}}])
    back = Dataset.from_record(record).to_record()
    assert back["dataset"]["distributions"][0]["conditions"] == {"SOC": 0.5}
    assert not validate_record(back).ok


def test_distribution_conditions_that_are_not_a_mapping_are_not_carried() -> None:
    record = _dataset_record(distributions=[{**FULL_DISTRIBUTION, "conditions": "50 % SOC"}])
    assert "conditions" not in Dataset.from_record(record).to_record()["dataset"]["distributions"][0]


def _draft(**fields: Any) -> Dataset:
    """A dataset without an IRI, as a session holds it before a save mints one."""
    return Dataset(name="EIS spectra of cell C01", access_url="https://example.org/data/c01", **fields)


def test_distribution_conditions_stay_out_of_the_content_seed() -> None:
    # Seed rules are frozen with 0.8.0, whose model dropped a distribution's conditions. A dataset given them keeps the seed, and so the IRI, that release minted. tests/test_golden_iris.py holds the IRIs.
    without = {key: value for key, value in FULL_DISTRIBUTION.items() if key != "conditions"}
    given, plain = _draft(distributions=[FULL_DISTRIBUTION]), _draft(distributions=[without])
    assert given.distributions[0]["conditions"] == FULL_DISTRIBUTION["conditions"]
    assert _content_seed(given) == _content_seed(plain)
    assert _legacy_content_seed(given) == _legacy_content_seed(plain)
