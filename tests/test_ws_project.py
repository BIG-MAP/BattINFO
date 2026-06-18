"""Tests for workspace funding-project (grant) tagging — battinfo.ws.project().

Covers the ProjectRef model, the OpenAIRE response parser, and the
AuthoringWorkspace.project() set/get/refresh/clear flow.  All tests run offline:
the OpenAIRE resolver is monkeypatched so no real network calls are made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo.ws as wsmod  # noqa: E402
from battinfo.ws import (  # noqa: E402
    AuthoringWorkspace,
    ProjectRef,
    _is_eu_grant,
    _parse_openaire_project,
)

# A representative (deeply nested, polymorphic) OpenAIRE projects payload.
_OPENAIRE_PAYLOAD = {
    "response": {"results": {"result": [{"metadata": {"oaf:entity": {"oaf:project": {
        "code": {"$": "101103997"},
        "acronym": {"$": "DIGIBATT"},
        "title": {"$": "Digital Battery"},
        "fundingtree": {
            "funder": {"name": {"$": "European Commission"}, "shortname": {"$": "EC"}},
            "funding_level_0": {"name": {"$": "HORIZON.2.5"}},
        },
    }}}}]}}
}

_RESOLVED = {
    "name": "Digital Battery",
    "acronym": "DIGIBATT",
    "funder": "European Commission",
    "program": "HORIZON.2.5",
}


@pytest.fixture(autouse=True)
def _offline_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: resolver returns the canned DigiBatt metadata, no network."""
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))


# ── ProjectRef model ──────────────────────────────────────────────────────────

def test_eu_grant_heuristic() -> None:
    assert _is_eu_grant("101103997")   # 9-digit Horizon Europe
    assert _is_eu_grant("875126")      # 6-digit H2020
    assert not _is_eu_grant("123")     # too short
    assert not _is_eu_grant("ABC-42")  # not numeric


def test_default_iri_for_eu_grant() -> None:
    assert ProjectRef("101103997").default_iri() == "https://cordis.europa.eu/project/id/101103997"
    assert ProjectRef("NSF-2026").default_iri() is None


def test_funding_block_shape() -> None:
    block = ProjectRef("101103997", name="DigiBatt", funder="European Commission",
                       acronym="DIGIBATT", program="HORIZON.2.5").funding_block()
    assert block == {
        "type": "Grant",
        "identifier": "101103997",
        "id": "https://cordis.europa.eu/project/id/101103997",
        "name": "DigiBatt",
        "acronym": "DIGIBATT",
        "funder": {"type": "Organization", "name": "European Commission"},
        "program": "HORIZON.2.5",
    }


def test_funding_block_minimal_identifier_only() -> None:
    block = ProjectRef("NSF-2026").funding_block()
    assert block == {"type": "Grant", "identifier": "NSF-2026"}


def test_to_from_dict_roundtrip() -> None:
    ref = ProjectRef("101103997", name="DigiBatt", funder="EC", manual=["name"])
    assert ProjectRef.from_dict(ref.to_dict()) == ref


# ── OpenAIRE parser ───────────────────────────────────────────────────────────

def test_parse_openaire_project_nested() -> None:
    assert _parse_openaire_project(_OPENAIRE_PAYLOAD) == {
        "name": "Digital Battery",
        "acronym": "DIGIBATT",
        "funder": "European Commission",
        "program": "HORIZON.2.5",
    }


def test_parse_openaire_project_empty() -> None:
    assert _parse_openaire_project({}) == {}


# ── ws.project() set / get / persist ──────────────────────────────────────────

def test_set_project_resolves_and_persists(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    block = ws.project("101103997")
    assert block["name"] == "Digital Battery"
    assert block["id"] == "https://cordis.europa.eu/project/id/101103997"

    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text())
    assert state["project"]["identifier"] == "101103997"
    assert state["project"]["resolved"] is True


def test_project_reloads_from_disk(tmp_path: Path) -> None:
    AuthoringWorkspace(root=tmp_path, registry_url=None).project("101103997")
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert fresh._funding_block()["identifier"] == "101103997"
    assert fresh._funding_block()["name"] == "Digital Battery"


