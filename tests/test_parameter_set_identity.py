"""Parameter-set identity after the move from spec/ to dataset/ (IDENTIFIER_POLICY 6.3).

Rules under test:
- one seed per flavour, minted in one place: a record saved without an id
  lands on the IRI the builder gives the same fields, for every packaged
  example and for a filled-in template;
- a save never overwrites a record of another kind that holds the same IRI.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import battinfo
from battinfo.api import (
    EXAMPLES_ROOT,
    create_parameter_set,
    save_dataset,
    save_parameter_set,
    template_parameter_set,
)
from battinfo.bundle import Dataset, ProvenanceInfo
from battinfo.entities import stable_uid

EXAMPLES = sorted((EXAMPLES_ROOT / "parameter-set").glob("parameter-set-*.json"))
CLAIM_BATCH_EXAMPLE = EXAMPLES_ROOT / "parameter-set" / "parameter-set-xm4e-fr60-10y6-ajqh.json"
PARAMETER_FILE_EXAMPLE = EXAMPLES_ROOT / "parameter-set" / "parameter-set-rnc6-edv8-m43x-ebnq.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _stripped(record: dict) -> dict:
    """The record with its minted identity removed, as a filled-in template has it."""
    out = copy.deepcopy(record)
    out["parameter_set"].pop("id")
    out["parameter_set"].pop("short_id", None)
    return out


def _legacy(path: Path) -> dict:
    """A packaged example as it was published under spec/ before 2026-10-11.

    Same body, with the IRI the seeds of the time gave it: "parameter-set:..."
    for a claim batch, "parameter-set-file:<parameters_sha256>" for a file.
    """
    record = _load(path)
    body = record["parameter_set"]
    if "parameters_sha256" in body:
        seed = f"parameter-set-file:{body['parameters_sha256']}"
    else:
        seed = f"parameter-set:{body['material_kind']}:{body['scope']}:{body['name'].strip().lower()}"
    uid = stable_uid(seed)
    body["id"] = f"https://w3id.org/battinfo/spec/{uid}"
    body["short_id"] = uid.replace("-", "")[:6]
    return record


# ── one seed per flavour ─────────────────────────────────────────────────────


def test_a_saved_template_lands_on_the_builders_iri(tmp_path: Path) -> None:
    template = template_parameter_set()
    body = template["parameter_set"]
    built = create_parameter_set(name=body["name"], material_kind=body["material_kind"], claims=body["claims"])
    saved = save_parameter_set(template, source_root=tmp_path)
    assert saved["id"] == built["parameter_set"]["id"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_a_packaged_example_saved_without_its_id_gets_it_back(path: Path, tmp_path: Path) -> None:
    record = _load(path)
    saved = save_parameter_set(_stripped(record), source_root=tmp_path)
    assert saved["id"] == record["parameter_set"]["id"]


def test_a_stripped_legacy_claim_batch_saved_with_supersedes_gets_a_new_uid(tmp_path: Path) -> None:
    legacy = _legacy(CLAIM_BATCH_EXAMPLE)
    old = legacy["parameter_set"]["id"]
    draft = _stripped(legacy)
    draft["parameter_set"]["supersedes"] = old
    saved = save_parameter_set(draft, source_root=tmp_path)
    assert saved["id"].startswith("https://w3id.org/battinfo/dataset/")
    assert saved["id"].rsplit("/", 1)[-1] != old.rsplit("/", 1)[-1]
    assert saved["id"] == _load(CLAIM_BATCH_EXAMPLE)["parameter_set"]["id"]


# ── a save never replaces a record of another kind ───────────────────────────


@pytest.mark.parametrize("mode,policy", [
    ("create_only", "error"), ("create_only", "return_existing"), ("upsert", "error"),
])
def test_a_parameter_set_never_overwrites_a_dataset_at_the_same_iri(
    tmp_path: Path, mode: str, policy: str
) -> None:
    dataset = Dataset(
        name="pOCV curves", access_url="https://example.org/data.parquet",
        source=ProvenanceInfo(type="measurement"),
    )
    saved = save_dataset(dataset, source_root=tmp_path)
    before = Path(saved["path"]).read_text(encoding="utf-8")
    clash = create_parameter_set(
        validate=False, id=saved["id"], name="Chen 2020 - graphite", material_kind="graphite",
        claims=_load(CLAIM_BATCH_EXAMPLE)["parameter_set"]["claims"],
    )
    with pytest.raises(ValueError, match="already the IRI of the dataset record") as excinfo:
        save_parameter_set(clash, source_root=tmp_path, mode=mode, duplicate_policy=policy)
    assert "parameter-set" in str(excinfo.value)
    assert Path(saved["path"]).read_text(encoding="utf-8") == before


def test_the_kind_check_holds_inside_a_bulk_session(tmp_path: Path) -> None:
    dataset = Dataset(
        name="pOCV curves", access_url="https://example.org/data.parquet",
        source=ProvenanceInfo(type="measurement"),
    )
    with battinfo.bulk_save_session(tmp_path):
        saved = save_dataset(dataset, source_root=tmp_path)
        clash = create_parameter_set(
            validate=False, id=saved["id"], name="Chen 2020 - graphite", material_kind="graphite",
            claims=_load(CLAIM_BATCH_EXAMPLE)["parameter_set"]["claims"],
        )
        with pytest.raises(ValueError, match="already the IRI of the dataset record"):
            save_parameter_set(clash, source_root=tmp_path, mode="upsert")
