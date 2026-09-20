"""Organizations as first-class records: authoring, validation, emission.

Closes the documented triple gap (no authoring API, no JSON-LD emitter, no
entities-registry kind) under the 0.8.0 core-features scope ruling. The
canonical keys are snake_case; the family's original camelCase spellings stay
accepted forever as deprecated aliases and normalize on round-trip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo.api as api  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.validate.record import validate_record  # noqa: E402


def test_id_is_deterministic_from_the_name() -> None:
    a = api.create_organization(name="A123 Systems")["organization"]["id"]
    b = api.create_organization(name="A123 Systems", type="Manufacturer")["organization"]["id"]
    c = api.create_organization(name="Celgard")["organization"]["id"]
    assert a == b != c
    assert a.startswith("https://w3id.org/battinfo/organization/")


def test_existing_random_minted_ids_are_kept() -> None:
    kept = api.create_organization(
        name="A123 Systems",
        id="https://w3id.org/battinfo/organization/8z6j-n7vw-e73w-smh7",
    )
    assert kept["organization"]["id"].endswith("8z6j-n7vw-e73w-smh7")


def test_camel_case_kwargs_normalize_to_canonical_keys() -> None:
    rec = api.create_organization(
        name="SINTEF", legalName="SINTEF AS", foundingDate="1950-01-01",
        location={"addressCountry": "NO", "addressLocality": "Trondheim"},
    )
    body = rec["organization"]
    assert body["legal_name"] == "SINTEF AS"
    assert body["founding_date"] == "1950-01-01"
    assert body["location"] == {"address_country": "NO", "address_locality": "Trondheim"}
    assert "legalName" not in body and "addressCountry" not in body["location"]


def test_conflicting_alias_and_canonical_kwargs_are_rejected() -> None:
    with pytest.raises(ValueError, match="legalName"):
        api.create_organization(name="X", legalName="A", legal_name="B")


def test_records_pass_the_entities_validation_path() -> None:
    # The registered kind routes organizations through validate_record like
    # every other family — previously they raised "Unsupported record type".
    for path in sorted((ROOT / "examples" / "organization").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = validate_record(doc)
        assert result.ok, (path.name, result.errors[:1])


def test_legacy_camel_case_record_normalizes_on_round_trip() -> None:
    from battinfo.canonical_aliases import record_to_snake_aliases

    legacy = {
        "schema_version": "0.2.0",
        "organization": {
            "id": "https://w3id.org/battinfo/organization/8z6j-n7vw-e73w-smh7",
            "name": "A123 Systems",
            "legalName": "A123 Systems LLC",
            "alternateName": ["A123"],
            "location": {"addressCountry": "US", "addressRegion": "Massachusetts"},
        },
        "provenance": {"source_type": "manual", "retrieved_at": 1750000000},
    }
    assert validate_record(legacy).ok  # accepted forever
    normalized = record_to_snake_aliases(legacy)["organization"]
    assert normalized["legal_name"] == "A123 Systems LLC"
    assert normalized["alternate_name"] == ["A123"]
    assert normalized["location"] == {"address_country": "US", "address_region": "Massachusetts"}


def test_emission_is_pure_schema_org() -> None:
    rec = api.create_organization(
        name="EMPA", type="ResearchOrganization",
        url="https://www.empa.ch",
        same_as="https://ror.org/02x681a42",
        parent_organization={"name": "ETH Domain"},
    )
    ld = record_to_jsonld(rec, "organization")
    assert ld["@context"] == "https://w3id.org/battinfo/context/records/v1.json"
    # ResearchOrganization IS a schema.org class, so it stacks as a type.
    assert ld["@type"] == ["schema:Organization", "schema:ResearchOrganization"]
    assert ld["schema:sameAs"] == {"@id": "https://ror.org/02x681a42"}
    assert ld["schema:parentOrganization"]["schema:name"] == "ETH Domain"
    # No EMMO terms and nothing minted: every key is @-, schema:-, dcterms:-,
    # or prov:-prefixed.
    for key in ld:
        assert key.startswith(("@", "schema:", "dcterms:", "prov:")), key


def test_manufacturer_type_stays_data_not_a_type() -> None:
    ld = record_to_jsonld(api.create_organization(name="X Corp", type="Manufacturer"), "organization")
    assert ld["@type"] == "schema:Organization"
    assert ld["schema:additionalType"] == "Manufacturer"


def test_legacy_and_canonical_records_emit_identically() -> None:
    canonical = api.create_organization(
        name="A123 Systems", legal_name="A123 Systems LLC",
        id="https://w3id.org/battinfo/organization/8z6j-n7vw-e73w-smh7",
        retrieved_at=1750000000,
    )
    legacy = json.loads(json.dumps(canonical).replace("legal_name", "legalName"))
    assert record_to_jsonld(legacy, "organization") == record_to_jsonld(canonical, "organization")


def test_save_and_query_round_trip(tmp_path: Path) -> None:
    record = api.create_organization(name="Example Instruments", type="Manufacturer")
    api.save_organization(record, source_root=tmp_path)
    rows = api.query_organizations(source_root=tmp_path)
    assert [r["name"] for r in rows] == ["Example Instruments"]
    assert rows[0]["type"] == "Manufacturer"
    again = api.query_organizations(source_root=tmp_path, type="ResearchOrganization")
    assert again == []