def test_getter_with_no_project_returns_none(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert ws.project() is None


def test_clear_removes_project(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.project("101103997")
    assert ws.project(clear=True) is None
    assert ws._funding_block() is None
    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text())
    assert "project" not in state


# ── manual overrides win and survive refresh ──────────────────────────────────

def test_manual_override_wins(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.project("101103997", name="My Custom Name")
    ref = ws._get_project()
    assert ref.name == "My Custom Name"
    assert ref.funder == "European Commission"  # non-overridden field still resolved
    assert "name" in ref.manual


def test_manual_override_survives_refresh(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.project("101103997", name="My Custom Name")
    ws.project(refresh=True)  # re-pull from OpenAIRE without re-passing name=
    assert ws._get_project().name == "My Custom Name"


# ── offline degradation ───────────────────────────────────────────────────────

def test_offline_resolution_keeps_bare_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: {})
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    block = ws.project("101103997")
    assert block == {
        "type": "Grant",
        "identifier": "101103997",
        "id": "https://cordis.europa.eu/project/id/101103997",
    }


# ── Phase 3: stamping funding onto saved records ──────────────────────────────

def _populate(ws: AuthoringWorkspace, tmp_path: Path) -> None:
    """Author a full cell-spec → cell → test → dataset chain on the workspace."""
    from battinfo import quantity

    data_file = tmp_path / "inputs" / "cap.csv"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")

    cell_spec = ws._ws.cell_spec(
        manufacturer="Energizer", model="CR2032", format="coin", chemistry="Li-primary",
        specs={"nominal_voltage": quantity(3.0, "V"), "diameter": quantity(20.0, "mm"),
               "height": quantity(3.2, "mm")},
        source_file="energizer-cr2032.manual.json",
    )
    cell = ws._ws.cell(cell_spec, serial_number="cr2032-001", source_type="lab")
    test = ws._ws.test(cell, kind="capacity_check", protocol="0.2 mA CC discharge",
                       instrument="Biologic VSP-300", status="completed")
    ws._ws.dataset(cell, title="CR2032 capacity", description="discharge summary",
                   test=test, path=data_file, license="CC-BY-4.0")


def _all_record_paths(records_root: Path) -> list[Path]:
    return [p for p in records_root.rglob("*.json") if "index" not in p.name]


def test_save_stamps_funding_on_every_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.project("101103997")
    ws.save(validation_policy="strict")

    records = _all_record_paths(ws._records_root)
    assert records, "expected record files to be written"
    expected = ws._funding_block()
    for p in records:
        rec = json.loads(p.read_text(encoding="utf-8"))
        assert rec.get("funding") == expected, f"{p.name} missing funding block"


def test_stamped_records_pass_strict_validation_on_resave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The decisive round-trip: a second save re-runs build_index(validate=True)
    # over the funding-stamped files; it must not raise schema errors.
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.project("101103997")
    ws.save(validation_policy="strict")
    result = ws.save(validation_policy="strict")
    assert result["index"]["failed"] == 0


def test_funding_backfills_records_saved_before_project_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.save(validation_policy="strict")  # saved with no project yet
    for p in _all_record_paths(ws._records_root):
        assert "funding" not in json.loads(p.read_text(encoding="utf-8"))

    ws.project("101103997")
    ws.save(validation_policy="strict")  # re-save back-fills
    for p in _all_record_paths(ws._records_root):
        assert json.loads(p.read_text(encoding="utf-8")).get("funding") == ws._funding_block()


def test_no_project_leaves_records_unstamped(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.save(validation_policy="strict")
    for p in _all_record_paths(ws._records_root):
        assert "funding" not in json.loads(p.read_text(encoding="utf-8"))


# ── Phase 4: funding → schema:funding/Grant in JSON-LD ────────────────────────

def test_funding_to_jsonld_shape() -> None:
    from battinfo.jsonld import funding_to_jsonld

    grant = funding_to_jsonld(ProjectRef("101103997", name="DigiBatt", acronym="DIGIBATT",
                                         funder="European Commission", program="HORIZON.2.5").funding_block())
    assert grant == {
        "@type": "schema:Grant",
        "@id": "https://cordis.europa.eu/project/id/101103997",
        "schema:identifier": "101103997",
        "schema:name": "DigiBatt",
        "schema:alternateName": "DIGIBATT",
        "schema:funder": {"@type": "schema:Organization", "schema:name": "European Commission"},
    }
    # program is intentionally not exported (no standard schema.org term)
    assert "HORIZON.2.5" not in json.dumps(grant)


def test_funding_to_jsonld_handles_none_and_minimal() -> None:
    from battinfo.jsonld import funding_to_jsonld

    assert funding_to_jsonld(None) is None
    assert funding_to_jsonld({"type": "Grant"}) is None  # nothing identifying
    assert funding_to_jsonld(ProjectRef("NSF-2026").funding_block()) == {
        "@type": "schema:Grant", "schema:identifier": "NSF-2026",
    }


def test_record_to_jsonld_emits_funding_for_every_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from battinfo.jsonld import record_to_jsonld

    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.project("101103997")
    ws.save(validation_policy="strict")

    type_by_dir = {"cell-spec": "cell-spec", "cell-instance": "cell-instance",
                   "test": "test", "dataset": "dataset"}
    seen = set()
    examples = ws._records_root / "examples"
    for subdir, rtype in type_by_dir.items():
        for p in sorted((examples / subdir).glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            node = record_to_jsonld(rec, rtype)
            grant = node.get("schema:funding")
            assert grant and grant["@type"] == "schema:Grant", f"{rtype} missing schema:funding"
            assert grant["schema:identifier"] == "101103997"
            seen.add(rtype)
    assert seen == set(type_by_dir.values())


def test_record_to_jsonld_without_funding_omits_it(
    tmp_path: Path
) -> None:
    from battinfo.jsonld import record_to_jsonld

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.save(validation_policy="strict")  # no project
    p = next((ws._records_root / "examples" / "dataset").glob("*.json"))
    node = record_to_jsonld(json.loads(p.read_text(encoding="utf-8")), "dataset")
    assert "schema:funding" not in node


def test_export_jsonld_and_ttl_carry_funding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.project("101103997")
    ws.save(validation_policy="strict")

    out = tmp_path / "rdf"
    ws.export("json-ld", output_dir=out)
    ds_ld = json.loads(next((out / "dataset").glob("*.jsonld")).read_text(encoding="utf-8"))
    assert ds_ld["schema:funding"]["schema:identifier"] == "101103997"

    # Turtle export round-trips through rdflib — proves the schema: context resolves
    # (a broken context would raise here, not silently drop the triples).
    ttl_paths = ws.export("ttl", output_dir=out)
    assert ttl_paths
    ttl = (out / "dataset" / next((out / "dataset").glob("*.ttl")).name).read_text(encoding="utf-8")
    assert "101103997" in ttl


def test_zenodo_graph_carries_funding_on_catalog_and_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wsmod, "_resolve_project_openaire", lambda ident, **k: dict(_RESOLVED))
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.project("101103997")
    ws.save(validation_policy="strict")

    doc = ws._build_zenodo_jsonld(
        zenodo_record_id=123, prereserved_doi="10.5281/zenodo.123",
        record_url="https://zenodo.org/records/123", data_filenames=[],
        title="DigiBatt cycling", description="Test deposit", creators=[{"name": "Ada Lovelace"}],
        license="CC-BY-4.0",
    )
    graph = doc["@graph"]
    catalog = next(n for n in graph if "schema:DataCatalog" in (n.get("@type") or []))
    member = next(n for n in graph if n.get("@type") and "schema:Dataset" in n["@type"]
                  and "schema:DataCatalog" not in n["@type"])
    assert catalog["schema:funding"]["schema:identifier"] == "101103997"
    assert member["schema:funding"]["schema:identifier"] == "101103997"
