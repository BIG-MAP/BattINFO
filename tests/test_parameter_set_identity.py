"""Parameter-set identity after the move from spec/ to dataset/ (IDENTIFIER_POLICY 6.3).

Rules under test:
- one seed per flavour, minted in one place: a record saved without an id
  lands on the IRI the builder gives the same fields, for every packaged
  example, the claim-batch fixture and a filled-in template;
- parameter sets minted under spec/ before 2026-10-11 stay readable: they
  validate with ``semantic.parameter_set_legacy_namespace`` (a warning, an
  error under the publisher policy), local lookups find them by their spec/
  IRI, and the builders never mint a new spec/ IRI;
- a uid is never reused: not by a record that supersedes itself, not by a
  dataset/ record that keeps the uid of the spec/ record it supersedes, nor
  by one that keeps the uid the seeds of before 2026-10-11 give its fields;
- the legacy warning names the dataset/ IRI the replacement mints;
- ws.zenodo() refuses what ws.submit() refuses, before contacting Zenodo;
- queries and collation return a replacement without the record it
  supersedes, so a migrated source is counted once;
- a lookup by IRI opens only the parameter-set file named by its uid;
- a save never overwrites a record of another kind that holds the same IRI;
- supersede_parameter_set() builds the dataset/ replacement of a legacy
  record from the current seeds.
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
    query_parameter_sets,
    save_dataset,
    save_parameter_set,
    supersede_parameter_set,
    template_parameter_set,
)
from battinfo.api._records import _find_record_path_by_id
from battinfo.bundle import Dataset, ProvenanceInfo
from battinfo.entities import stable_uid
from battinfo.validate import validate_record_report
from battinfo.validate.references import _find_record

EXAMPLES = sorted((EXAMPLES_ROOT / "parameter-set").glob("parameter-set-*.json"))
# A test fixture, not a packaged example: its claim values are not curated.
CLAIM_BATCH_FIXTURE = Path(__file__).parent / "fixtures" / "parameter-set" / "parameter-set-xm4e-fr60-10y6-ajqh.json"
PARAMETER_FILE_EXAMPLE = EXAMPLES_ROOT / "parameter-set" / "parameter-set-rnc6-edv8-m43x-ebnq.json"
LEGACY_CODE = "semantic.parameter_set_legacy_namespace"


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


def _moved(path: Path) -> dict:
    """The naive migration without supersedes: the spec/ record's uid under dataset/."""
    record = _legacy(path)
    body = record["parameter_set"]
    body["id"] = body["id"].replace("/spec/", "/dataset/")
    assert "supersedes" not in body
    return record


def _codes(report, severity: str) -> list[str]:
    return [issue.code for issue in report.issues if issue.severity == severity]


# ── one seed per flavour ─────────────────────────────────────────────────────


def test_a_saved_template_lands_on_the_builders_iri(tmp_path: Path) -> None:
    template = template_parameter_set()
    body = template["parameter_set"]
    built = create_parameter_set(name=body["name"], material_kind=body["material_kind"], claims=body["claims"])
    saved = save_parameter_set(template, source_root=tmp_path)
    assert saved["id"] == built["parameter_set"]["id"]


@pytest.mark.parametrize("path", [*EXAMPLES, CLAIM_BATCH_FIXTURE], ids=lambda p: p.stem)
def test_a_packaged_example_saved_without_its_id_gets_it_back(path: Path, tmp_path: Path) -> None:
    record = _load(path)
    saved = save_parameter_set(_stripped(record), source_root=tmp_path)
    assert saved["id"] == record["parameter_set"]["id"]


def test_a_stripped_legacy_claim_batch_saved_with_supersedes_gets_a_new_uid(tmp_path: Path) -> None:
    legacy = _legacy(CLAIM_BATCH_FIXTURE)
    old = legacy["parameter_set"]["id"]
    draft = _stripped(legacy)
    draft["parameter_set"]["supersedes"] = old
    saved = save_parameter_set(draft, source_root=tmp_path)
    assert saved["id"].startswith("https://w3id.org/battinfo/dataset/")
    assert saved["id"].rsplit("/", 1)[-1] != old.rsplit("/", 1)[-1]
    assert saved["id"] == _load(CLAIM_BATCH_FIXTURE)["parameter_set"]["id"]


# ── legacy spec/ ids are read, never minted ─────────────────────────────────


