"""A record read into its model and written back says what it said.

``docs/howto/read-registry-data.md`` tells users to make a new version of a published dataset with ``Dataset.from_record(record)``, a change and a save. Whatever the model does not carry is missing from the new version, and nothing warns about it.

The first two sections pin the two losses found that way in the ``Dataset`` model, a distribution's ``conditions`` and the ``about`` entries that are neither a cell nor a test. The third sends every packaged example of every record type that has a model through it, and fails on any difference that ``ALLOWED`` does not list with its reason.
"""

from __future__ import annotations

import copy
import functools
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest

import battinfo
from battinfo import bundle, validate_record
from battinfo._workspace import _content_seed, _legacy_content_seed
from battinfo.bundle import BundleJsonModel, Cell, CellSpec, Dataset, Test, TestSpec
from battinfo.entities import ENTITY_KINDS, kind_for_doc

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


# ── Every packaged example, through its model ─────────────────────────────────
#
# Each example record of a type that has a model is read with from_record, written with to_record and compared with what it was, as JSON, which is what a save writes. The order of an object's keys does not count. Every other difference fails the test unless ALLOWED lists it for the record type.

# The record types with a model that has from_record and to_record. The other 17 types are built by functions (battinfo.api.create_*), which have no way back from a record.
MODELS: dict[str, type[BundleJsonModel]] = {
    "cell-spec": CellSpec,
    "cell": Cell,
    "test-protocol": TestSpec,
    "test": Test,
    "dataset": Dataset,
}


class Difference(NamedTuple):
    """One difference between a record and its round trip. *path* names a list item as ``[]``."""

    path: str
    change: str  # "added", "dropped" or "changed"
    before: Any
    after: Any

    @property
    def value(self) -> Any:
        """What the condition of an allowed difference looks at."""
        return {"added": self.after, "dropped": self.before}.get(self.change, (self.before, self.after))


class Allowed(NamedTuple):
    """A difference a model is allowed to make, and why. ``*.key`` in *path* is that key in any holder."""

    path: str
    change: str
    when: Callable[[Any], bool]
    why: str

    def covers(self, difference: Difference) -> bool:
        same_path = (
            difference.path.endswith(self.path[1:]) if self.path.startswith("*.") else difference.path == self.path
        )
        return same_path and difference.change == self.change and self.when(difference.value)


def _any_value(value: Any) -> bool:
    return True


def _empty(value: Any) -> bool:
    return value in ({}, [])


def _null(value: Any) -> bool:
    return value is None


def _this_version(value: Any) -> bool:
    return value == battinfo.__version__


def _whole_number_as_float(value: Any) -> bool:
    before, after = value
    return type(before) is int and type(after) is float and before == after


_DERIVED = "derived from the record's IRI and written when the record leaves it out"
_STAMP = "to_record stamps the library's version on a record that states none"
# The words every known loss starts with. Each was found by the comparison this test makes, when the Dataset model's two losses were fixed (branch fix/dataset-model-round-trip, November 2026), and left as it was because it is not a one-line omission. Fix one and delete its line.
_LOSS = "KNOWN LOSS, found and left by the dataset model round-trip task of November 2026. "

ALLOWED: dict[str, tuple[Allowed, ...]] = {
    "cell-spec": (
        Allowed("cell_spec.short_id", "added", _any_value, _DERIVED),
        Allowed("cell_spec.identifier", "added", _any_value, _DERIVED),
        Allowed("provenance.battinfo_version", "added", _this_version, _STAMP),
        # The component models write their empty defaults.
        Allowed("properties", "added", _empty, "a spec without properties is written with an empty map"),
        Allowed("*.property", "added", _empty, "a component without properties is written with an empty map"),
        Allowed(
            "electrolyte.additive", "added", _empty, "an electrolyte without additives is written with an empty list"
        ),
        Allowed("housing.seals", "added", _empty, "a housing without seals is written with an empty list"),
        Allowed("housing.terminals", "added", _empty, "a housing without terminals is written with an empty list"),
        Allowed("provenance.source_file", "dropped", _null, "a null is left out"),
        Allowed("provenance.source_url", "dropped", _null, "a null is left out"),
        Allowed("cell_spec.brand", "dropped", _any_value, _LOSS + "CellSpec has no field for schema:brand."),
        Allowed("cell_spec.category", "dropped", _any_value, _LOSS + "CellSpec has no field for schema:category."),
        Allowed(
            "cell_spec.manufacturer.same_as",
            "dropped",
            _any_value,
            _LOSS + "CellSpec keeps a manufacturer's name and organization IRI, not its same_as link.",
        ),
    ),
    "cell": (
        Allowed("cell_instance.short_id", "added", _any_value, _DERIVED),
        Allowed("cell_instance.name", "added", _any_value, "a cell without a name takes its serial number"),
        Allowed("provenance.battinfo_version", "added", _this_version, _STAMP),
        Allowed(
            "contributor",
            "dropped",
            _any_value,
            _LOSS + "No model carries the record envelope (funding, contributor, and license outside a dataset), "
            "which a workspace stamps at save, so a record written back by a model alone is without it.",
        ),
    ),
    "test-protocol": (
        Allowed("test_spec.short_id", "added", _any_value, _DERIVED),
        Allowed("test_spec.identifier", "added", _any_value, _DERIVED),
        Allowed("provenance.battinfo_version", "added", _this_version, _STAMP),
        # to_record computes the facets from the method and never reads the ones a record holds. Seven examples hold none, one lacks the temperatures, and two hold a mode ("group") the method no longer gives.
        Allowed("facets", "added", _any_value, "computed from the method"),
        Allowed("facets.temperatures", "added", _any_value, "computed from the method"),
        Allowed("facets.modes[]", "changed", _any_value, "computed from the method"),
        Allowed("method[].steps", "dropped", _empty, "an empty list in a step is left out"),
        Allowed("method[].tags", "dropped", _empty, "an empty list in a step is left out"),
        Allowed("method[].termination", "dropped", _empty, "an empty list in a step is left out"),
        Allowed("method[].termination[].value", "changed", _whole_number_as_float, "a quantity's value is a float"),
    ),
    "test": (
        Allowed("test.short_id", "added", _any_value, _DERIVED),
        Allowed("provenance.battinfo_version", "added", _this_version, _STAMP),
    ),
    "dataset": (
        # to_record also writes about as cells, then tests, then the rest. Every example has that order already, so nothing is listed for it; the section above pins it.
        Allowed("dataset.short_id", "added", _any_value, _DERIVED),
        Allowed("provenance.battinfo_version", "added", _this_version, _STAMP),
        *(
            Allowed(
                f"provenance.{key}",
                "dropped",
                _any_value,
                _LOSS + "ProvenanceInfo has no field for the intake keys of the dataset schema's provenance.",
            )
            for key in ("source_dataset_key", "ingest_status", "quality_flags")
        ),
    ),
}


