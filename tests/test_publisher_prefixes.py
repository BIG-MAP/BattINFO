"""The publisher prefix register, ``src/battinfo/data/namespace/prefixes.json``.

Ruling decision 3 (BIG-MAP/BattINFO#476, #480): every minting authority holds
a four-digit number, given out in sequence from 1000. 1000 is BattINFO and
holds definitions only; 1001 is the Battery Genome registry. The namespace
module takes its prefix constants from the register.
"""

from __future__ import annotations

import copy
import json
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


def test_the_register_ships_with_the_package_and_loads() -> None:
    assert PUBLISHER_PREFIXES == {
        "1000": PublisherPrefix("1000", "BattINFO", False, None, date(2026, 10, 22)),
        "1001": PublisherPrefix("1001", "Battery Genome registry", True, None, date(2026, 10, 22)),
    }


def test_the_register_validates_against_its_schema() -> None:
    schema = _packaged("prefixes.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(_packaged("prefixes.json")), key=str)
    assert not errors, [error.message for error in errors]


def test_numbers_are_four_digits_unique_and_in_sequence_from_1000() -> None:
    prefixes = [entry["prefix"] for entry in _packaged("prefixes.json")["prefixes"]]
    assert prefixes == [str(number) for number in range(1000, 1000 + len(prefixes))]
    assert list(PUBLISHER_PREFIXES) == prefixes


def test_every_resolver_is_an_https_url_or_none() -> None:
    for entry in PUBLISHER_PREFIXES.values():
        assert entry.resolver is None or entry.resolver.startswith("https://"), entry


def test_the_prefix_constants_are_in_the_register() -> None:
    assert (namespace.BATTINFO_PREFIX, namespace.BATTERY_GENOME_PREFIX) == ("1000", "1001")
    assert PUBLISHER_PREFIXES[namespace.BATTINFO_PREFIX].records is False
    assert PUBLISHER_PREFIXES[namespace.BATTERY_GENOME_PREFIX].records is True
    assert namespace._OLD_FORM_PREFIX == namespace.BATTERY_GENOME_PREFIX


def test_an_allocation_date_that_is_not_text_is_refused() -> None:
    entry = {"prefix": "1000", "holder": "BattINFO", "records": False, "resolver": None, "allocated": 20261022}
    with pytest.raises(ValueError, match="allocation date"):
        namespace._load_prefix_register({"prefixes": [entry]})


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


@pytest.mark.parametrize("prefix", ["1002", "9999", "12345"])
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
    document = copy.deepcopy(_packaged("prefixes.json"))
    document["prefixes"][1].update(changes)
    return document


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (_register(prefix="1002"), "in sequence"),
        (_register(prefix="1000"), "in sequence"),
        (_register(prefix="0999"), "four-digit"),
        (_register(prefix=1001), "four-digit"),
        (_register(holder=""), "holder"),
        (_register(records="yes"), "records"),
        (_register(resolver="http://example.org/"), "https"),
        (_register(extra=1), "fields"),
    ],
)
def test_a_malformed_register_is_refused(document: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        namespace._load_prefix_register(document)