@pytest.mark.parametrize("path", [CLAIM_BATCH_FIXTURE, PARAMETER_FILE_EXAMPLE], ids=["claims", "file"])
@pytest.mark.parametrize("policy", ["default", "strict", "ingest"])
def test_a_legacy_record_validates_with_the_legacy_warning(path: Path, policy: str) -> None:
    # Exactly one issue more than the same record under its dataset/ IRI has.
    current = validate_record_report(_load(path), policy=policy)
    report = validate_record_report(_legacy(path), policy=policy)
    assert report.ok, report.errors
    assert sorted(_codes(report, "warning")) == sorted([*_codes(current, "warning"), LEGACY_CODE])
    message = next(issue.message for issue in report.issues if issue.code == LEGACY_CODE)
    assert "spec/" in message and "dataset/" in message and "supersede_parameter_set" in message
    assert _load(path)["parameter_set"]["id"] in message  # the IRI its replacement mints


@pytest.mark.parametrize("path", [CLAIM_BATCH_FIXTURE, PARAMETER_FILE_EXAMPLE], ids=["claims", "file"])
def test_a_legacy_record_is_refused_under_the_publisher_policy(path: Path) -> None:
    assert validate_record_report(_load(path), policy="publisher").ok
    report = validate_record_report(_legacy(path), policy="publisher")
    assert _codes(report, "error") == [LEGACY_CODE]


def test_a_legacy_parameter_file_stays_bound_to_its_fingerprint() -> None:
    # Its spec/ IRI is the one the seed of the time gives: no id mismatch.
    record = _legacy(PARAMETER_FILE_EXAMPLE)
    assert "semantic.parameter_file_id_mismatch" not in _codes(validate_record_report(record), "error")
    # Any other spec/ IRI is still a mismatch, under every policy.
    record["parameter_set"]["id"] = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
    record["parameter_set"]["short_id"] = "aaaabb"
    report = validate_record_report(record, policy="ingest")
    assert _codes(report, "error") == ["semantic.parameter_file_id_mismatch"]
    assert "parameter-set-file:" in report.errors[0].message


def test_an_id_in_neither_namespace_says_which_are_accepted() -> None:
    record = _load(CLAIM_BATCH_FIXTURE)
    record["parameter_set"]["id"] = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
    report = validate_record_report(record)
    error = next(issue for issue in report.errors if issue.path == "parameter_set.id")
    assert "dataset/" in error.message and "before 2026-10-11" in error.message


def test_the_builders_never_mint_under_spec() -> None:
    legacy = _legacy(CLAIM_BATCH_FIXTURE)["parameter_set"]
    with pytest.raises(ValueError, match=r"IDENTIFIER_POLICY 6\.3.*supersede_parameter_set"):
        create_parameter_set(
            id=legacy["id"], name=legacy["name"], material_kind="graphite", claims=legacy["claims"]
        )
    from battinfo.interop import from_bpx_parameters

    fixture = Path(__file__).resolve().parent / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
    result = from_bpx_parameters(fixture)
    spec_id = f"https://w3id.org/battinfo/spec/{stable_uid('parameter-set-file:' + result.content_digest)}"
    with pytest.raises(ValueError, match=r"IDENTIFIER_POLICY 6\.3"):
        result.to_parameter_set(virtual_cell=True, id=spec_id)


def test_a_legacy_record_is_found_by_its_spec_iri(tmp_path: Path) -> None:
    legacy = _legacy(CLAIM_BATCH_FIXTURE)
    saved = save_parameter_set(legacy, source_root=tmp_path)
    assert saved["status"] == "created"
    path = _find_record_path_by_id(legacy["parameter_set"]["id"], tmp_path)
    assert path is not None and Path(saved["path"]) == path
    # A re-save finds it, so it updates in place rather than writing a second file.
    again = save_parameter_set(legacy, source_root=tmp_path, mode="upsert")
    assert again["status"] == "updated" and again["path"] == saved["path"]
    # The reference validator's lookup finds it too, as a parameter set.
    assert _find_record(legacy["parameter_set"]["id"], tmp_path) == (path, "parameter-set")
    # Under the bulk-save cache as well.
    with battinfo.bulk_save_session(tmp_path):
        assert _find_record_path_by_id(legacy["parameter_set"]["id"], tmp_path) == path