def _differences(before: Any, after: Any, path: str = "") -> Iterator[Difference]:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            where = f"{path}.{key}" if path else key
            if key not in after:
                yield Difference(where, "dropped", before[key], None)
            elif key not in before:
                yield Difference(where, "added", None, after[key])
            else:
                yield from _differences(before[key], after[key], where)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for left, right in zip(before, after, strict=True):
            yield from _differences(left, right, f"{path}[]")
    elif type(before) is not type(after) or before != after:
        yield Difference(path, "changed", before, after)


def _round_trip(entity_type: str, record: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(MODELS[entity_type].from_record(record).to_record()))


def _example_cases() -> list[tuple[str, Path]]:
    cases = []
    for path in sorted(EXAMPLES.rglob("*.json")):
        kind = kind_for_doc(json.loads(path.read_text(encoding="utf-8")))
        if kind is not None and kind.entity_type in MODELS:
            cases.append((kind.entity_type, path))
    return cases


EXAMPLE_CASES = _example_cases()


@functools.cache
def _example_differences(entity_type: str) -> dict[str, list[Difference]]:
    """The differences each example of *entity_type* shows, by its path under the examples."""
    found = {}
    for kind, path in EXAMPLE_CASES:
        if kind == entity_type:
            record = json.loads(path.read_text(encoding="utf-8"))
            found[path.relative_to(EXAMPLES).as_posix()] = list(_differences(record, _round_trip(kind, record)))
    return found


def test_the_sweep_takes_every_model_that_reads_and_writes_a_record() -> None:
    models = {
        value
        for value in vars(bundle).values()
        if isinstance(value, type)
        and issubclass(value, BundleJsonModel)
        and hasattr(value, "from_record")
        and hasattr(value, "to_record")
    }
    assert models == set(MODELS.values())
    assert set(MODELS) <= {kind.entity_type for kind in ENTITY_KINDS}


def test_the_sweep_has_examples_of_every_modelled_type() -> None:
    counts = {entity_type: len(_example_differences(entity_type)) for entity_type in MODELS}
    assert all(count >= 5 for count in counts.values()), counts
    assert sum(counts.values()) >= 70, counts


@pytest.mark.parametrize(
    ("entity_type", "path"), EXAMPLE_CASES, ids=[path.relative_to(EXAMPLES).as_posix() for _, path in EXAMPLE_CASES]
)
def test_an_example_says_the_same_after_its_model(entity_type: str, path: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    back = _round_trip(entity_type, record)
    unexpected = [
        f"{difference.change} {difference.path}: {difference.before!r} -> {difference.after!r}"
        for difference in _differences(record, back)
        if not any(allowed.covers(difference) for allowed in ALLOWED[entity_type])
    ]
    assert not unexpected, (
        f"{MODELS[entity_type].__name__}.from_record(record).to_record() changed what the record says. Carry the "
        "field in the model, or list the difference in ALLOWED with the reason:\n  " + "\n  ".join(unexpected)
    )
    # Reading the written record back changes nothing more.
    assert _round_trip(entity_type, back) == back


@pytest.mark.parametrize(
    ("entity_type", "allowed"),
    [(entity_type, allowed) for entity_type, entries in ALLOWED.items() for allowed in entries],
    ids=lambda value: f"{value.change} {value.path}" if isinstance(value, Allowed) else value,
)
def test_an_allowed_difference_still_occurs(entity_type: str, allowed: Allowed) -> None:
    """Delete the entry when no example needs it any more, so the list holds only what the models do."""
    assert allowed.why.strip()
    assert any(
        allowed.covers(difference)
        for differences in _example_differences(entity_type).values()
        for difference in differences
    ), f"no {entity_type} example shows this difference any more; delete it from ALLOWED"
