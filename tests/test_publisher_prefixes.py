"""The publisher prefix register, ``src/battinfo/data/namespace/prefixes.json``.

Ruling decision 3 (BIG-MAP/BattINFO#476, #480): every minting authority holds
a number of four or more digits, given out in sequence from 1000. 1000 is
BattINFO and holds definitions only; 1001 is the Battery Genome registry. The
namespace module takes its prefix constants from the register. Each entry
also says where the records minted under its prefix live, as URL templates
for a record's RDF and its human page, built from the uid.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import namespace  # noqa: E402
from battinfo.namespace import (  # noqa: E402
    PUBLISHER_PREFIXES,
    PublisherPrefix,
    parse_record_iri,
    publisher_prefix,
    record_iri,
)

UID = "b6yn-0sxe-t2qk-9mjv"


def _packaged(name: str) -> Any:
    return json.loads(resources.files("battinfo").joinpath("data", "namespace", name).read_text(encoding="utf-8"))


def _schema_errors(document: Any) -> list[str]:
    return [error.message for error in Draft202012Validator(_packaged("prefixes.schema.json")).iter_errors(document)]


def _entry(prefix: str, **changes: Any) -> dict[str, Any]:
    entry = {
        "prefix": prefix,
        "holder": "A publisher",
        "records": True,
        "records_rdf": None,
        "records_page": None,
        "allocated": "2026-10-25",
    }
    entry.update(changes)
    return entry


def _with_entry(number: str, /, **changes: Any) -> dict[str, Any]:
    """The packaged register with the entry of *number* changed."""
    document = copy.deepcopy(_packaged("prefixes.json"))
    next(entry for entry in document["prefixes"] if entry["prefix"] == number).update(changes)
    return document


def test_the_register_ships_with_the_package_and_loads() -> None:
    assert PUBLISHER_PREFIXES == {
        "1000": PublisherPrefix("1000", "BattINFO", False, None, None, date(2026, 10, 22)),
        "1001": PublisherPrefix("1001", "Battery Genome registry", True, None, None, date(2026, 10, 22)),
        "1002": PublisherPrefix("1002", "Battery Data Commons", True, None, None, date(2026, 10, 25)),
    }


def test_the_register_validates_against_its_schema() -> None:
    schema = _packaged("prefixes.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(_packaged("prefixes.json")), key=str)
    assert not errors, [error.message for error in errors]


def test_numbers_are_unique_and_in_sequence_from_1000() -> None:
    prefixes = [entry["prefix"] for entry in _packaged("prefixes.json")["prefixes"]]
    assert prefixes == [str(number) for number in range(1000, 1000 + len(prefixes))]
    assert list(PUBLISHER_PREFIXES) == prefixes


def test_the_prefix_constants_are_in_the_register() -> None:
    assert (namespace.BATTINFO_PREFIX, namespace.BATTERY_GENOME_PREFIX) == ("1000", "1001")
    assert PUBLISHER_PREFIXES[namespace.BATTINFO_PREFIX].records is False
    assert PUBLISHER_PREFIXES[namespace.BATTERY_GENOME_PREFIX].records is True
    assert namespace._OLD_FORM_PREFIX == namespace.BATTERY_GENOME_PREFIX


def test_an_allocation_date_that_is_not_text_is_refused() -> None:
    entry = _entry("1000", records=False, allocated=20261022)
    with pytest.raises(ValueError, match="allocation date"):
        namespace._load_prefix_register({"prefixes": [entry]})


# ── Where a holder's records live ───────────────────────────────────────────


def test_the_record_patterns_of_a_holder_load_as_written() -> None:
    rdf = "https://hub.example.org/records/{segment}/{uid}.ttl"
    page = "https://hub.example.org/records/{uid}"
    document = _with_entry("1002", records_rdf=rdf, records_page=page)
    assert not _schema_errors(document)
    entry = namespace._load_prefix_register(document)["1002"]
    assert (entry.records_rdf, entry.records_page) == (rdf, page)


@pytest.mark.parametrize("field", ["records_rdf", "records_page"])
@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("http://hub.example.org/records/{uid}", "not an https URL"),
        ("https://hub.example.org", "not an https URL"),
        ("https://{uid}.example.org/", "not an https URL"),
        ("https://hub.example.org/records/ {uid}", "not an https URL"),
        (42, "not an https URL"),
        ("https://hub.example.org/records/", "without {uid}"),
        ("https://hub.example.org/{segment}/", "without {uid}"),
        ("https://hub.example.org/{prefix}/{uid}", "placeholder other than"),
        ("https://hub.example.org/{UID}", "placeholder other than"),
        ("https://hub.example.org/{uid", "placeholder other than"),
        ("https://hub.example.org/{{uid}}", "placeholder other than"),
    ],
)
def test_a_record_pattern_that_is_not_an_https_template_with_uid_is_refused(
    field: str, template: object, message: str
) -> None:
    document = _with_entry("1002", **{field: template})
    assert _schema_errors(document)
    with pytest.raises(ValueError, match=rf"1002 has a {field} .*{re.escape(message)}"):
        namespace._load_prefix_register(document)


@pytest.mark.parametrize("field", ["records_rdf", "records_page"])
def test_a_prefix_that_holds_definitions_only_has_no_record_patterns(field: str) -> None:
    document = _with_entry("1000", **{field: "https://hub.example.org/records/{uid}"})
    assert _schema_errors(document)
    with pytest.raises(ValueError, match="1000 holds definitions only"):
        namespace._load_prefix_register(document)


@pytest.mark.parametrize("field", ["records_rdf", "records_page"])
def test_the_battery_genome_prefix_has_no_record_patterns(field: str) -> None:
    """The registry serves the records minted under 1001 itself."""
    document = _with_entry("1001", **{field: "https://hub.example.org/records/{uid}"})
    assert _schema_errors(document)
    with pytest.raises(ValueError, match="serves its records itself"):
        namespace._load_prefix_register(document)


# ── Definitions only ────────────────────────────────────────────────────────


def test_1000_holds_definitions_only() -> None:
    assert publisher_prefix("1000") is not None and publisher_prefix("1000").records is False
    assert namespace._DEFINITIONS_ONLY_PREFIXES == {
        prefix for prefix, entry in PUBLISHER_PREFIXES.items() if not entry.records
    }
    assert namespace._DEFINITIONS_ONLY_PREFIXES == {"1000"}


def test_no_record_is_minted_under_a_prefix_with_records_false() -> None:
    for prefix, entry in PUBLISHER_PREFIXES.items():
        if entry.records:
            assert record_iri("cell", UID, prefix) == f"https://w3id.org/battinfo/id/{prefix}/cell/{UID}"
        else:
            with pytest.raises(ValueError, match="definitions only"):
                record_iri("cell", UID, prefix)


# ── A number nobody holds ───────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["1003", "9999", "12345"])
def test_an_unknown_prefix_has_no_entry_but_still_builds_and_parses(prefix: str) -> None:
    """Whether a publisher holds a prefix is the registry's question; the SDK builds and reads any number."""
    assert publisher_prefix(prefix) is None
    iri = record_iri("cell", UID, prefix)
    assert iri == f"https://w3id.org/battinfo/id/{prefix}/cell/{UID}"
    assert parse_record_iri(iri) == namespace.RecordIri(prefix, "cell", UID)