def test_a_lookup_opens_only_the_parameter_set_file_named_by_the_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Parameter sets are searched under dataset/ and spec/; a miss in either
    # used to JSON-load every parameter-set file in the folder.
    import battinfo.api._records as records_module
    import battinfo.validate.references as references_module

    current = Path(save_parameter_set(_load(CLAIM_BATCH_FIXTURE), source_root=tmp_path)["path"])
    legacy = _legacy(PARAMETER_FILE_EXAMPLE)
    save_parameter_set(legacy, source_root=tmp_path)
    opened: list[Path] = []
    for module in (records_module, references_module):
        monkeypatch.setattr(
            module, "_load_json", lambda path, load=module._load_json: opened.append(Path(path)) or load(path)
        )

    for missing in ("spec", "dataset"):
        iri = f"https://w3id.org/battinfo/{missing}/aaaa-bbbb-cccc-dddd"
        assert _find_record_path_by_id(iri, tmp_path) is None
        assert _find_record(iri, tmp_path) is None
    assert not [path for path in opened if path.parent.name == "parameter-set"]

    assert _find_record_path_by_id(_load(CLAIM_BATCH_FIXTURE)["parameter_set"]["id"], tmp_path) == current
    assert _find_record(legacy["parameter_set"]["id"], tmp_path) is not None
    assert [path.name for path in opened if path.parent.name == "parameter-set"] == [
        current.name, f"parameter-set-{legacy['parameter_set']['id'].rsplit('/', 1)[-1]}.json",
    ]


def _migrated(tmp_path: Path) -> tuple[dict, dict]:
    """A legacy claim batch and its dataset/ replacement, both saved, as after a migration."""
    legacy = _legacy(CLAIM_BATCH_FIXTURE)
    save_parameter_set(legacy, source_root=tmp_path)
    replacement = _stripped(legacy)
    replacement["parameter_set"]["supersedes"] = legacy["parameter_set"]["id"]
    saved = save_parameter_set(replacement, source_root=tmp_path)
    return legacy, _load(Path(saved["path"]))


def test_query_parameter_sets_marks_legacy_rows(tmp_path: Path) -> None:
    legacy, replacement = _migrated(tmp_path)
    rows = {row["id"]: row for row in query_parameter_sets(source_root=tmp_path, include_superseded=True)}
    assert len(rows) == 2
    assert rows[legacy["parameter_set"]["id"]]["minted_under_spec"] is True
    assert rows[replacement["parameter_set"]["id"]]["minted_under_spec"] is False


def test_query_parameter_sets_leaves_out_a_record_its_replacement_supersedes(tmp_path: Path) -> None:
    legacy, replacement = _migrated(tmp_path)
    for filters in ({}, {"material_kind": "graphite"}, {"parameter": "particle_radius"}):
        rows = query_parameter_sets(source_root=tmp_path, **filters)
        assert [row["id"] for row in rows] == [replacement["parameter_set"]["id"]], filters
    # Only a replacement in the same result counts: a search that finds the
    # legacy record alone still returns it.
    rows = query_parameter_sets(source_root=tmp_path, id=legacy["parameter_set"]["id"])
    assert [row["id"] for row in rows] == [legacy["parameter_set"]["id"]]


def test_collation_counts_a_migrated_source_once(tmp_path: Path) -> None:
    from battinfo.parameters import collate_claims

    legacy, replacement = _migrated(tmp_path)
    claim_count = len(legacy["parameter_set"]["claims"])

    def _count(collated: dict) -> int:
        return sum(len(claims) for claims in collated.values())

    rows = query_parameter_sets(source_root=tmp_path, material_kind="graphite")
    collated = collate_claims([row["record"] for row in rows])
    assert _count(collated) == claim_count
    assert {claim["source"]["parameter_set_id"] for claims in collated.values() for claim in claims} == {
        replacement["parameter_set"]["id"]
    }
    # collate_claims applies the same rule to the records it is given.
    assert _count(collate_claims([legacy, replacement])) == claim_count
    assert _count(collate_claims([legacy, replacement], include_superseded=True)) == 2 * claim_count


def test_a_workspace_saves_a_legacy_record_and_refuses_to_submit_it(tmp_path: Path) -> None:
    from battinfo.ws import SubmitError

    ws = battinfo.workspace(str(tmp_path / "ws"), registry_url=None)
    ws.license("cc-by-4.0")
    ws.add("parameter_set", record=_legacy(CLAIM_BATCH_FIXTURE))
    ws.save()
    saved = sorted((tmp_path / "ws").rglob("parameter-set-*.json"))
    assert [p.name for p in saved] == ["parameter-set-8qqs-rh43-wt8d-172n.json"]
    with pytest.raises(SubmitError) as excinfo:
        ws.submit(
            registry_url="https://registry.example.org", api_key="placeholder",
            workspace_id="placeholder", publisher_id="placeholder",
        )
    assert "supersede_parameter_set" in excinfo.value.failed[0]["error"]


