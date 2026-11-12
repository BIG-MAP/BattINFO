"""A record read into its model and written back says what it said.

``docs/howto/read-registry-data.md`` tells users to make a new version of a published dataset with ``Dataset.from_record(record)``, a change and a save. Whatever the model does not carry is missing from the new version, and nothing warns about it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import battinfo
from battinfo import validate_record
from battinfo._workspace import _content_seed, _legacy_content_seed
from battinfo.bundle import Dataset

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "src" / "battinfo" / "data" / "schemas"
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"

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


# ── What a dataset is about ───────────────────────────────────────────────────

UID = {
    "cell": "aaaa-aaaa-aaaa-aaaa",
    "test": "bbbb-bbbb-bbbb-bbbb",
    "spec": "cccc-cccc-cccc-cccc",
    "material": "dddd-dddd-dddd-dddd",
}
EXTERNAL = "https://example.org/batches/42"
BOTH_FORMS = pytest.mark.parametrize("base", [OLD_FORM, PREFIXED_FORM], ids=["old form", "prefixed form"])


def _iri(base: str, segment: str, uid: str | None = None) -> str:
    return f"{base}{segment}/{uid or UID[segment]}"


@BOTH_FORMS
def test_about_keeps_a_cell_a_test_a_spec_a_material_and_an_external_url(base: str) -> None:
    about = [_iri(base, "cell"), _iri(base, "test"), _iri(base, "spec"), _iri(base, "material"), EXTERNAL]
    record = _dataset_record(about=about)
    _assert_valid(record)
    dataset = Dataset.from_record(record)
    assert dataset.cell_instance_id == about[0]
    assert dataset.test_id == about[1]
    assert (dataset.related_cell_ids, dataset.related_test_ids) == ([], [])
    assert dataset.related_ids == about[2:]
    assert dataset.to_record() == record


@BOTH_FORMS
def test_about_keeps_further_cells_and_tests_of_either_form(base: str) -> None:
    other = PREFIXED_FORM if base == OLD_FORM else OLD_FORM
    about = [
        _iri(base, "cell"),
        _iri(other, "cell", "eeee-eeee-eeee-eeee"),
        _iri(other, "test"),
        _iri(base, "test", "ffff-ffff-ffff-ffff"),
        _iri(other, "spec"),
    ]
    record = _dataset_record(about=about)
    _assert_valid(record)
    dataset = Dataset.from_record(record)
    assert (dataset.cell_instance_id, dataset.related_cell_ids) == (about[0], [about[1]])
    assert (dataset.test_id, dataset.related_test_ids) == (about[2], [about[3]])
    assert dataset.related_ids == [about[4]]
    assert dataset.to_record() == record


def test_the_material_and_spec_example_keeps_its_about() -> None:
    record = json.loads((EXAMPLES / "dataset" / "dataset-nxv4-ecrt-9wnm-a2yt.json").read_text(encoding="utf-8"))
    about = record["dataset"]["about"]
    assert [iri.split("/")[-2] for iri in about] == ["material", "spec"]
    dataset = Dataset.from_record(record)
    assert (dataset.cell_instance_id, dataset.test_id, dataset.related_ids) == (None, None, about)
    assert dataset.to_record()["dataset"]["about"] == about


def test_an_external_url_with_cell_or_test_in_its_path_is_an_external_reference() -> None:
    cell = _iri(OLD_FORM, "cell")
    urls = ["https://example.org/cell/42", "https://example.org/id/1001/test/7"]
    dataset = Dataset.from_record(_dataset_record(about=[*urls, cell]))
    assert (dataset.cell_instance_id, dataset.test_id) == (cell, None)
    assert dataset.related_ids == urls
    assert dataset.to_record()["dataset"]["about"] == [cell, *urls]


def test_a_malformed_battinfo_cell_or_test_iri_is_still_read_as_the_cell_or_test(tmp_path: Path) -> None:
    # Not record IRIs (the uid is malformed), so the parser has no segment to go by. They are read as before, and a save names them as the cell and test references they fail to be.
    cell, test = OLD_FORM + "cell/C01", PREFIXED_FORM + "test/run-7"
    dataset = Dataset.from_record(_dataset_record(about=[cell, test]))
    assert (dataset.cell_instance_id, dataset.test_id, dataset.related_ids) == (cell, test, [])
    with pytest.raises(ValueError, match="related_cell_ids entries must match"):
        battinfo.save_dataset(dataset, source_root=tmp_path, dry_run=True)


def test_about_is_written_cells_then_tests_then_the_rest_and_reading_it_back_changes_nothing() -> None:
    cell, test, spec = _iri(OLD_FORM, "cell"), _iri(PREFIXED_FORM, "test"), _iri(OLD_FORM, "spec")
    shared_thing = OLD_FORM + "id/" + UID["material"]
    record = _dataset_record(about=[spec, test, EXTERNAL, cell, shared_thing])
    _assert_valid(record)
    once = Dataset.from_record(record).to_record()
    assert once["dataset"]["about"] == [cell, test, spec, EXTERNAL, shared_thing]
    assert Dataset.from_record(once).to_record() == once
    once["dataset"]["about"] = record["dataset"]["about"]
    assert once == record  # only the order of about differs


def test_a_reference_given_twice_is_written_once() -> None:
    cell, spec = _iri(OLD_FORM, "cell"), _iri(OLD_FORM, "spec")
    dataset = Dataset(
        id=OLD_FORM + "dataset/aaaa-bbbb-cccc-dddd",
        name="EIS spectra of cell C01",
        access_url="https://example.org/data/c01",
        cell_instance_id=cell,
        related_cell_ids=[cell],
        related_ids=[spec, EXTERNAL, spec, cell],
    )
    assert dataset.to_record()["dataset"]["about"] == [cell, spec, EXTERNAL]


def test_save_dataset_writes_related_ids_to_about(tmp_path: Path) -> None:
    cell, spec = _iri(PREFIXED_FORM, "cell"), _iri(PREFIXED_FORM, "spec")
    dataset = Dataset(
        name="EIS spectra of cell C01",
        access_url="https://example.org/data/c01",
        cell_instance_id=cell,
        related_ids=[spec, EXTERNAL],
        source={"type": "measurement"},
    )
    result = battinfo.save_dataset(
        dataset,
        source_root=tmp_path,
        validation_policy="strict",
        resolve_references=False,
        build_jsonld=False,
        build_html=False,
    )
    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["dataset"]["about"] == [cell, spec, EXTERNAL]
    assert Dataset.from_record(saved).to_record() == saved


def test_related_ids_stay_out_of_the_content_seed() -> None:
    # The model of 0.8.0, with which seed rules are frozen, had no such field. Its dump now holds one, empty or not, and the seed leaves it out, so a dataset keeps the seed, and so the IRI, it had. tests/test_golden_iris.py holds the IRIs.
    plain, related = _draft(), _draft(related_ids=[_iri(OLD_FORM, "spec"), EXTERNAL])
    assert "related_ids" in plain.model_dump()
    assert "related_ids" not in _content_seed(plain)
    assert _content_seed(related) == _content_seed(plain)
    assert _legacy_content_seed(related) == _legacy_content_seed(plain)