@pytest.mark.parametrize("value", ["1001 ", "01001", 1001, None])
def test_publisher_prefix_takes_the_number_as_written_in_the_register(value: Any) -> None:
    assert publisher_prefix(value) is None


# ── A malformed register fails to load ──────────────────────────────────────


def _register(**changes: Any) -> dict[str, Any]:
    return _with_entry("1001", **changes)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (_register(prefix="1002"), "in sequence"),
        (_register(prefix="1000"), "in sequence"),
        (_register(prefix="10000"), "in sequence"),
        (_register(prefix="0999"), "four or more digits"),
        (_register(prefix="999"), "four or more digits"),
        (_register(prefix=1001), "four or more digits"),
        (_register(holder=""), "holder"),
        (_register(records="yes"), "records"),
        (_register(records_rdf="http://example.org/{uid}"), "https"),
        (_register(extra=1), "fields"),
    ],
)
def test_a_malformed_register_is_refused(document: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        namespace._load_prefix_register(document)


def test_a_five_digit_prefix_follows_9999() -> None:
    """Numbers carry on past four digits: 10000 is the one after 9999."""
    document = {"prefixes": [_entry(str(number)) for number in range(1000, 10001)]}
    assert not _schema_errors(document)
    register = namespace._load_prefix_register(document)
    assert list(register)[-2:] == ["9999", "10000"]