class _ZenodoReached(Exception):
    pass


def _no_zenodo(*args: object, **kwargs: object) -> None:
    raise _ZenodoReached


@pytest.mark.parametrize("record,code", [
    (_legacy(CLAIM_BATCH_FIXTURE), LEGACY_CODE),
    (_moved(CLAIM_BATCH_FIXTURE), "semantic.parameter_set_uid_reused"),
], ids=["spec-iri", "spec-uid-under-dataset"])
def test_ws_zenodo_refuses_a_parameter_set_ws_submit_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: dict, code: str
) -> None:
    # The Zenodo path ran only the publication JSON-LD checks, so it deposited a
    # spec/ parameter set without complaint. It now refuses before contacting Zenodo.
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", _no_zenodo)
    ws = battinfo.workspace(str(tmp_path / "ws"), registry_url=None)
    ws.license("cc-by-4.0")
    if code == LEGACY_CODE:
        ws.add("parameter_set", record=record)
        ws.save()
    else:
        # A save refuses it too, so it reaches the folder the way a hand-copied file does.
        path = ws._ws.source_root / "parameter-set" / "parameter-set-8qqs-rh43-wt8d-172n.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Refusing to deposit") as excinfo:
        ws.zenodo(token="placeholder")
    assert record["parameter_set"]["id"] in str(excinfo.value)
    assert "supersede_parameter_set" in str(excinfo.value)


def test_ws_zenodo_deposits_a_dataset_parameter_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", _no_zenodo)
    ws = battinfo.workspace(str(tmp_path / "ws"), registry_url=None)
    ws.license("cc-by-4.0")
    ws.add("parameter_set", record=_load(CLAIM_BATCH_FIXTURE))
    ws.save()
    with pytest.raises(_ZenodoReached):
        ws.zenodo(token="placeholder")


# ── a uid is never reused ────────────────────────────────────────────────────


@pytest.mark.parametrize("policy", ["default", "strict", "ingest", "publisher"])
def test_a_record_that_supersedes_itself_is_an_error_under_every_policy(policy: str) -> None:
    record = _load(CLAIM_BATCH_FIXTURE)
    record["parameter_set"]["supersedes"] = record["parameter_set"]["id"]
    assert "semantic.parameter_set_supersedes_itself" in _codes(
        validate_record_report(record, policy=policy), "error"
    )


@pytest.mark.parametrize("path", [CLAIM_BATCH_FIXTURE, PARAMETER_FILE_EXAMPLE], ids=["claims", "file"])
@pytest.mark.parametrize("policy", ["default", "strict", "ingest", "publisher"])
def test_keeping_the_uid_of_the_superseded_record_is_an_error_under_every_policy(
    path: Path, policy: str
) -> None:
    # The naive migration: spec/<uid> moved to dataset/<uid>, superseding itself.
    record = _legacy(path)
    old = record["parameter_set"]["id"]
    record["parameter_set"]["id"] = old.replace("/spec/", "/dataset/")
    record["parameter_set"]["supersedes"] = old
    assert "semantic.parameter_set_uid_reused" in _codes(validate_record_report(record, policy=policy), "error")


def test_the_builder_refuses_to_reuse_the_superseded_uid() -> None:
    legacy = _legacy(CLAIM_BATCH_FIXTURE)["parameter_set"]
    with pytest.raises(ValueError, match="never reused"):
        create_parameter_set(
            uid=legacy["id"].rsplit("/", 1)[-1], supersedes=legacy["id"],
            name=legacy["name"], material_kind="graphite", claims=legacy["claims"],
        )


@pytest.mark.parametrize("path", [CLAIM_BATCH_FIXTURE, PARAMETER_FILE_EXAMPLE], ids=["claims", "file"])
@pytest.mark.parametrize("policy", ["default", "strict", "ingest", "publisher"])
def test_a_dataset_record_that_keeps_its_spec_uid_is_an_error_under_every_policy(path: Path, policy: str) -> None:
    # Naming no supersedes does not make the uid free: the seeds of the time give it back.
    record = _moved(path)
    report = validate_record_report(record, policy=policy)
    assert "semantic.parameter_set_uid_reused" in _codes(report, "error")
    message = next(issue.message for issue in report.errors if issue.code == "semantic.parameter_set_uid_reused")
    assert _legacy(path)["parameter_set"]["id"] in message
    assert _load(path)["parameter_set"]["id"] in message  # where the record belongs


def test_the_chen_claim_batch_saved_under_its_spec_uid_is_refused(tmp_path: Path) -> None:
    # The reproduction: the Chen 2020 graphite claim batch, saved as dataset/8qqs-rh43-wt8d-172n
    # without supersedes, passed the publisher policy.
    record = _moved(CLAIM_BATCH_FIXTURE)
    assert record["parameter_set"]["id"] == "https://w3id.org/battinfo/dataset/8qqs-rh43-wt8d-172n"
    assert record["parameter_set"]["name"] == "Chen 2020 - graphite"
    assert not validate_record_report(record, policy="publisher").ok
    with pytest.raises(ValueError, match="parameter_set_uid_reused|never reused"):
        save_parameter_set(record, source_root=tmp_path)
    assert not list(tmp_path.rglob("parameter-set-*.json"))


def test_the_builders_refuse_a_uid_minted_under_spec() -> None:
    legacy = _legacy(CLAIM_BATCH_FIXTURE)["parameter_set"]
    legacy_uid = legacy["id"].rsplit("/", 1)[-1]
    for pin in ({"uid": legacy_uid}, {"id": f"https://w3id.org/battinfo/dataset/{legacy_uid}"}):
        with pytest.raises(ValueError, match="never reused") as excinfo:
            create_parameter_set(name=legacy["name"], material_kind="graphite", claims=legacy["claims"], **pin)
        assert legacy["id"] in str(excinfo.value)
    from battinfo.interop import from_bpx_parameters

    fixture = Path(__file__).resolve().parent / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
    result = from_bpx_parameters(fixture)
    file_uid = stable_uid("parameter-set-file:" + result.content_digest)
    with pytest.raises(ValueError, match="never reused"):
        result.to_parameter_set(virtual_cell=True, id=f"https://w3id.org/battinfo/dataset/{file_uid}")


def test_the_legacy_warning_names_the_replacement_iri() -> None:
    # A production record: the Ai2020 graphite claim batch, published as
    # spec/27fw-rh2c-t82v-t96q and republished as dataset/3zge-ge5d-cdn7-vzfy.
    record = create_parameter_set(
        validate=False, name="Ai2020 (PyBaMM) - graphite", material_kind="graphite",
        claims=_load(CLAIM_BATCH_FIXTURE)["parameter_set"]["claims"],
    )
    record["parameter_set"]["id"] = "https://w3id.org/battinfo/spec/27fw-rh2c-t82v-t96q"
    record["parameter_set"]["short_id"] = "27fwrh"
    for policy in ("default", "publisher"):
        report = validate_record_report(record, policy=policy)
        message = next(issue.message for issue in report.issues if issue.code == LEGACY_CODE)
        assert "https://w3id.org/battinfo/dataset/3zge-ge5d-cdn7-vzfy" in message
    replacement = supersede_parameter_set(record)
    assert replacement["parameter_set"]["id"] == "https://w3id.org/battinfo/dataset/3zge-ge5d-cdn7-vzfy"


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
        claims=_load(CLAIM_BATCH_FIXTURE)["parameter_set"]["claims"],
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
            claims=_load(CLAIM_BATCH_FIXTURE)["parameter_set"]["claims"],
        )
        with pytest.raises(ValueError, match="already the IRI of the dataset record"):
            save_parameter_set(clash, source_root=tmp_path, mode="upsert")


# ── the migration helper ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [CLAIM_BATCH_FIXTURE, PARAMETER_FILE_EXAMPLE], ids=["claims", "file"])
def test_supersede_parameter_set_mints_the_replacement_from_the_current_seeds(path: Path) -> None:
    legacy = _legacy(path)
    replacement = supersede_parameter_set(legacy)
    current = _load(path)  # the packaged example is the record the current seeds give
    assert replacement["parameter_set"]["id"] == current["parameter_set"]["id"]
    assert replacement["parameter_set"]["short_id"] == current["parameter_set"]["short_id"]
    assert replacement["parameter_set"]["supersedes"] == legacy["parameter_set"]["id"]
    # Everything else is the legacy record's, unchanged.
    rest = {k: v for k, v in replacement["parameter_set"].items() if k not in ("id", "short_id", "supersedes")}
    assert rest == {k: v for k, v in legacy["parameter_set"].items() if k not in ("id", "short_id")}
    assert {k: v for k, v in replacement.items() if k != "parameter_set"} == {
        k: v for k, v in legacy.items() if k != "parameter_set"
    }
    assert validate_record_report(replacement, policy="publisher").ok
    assert LEGACY_CODE not in _codes(validate_record_report(replacement), "warning")
    assert legacy == _legacy(path), "the legacy record is not modified"


def test_supersede_parameter_set_refuses_a_record_already_under_dataset() -> None:
    with pytest.raises(ValueError, match="already under dataset/"):
        supersede_parameter_set(_load(CLAIM_BATCH_FIXTURE))
    with pytest.raises(TypeError, match="parameter-set record"):
        supersede_parameter_set({"dataset": {"id": "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"}})


@pytest.mark.parametrize("bad_parts", [3, 3.5, True, "parts"])
def test_a_non_list_parts_value_is_a_finding_not_a_crash(bad_parts) -> None:
    from battinfo.interop import from_bpx_parameters

    fixture = Path(__file__).parent / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
    record = from_bpx_parameters(fixture).to_parameter_set(
        virtual_cell=True, materials={"negative": "graphite", "positive": "nmc811"}
    )
    record["parameter_set"]["parts"] = bad_parts
    for policy in ("default", "publisher"):
        report = validate_record_report(record, policy=policy)
        assert not report.ok


# ── a save keeps the record its uid-named file holds ─────────────────────────


@pytest.mark.parametrize("mode", ["create_only", "upsert"])
def test_a_save_never_replaces_another_record_held_under_the_same_uid(tmp_path: Path, mode: str) -> None:
    # Files are named by uid alone. A dataset/ record that keeps a legacy
    # record's uid under an edited name (so the uid-reuse finding, which
    # recomputes the seed from the name, stays quiet) replaced the legacy file.
    legacy = _legacy(CLAIM_BATCH_FIXTURE)
    saved = save_parameter_set(legacy, source_root=tmp_path)
    before = Path(saved["path"]).read_text(encoding="utf-8")
    clash = _moved(CLAIM_BATCH_FIXTURE)
    clash["parameter_set"]["name"] = "Chen 2020 - graphite (copy)"
    with pytest.raises(ValueError, match="never reused across namespaces") as excinfo:
        save_parameter_set(clash, source_root=tmp_path, mode=mode)
    assert legacy["parameter_set"]["id"] in str(excinfo.value)
    assert "supersede_parameter_set" in str(excinfo.value)
    assert Path(saved["path"]).read_text(encoding="utf-8") == before


# ── the documented migration deposits ────────────────────────────────────────


def test_ws_zenodo_leaves_out_a_legacy_record_its_replacement_supersedes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", _no_zenodo)
    ws = battinfo.workspace(str(tmp_path / "ws"), registry_url=None)
    ws.license("cc-by-4.0")
    legacy = _legacy(CLAIM_BATCH_FIXTURE)
    ws.add("parameter_set", record=legacy)
    ws.save()
    replacement = supersede_parameter_set(legacy)
    ws.add("parameter_set", record=replacement)
    ws.save()
    old_iri, new_iri = legacy["parameter_set"]["id"], replacement["parameter_set"]["id"]
    capsys.readouterr()

    with pytest.raises(_ZenodoReached):
        ws.zenodo(token="placeholder")
    assert f"Leaving out {old_iri}" in capsys.readouterr().out

    preview = ws.preview_jsonld()
    out = capsys.readouterr().out
    assert f"Leaving out {old_iri}" in out
    assert "supersede_parameter_set" not in out
    ids = {node.get("@id") for node in json.loads(preview.read_text(encoding="utf-8"))["@graph"]}
    assert new_iri in ids
    assert old_iri not in ids


# ── an id of another shape is skipped, not a crash ───────────────────────────


@pytest.mark.parametrize("bad_id", [
    ["https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"], {"@id": "https://example.org/x"},
], ids=["list", "dict"])
def test_a_parameter_set_id_of_another_shape_does_not_break_a_query(tmp_path: Path, bad_id: object) -> None:
    from battinfo.parameters import collate_claims

    record = _load(CLAIM_BATCH_FIXTURE)
    record["parameter_set"]["id"] = bad_id
    claim_count = len(record["parameter_set"]["claims"])
    for include in (False, True):
        collated = collate_claims([record], include_superseded=include)
        assert sum(len(claims) for claims in collated.values()) == claim_count
    folder = tmp_path / "parameter-set"
    folder.mkdir()
    (folder / "parameter-set-bad.json").write_text(json.dumps(record), encoding="utf-8")
    for include in (False, True):
        assert len(query_parameter_sets(source_root=tmp_path, include_superseded=include)) == 1


# ── a deposit of parameter sets alone resolves what they point at ────────────


_SPECIFIC_CAPACITY = {
    "parameter": "specific_capacity", "quantity": {"value": 372.0, "unit": "mAh/g"},
    "provenance_class": "literature",
}
_NOMINAL_CAPACITY = {
    "parameter": "nominal_capacity", "quantity": {"value": 5.0, "unit": "Ah"},
    "provenance_class": "literature",
}
_MATERIAL_SPEC = "https://w3id.org/battinfo/spec/bbbb-cccc-dddd-eeee"
_CELL_SPEC = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
_CELL = "https://w3id.org/battinfo/cell/cccc-dddd-eeee-ffff"
_MATERIAL_SPEC_TYPE = ["Description", "schema:ProductModel", "schema:CreativeWork"]


def _parameter_file_about(**link: str) -> dict:
    record = _load(PARAMETER_FILE_EXAMPLE)
    body = record["parameter_set"]
    body.pop("virtual_cell")
    body.update(link)
    return record


def _part_with_material_spec() -> dict:
    record = _load(PARAMETER_FILE_EXAMPLE)
    record["parameter_set"]["parts"][0]["material_spec_id"] = _MATERIAL_SPEC
    return record


def _deposit(record_sets: dict[str, list[dict]]) -> tuple[dict, list[str]]:
    from battinfo.validate import validate_publication_report
    from battinfo.ws import AuthoringWorkspace

    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets, zenodo_record_id=1, prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1", data_filenames=[], title="Parameter sets",
        license="cc-by-4.0", creators=[{"name": "Doe, Jane"}],
    )
    report = validate_publication_report(doc, policy="publisher")
    return doc, [issue.code for issue in report.errors]


@pytest.mark.parametrize("record,target,stub_type", [
    (lambda: create_parameter_set(
        validate=False, name="A - graphite", material_spec_id=_MATERIAL_SPEC, claims=[_SPECIFIC_CAPACITY],
    ), _MATERIAL_SPEC, _MATERIAL_SPEC_TYPE),
    (lambda: create_parameter_set(
        validate=False, name="A - cell", cell_spec_id=_CELL_SPEC, claims=[_NOMINAL_CAPACITY],
    ), _CELL_SPEC, "BatteryCellSpecification"),
    (lambda: _parameter_file_about(cell_spec_id=_CELL_SPEC), _CELL_SPEC, "BatteryCellSpecification"),
    (lambda: _parameter_file_about(cell_instance_id=_CELL), _CELL, "BatteryCell"),
    (_part_with_material_spec, _MATERIAL_SPEC, _MATERIAL_SPEC_TYPE),
], ids=["claims-material-spec", "claims-cell-spec", "file-cell-spec", "file-cell", "file-part"])
def test_a_deposit_of_parameter_sets_alone_stubs_what_they_point_at(record, target: str, stub_type) -> None:
    doc, errors = _deposit({"parameter-set": [record()]})
    assert errors == []
    stubs = [node for node in doc["@graph"] if node.get("@id") == target]
    assert stubs == [{"@id": target, "@type": stub_type, "rdfs:isDefinedBy": {"@id": target}}]


def test_a_target_the_deposit_carries_gets_no_stub() -> None:
    material = _load(sorted((EXAMPLES_ROOT / "material-spec").glob("*.json"))[0])
    target = material["material_spec"]["id"]
    claim_batch = create_parameter_set(
        validate=False, name="A - graphite", material_spec_id=target, claims=[_SPECIFIC_CAPACITY],
    )
    doc, errors = _deposit({"material-spec": [material], "parameter-set": [claim_batch]})
    assert errors == []
    nodes = [node for node in doc["@graph"] if node.get("@id") == target]
    assert len(nodes) == 1
    assert "rdfs:isDefinedBy" not in nodes[0]
