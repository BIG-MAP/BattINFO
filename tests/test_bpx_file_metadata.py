"""A BPX file's metadata is not part of a parameter file's identity.

A BPX file may carry two top-level keys beside its parameters, ``Metadata``
(licence, citation, the cell) and ``@context`` (a JSON-LD context for the
metadata). They describe the parameter set and are not part of
it (IDENTIFIER_POLICY 6.3), so:

- the fingerprint leaves them out, in ``bpx_content_digest`` and in a
  distribution entry alike, and everything else still counts, the Header
  included;
- no file the repository holds changes its fingerprint;
- the import neither lists them in ``not_imported`` nor reads them as claims;
- the official parser gets the file without them when it does not know them;
- a layout conversion never lowers the version a file declares;
- a record that battinfo 0.8.0 saved from such a file, under the fingerprint
  of the whole document, keeps its IRI when the same file is saved again.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo._bpx_layout import FILE_METADATA_KEYS, to_v1_layout, without_file_metadata  # noqa: E402
from battinfo._jcs import canonical_json_bytes  # noqa: E402
from battinfo.api import save_parameter_set, save_record  # noqa: E402
from battinfo.api._parameters import parameter_file_uid  # noqa: E402
from battinfo.interop import (  # noqa: E402
    bpx_content_digest,
    bpx_file_distribution,
    check_bpx,
    from_bpx_parameters,
    legacy_bpx_content_digest,
    upgrade_bpx,
)
from battinfo.interop.bpx import _parse_with_official_parser, to_bpx  # noqa: E402
from battinfo.namespace import parse_record_iri  # noqa: E402
from battinfo.validate import validate_record_report  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"
SOURCE_URL = "https://files.example.org/parameter_sets/x/source.bpx.json"
CONTEXT = "https://example.org/bpx/context.jsonld"
METADATA = {
    "Licence": "https://spdx.org/licenses/CC-BY-4.0.html",
    "Cell": {"Record": "https://w3id.org/battinfo/spec/0000-0000-0000-0000"},
    "Citation": "https://example.org/papers/1",
    "Derived from": "https://example.org/data/1",
}


def _plain() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _with_metadata() -> dict:
    return {"@context": CONTEXT, **_plain(), "Metadata": copy.deepcopy(METADATA)}


def _bytes(doc: dict) -> bytes:
    return (json.dumps(doc, indent=2) + "\n").encode("utf-8")


def _whole_document_digest(doc: dict) -> str:
    """The fingerprint as battinfo 0.8.0 computed it: over the whole document."""
    return hashlib.sha256(canonical_json_bytes(doc)).hexdigest()


# ── The fingerprint ──────────────────────────────────────────────────────────


def test_metadata_and_context_do_not_enter_the_fingerprint() -> None:
    plain, tagged = _plain(), _with_metadata()
    assert bpx_content_digest(tagged) == bpx_content_digest(plain)
    assert bpx_content_digest(_bytes(tagged)) == bpx_content_digest(plain)
    # Either key alone, and a changed or corrected Metadata, change nothing.
    assert bpx_content_digest({**plain, "Metadata": METADATA}) == bpx_content_digest(plain)
    assert bpx_content_digest({**plain, "@context": CONTEXT}) == bpx_content_digest(plain)
    corrected = _with_metadata()
    corrected["Metadata"]["Licence"] = "https://spdx.org/licenses/CC0-1.0.html"
    assert bpx_content_digest(corrected) == bpx_content_digest(plain)
    # The whole-document digest of 0.8.0 differs, which is why the lookup below exists.
    assert _whole_document_digest(tagged) != bpx_content_digest(tagged)


def test_a_distribution_entry_names_the_same_fingerprint() -> None:
    entry = bpx_file_distribution(_bytes(_with_metadata()), content_url=SOURCE_URL)
    assert entry.parameters_sha256 == bpx_content_digest(_plain())
    # The checksum is still that of the exact bytes.
    assert entry["checksum"]["value"] == hashlib.sha256(_bytes(_with_metadata())).hexdigest()


def test_everything_else_still_counts() -> None:
    base = bpx_content_digest(_plain())
    retitled = _with_metadata()
    retitled["Header"]["Title"] = retitled["Header"]["Title"] + "."
    assert bpx_content_digest(retitled) != base
    respelled = _with_metadata()
    respelled["Header"]["BPX"] = "1.0.0"
    assert bpx_content_digest(respelled) != base
    # Only the top level is metadata: a block key of the same name is a value.
    nested = _plain()
    nested["Parameterisation"].setdefault("User-defined", {})["Metadata"] = "a user-defined value"
    assert bpx_content_digest(nested) != base


def test_without_file_metadata_reads_the_top_level_only_and_copies() -> None:
    tagged = _with_metadata()
    out = without_file_metadata(tagged)
    assert set(FILE_METADATA_KEYS) == {"Metadata", "@context"}
    assert not set(FILE_METADATA_KEYS) & set(out)
    assert "Metadata" in tagged and "@context" in tagged  # the input is untouched
    with pytest.raises(ValueError, match="JSON object"):
        without_file_metadata([1, 2])  # type: ignore[arg-type]


# The BPX files the repository held at 0.8.0, with the fingerprint 0.8.0 gave each.
FILES_AT_0_8_0 = {
    "tests/fixtures/interop/bpx-dfn-full.bpx.json": "37f1c8a5ac35e5faf22a5297c0c1a8c871fa219750a597f68542666beafe27df",
    "tests/fixtures/interop/bpx-dfn-full.node.bpx.json": "37f1c8a5ac35e5faf22a5297c0c1a8c871fa219750a597f68542666beafe27df",
}


def test_no_file_the_repository_held_at_0_8_0_changes_its_fingerprint() -> None:
    # The change moves no IRI: none of them has the two keys, so each keeps
    # the fingerprint 0.8.0 gave it, which legacy_bpx_content_digest still gives.
    for relative, digest in FILES_AT_0_8_0.items():
        doc = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert not set(FILE_METADATA_KEYS) & set(doc), relative
        assert bpx_content_digest(doc) == digest == legacy_bpx_content_digest(doc), relative


def test_the_0_8_0_rule_stays_findable() -> None:
    tagged = _with_metadata()
    assert legacy_bpx_content_digest(tagged) == _whole_document_digest(tagged)
    assert legacy_bpx_content_digest(_bytes(tagged)) == _whole_document_digest(tagged)
    assert legacy_bpx_content_digest(tagged) != bpx_content_digest(tagged)


# ── Import and record ────────────────────────────────────────────────────────


def test_the_import_neither_reads_nor_lists_the_metadata() -> None:
    plain = from_bpx_parameters(_plain())
    tagged = from_bpx_parameters(_bytes(_with_metadata()))
    assert tagged.content_digest == plain.content_digest
    assert tagged.file_uid() == plain.file_uid()
    assert tagged.parts == plain.parts
    assert tagged.not_imported == plain.not_imported
    assert not {"Metadata", "@context"} & set(tagged.not_imported)
    assert any("Metadata describes the parameter set" in w for w in tagged.warnings)
    assert not any("@context" in w for w in tagged.warnings)


def test_a_record_of_a_tagged_file_has_the_plain_files_iri_and_validates() -> None:
    raw = _bytes(_with_metadata())
    record = from_bpx_parameters(raw).to_parameter_set(
        virtual_cell=True, distributions=[bpx_file_distribution(raw, content_url=SOURCE_URL)]
    )
    plain = from_bpx_parameters(FIXTURE).to_parameter_set(
        virtual_cell=True, distributions=[bpx_file_distribution(FIXTURE, content_url=SOURCE_URL)]
    )
    assert record["parameter_set"]["id"] == plain["parameter_set"]["id"]
    assert record["parameter_set"]["parameters_sha256"] == plain["parameter_set"]["parameters_sha256"]
    report = validate_record_report(record)
    assert report.ok, report.errors


# ── The official parser ──────────────────────────────────────────────────────


def test_check_bpx_passes_a_tagged_file_and_says_what_it_left_out() -> None:
    bpx = pytest.importorskip("bpx")
    doc = upgrade_bpx(FIXTURE).document
    assert check_bpx(doc)["passed"]
    tagged = {"@context": CONTEXT, **doc, "Metadata": METADATA}
    check = check_bpx(tagged)
    assert check["passed"], check["detail"]
    if "Metadata" not in {getattr(f, "alias", None) for f in bpx.BPX.model_fields.values()}:
        # The parser itself refuses the keys, so without the hand-off this fails.
        with pytest.raises(Exception, match="(?i)extra"):
            bpx.parse_bpx_obj(copy.deepcopy(tagged))
        assert "Checked without the file's top-level Metadata and @context" in check["detail"]
        assert "has to leave them out" in check["detail"]


def _stub_parser(tmp_path: Path, accepted: set[str]) -> tuple[types.SimpleNamespace, list[set[str]]]:
    seen: list[set[str]] = []
    fields = {key.lower(): types.SimpleNamespace(alias=key) for key in accepted}
    module_file = tmp_path / "bpx" / "__init__.py"
    module_file.parent.mkdir(exist_ok=True)
    module_file.write_text("", encoding="utf-8")
    stub = types.SimpleNamespace(
        __file__=str(module_file),
        BPX=types.SimpleNamespace(model_fields=fields),
        parse_bpx_obj=lambda obj: seen.append(set(obj)),
    )
    return stub, seen


def test_a_parser_that_knows_the_keys_gets_them(tmp_path: Path) -> None:
    # A later bpx that reads Metadata and @context checks them itself.
    tagged = {"@context": CONTEXT, "Header": {}, "Parameterisation": {}, "Metadata": METADATA}
    stub, seen = _stub_parser(tmp_path, {"Header", "Parameterisation", "Metadata", "@context"})
    passed, detail, _ = _parse_with_official_parser(tagged, stub)
    assert passed and seen == [{"@context", "Header", "Parameterisation", "Metadata"}]
    assert "Checked without" not in detail

    old, seen_old = _stub_parser(tmp_path, {"Header", "Parameterisation"})
    passed, detail, _ = _parse_with_official_parser(tagged, old)
    assert passed and seen_old == [{"Header", "Parameterisation"}]
    assert "Checked without the file's top-level Metadata and @context" in detail

    # A key the schema declares as a validation alias counts as known.
    aliased, seen_aliased = _stub_parser(tmp_path, {"Header", "Parameterisation"})
    aliased.BPX.model_fields["metadata"] = types.SimpleNamespace(alias=None, validation_alias="Metadata")
    _parse_with_official_parser(tagged, aliased)
    assert seen_aliased == [{"Header", "Parameterisation", "Metadata"}]

    # A schema the check cannot read: the keys are left out, to be safe.
    unknown, seen_unknown = _stub_parser(tmp_path, set())
    unknown.BPX = object()
    _parse_with_official_parser(tagged, unknown)
    assert seen_unknown == [{"Header", "Parameterisation"}]
    assert "Metadata" in tagged  # the caller's document is untouched


# ── Layout conversion ────────────────────────────────────────────────────────


def test_a_conversion_never_lowers_the_declared_version() -> None:
    # The fixture keeps the v0.x layout. Declared as 1.0 it is raised to 1.1.0,
    # as before; declared as 1.2.0 it keeps 1.2.0 (it used to come out as 1.1.0).
    as_1_0 = _plain()
    document, changes = to_v1_layout(as_1_0)
    assert document["Header"]["BPX"] == "1.1.0"
    assert any(change.startswith("Header.BPX") for change in changes)

    as_1_2 = _plain()
    as_1_2["Header"]["BPX"] = "1.2.0"
    document, changes = to_v1_layout(as_1_2)
    assert document["Header"]["BPX"] == "1.2.0"
    assert changes and not any(change.startswith("Header.BPX") for change in changes)
    upgraded = upgrade_bpx(as_1_2)
    assert (upgraded.source_version, upgraded.target_version) == ("1.2.0", "1.2.0")
    assert "as BPX 1.2.0" in upgraded.conversion_note("battinfo test")

    # Metadata rides through a conversion unchanged (dropping Record is Phase C).
    tagged = {**as_1_2, "Metadata": METADATA}
    assert to_v1_layout(tagged)[0]["Metadata"] == METADATA


def test_to_bpx_writes_the_version_asked_for() -> None:
    # A record of a v0.x-layout file that declares 1.2.0: exported as it
    # declares, it keeps 1.2.0; exported for a parser that reads 1.1.0, it says 1.1.0.
    source = _plain()
    source["Header"]["BPX"] = "1.2.0"
    record = from_bpx_parameters(source).to_parameter_set(virtual_cell=True)
    assert to_bpx(record).bpx["Header"]["BPX"] == "1.2.0"
    assert to_bpx(record, bpx_version="1.1.0").bpx["Header"]["BPX"] == "1.1.0"
    assert (
        to_bpx(from_bpx_parameters(FIXTURE).to_parameter_set(virtual_cell=True), bpx_version="1.1.0").bpx["Header"][
            "BPX"
        ]
        == "1.1.0"
    )


def test_a_runnable_copy_of_a_tagged_file_is_checked_by_its_parameters() -> None:
    raw = _bytes(_with_metadata())
    source = bpx_file_distribution(raw, content_url=SOURCE_URL)
    upgraded = upgrade_bpx(raw)
    assert upgraded.document["Metadata"] == METADATA  # the conversion keeps it
    for runnable_doc in (upgraded.document, without_file_metadata(upgraded.document)):
        runnable_bytes = _bytes(runnable_doc)
        runnable = bpx_file_distribution(
            runnable_bytes,
            name="runnable.bpx.json",
            content_url="https://files.example.org/parameter_sets/x/runnable.bpx.json",
            role="runnable",
            derived_from=source["checksum"]["value"],
            conversion=upgraded.conversion_note("battinfo test"),
        )
        record = from_bpx_parameters(raw).to_parameter_set(
            virtual_cell=True, distributions=[source, runnable], runnable_file=runnable_bytes
        )
        assert validate_record_report(record).ok


# ── A record 0.8.0 saved from a tagged file ──────────────────────────────────


@pytest.fixture
def battinfo_0_8_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Records built in the test say they were written by 0.8.1, the release that changes the rule."""
    import battinfo  # noqa: PLC0415

    monkeypatch.setattr(battinfo, "__version__", "0.8.1")


def _record_08x(raw: bytes, *, with_source: bool = True) -> dict:
    """The record battinfo 0.8.0 made from *raw*: fingerprint and IRI over the whole document."""
    distributions = [bpx_file_distribution(raw, content_url=SOURCE_URL)] if with_source else None
    record = from_bpx_parameters(raw).to_parameter_set(virtual_cell=True, distributions=distributions)
    body = record["parameter_set"]
    old_digest = legacy_bpx_content_digest(raw)
    uid = parameter_file_uid(old_digest)
    own = parse_record_iri(body["id"])
    body.update(id=body["id"].replace(own.uid, uid), short_id=uid.replace("-", "")[:6], parameters_sha256=old_digest)
    record["provenance"]["battinfo_version"] = "0.8.0"
    return record


def _record_now(raw: bytes, *, with_source: bool = True, **kwargs) -> dict:
    distributions = [bpx_file_distribution(raw, content_url=SOURCE_URL)] if with_source else None
    return from_bpx_parameters(raw).to_parameter_set(virtual_cell=True, distributions=distributions, **kwargs)


def _saved_ids(root: Path) -> list[str]:
    return sorted(json.loads(path.read_text(encoding="utf-8"))["parameter_set"]["id"] for path in root.rglob("*.json"))


@pytest.mark.usefixtures("battinfo_0_8_1")
def test_a_record_0_8_0_saved_keeps_its_iri_on_every_save(tmp_path: Path) -> None:
    raw = _bytes(_with_metadata())
    legacy = _record_08x(raw)
    legacy_iri = legacy["parameter_set"]["id"]
    assert validate_record_report(legacy).ok  # self-consistent: its IRI is its fingerprint's
    assert save_parameter_set(legacy, source_root=tmp_path)["id"] == legacy_iri

    record = _record_now(raw)
    assert record["parameter_set"]["id"] != legacy_iri
    again = save_parameter_set(copy.deepcopy(record), source_root=tmp_path, duplicate_policy="return_existing")
    assert (again["status"], again["id"]) == ("exists", legacy_iri)
    # An upsert writes the new build (stamped 0.8.1) over the saved record; the next one still finds it.
    for _ in range(2):
        assert save_parameter_set(copy.deepcopy(record), source_root=tmp_path, mode="upsert")["id"] == legacy_iri
    assert _saved_ids(tmp_path) == [legacy_iri]
    # The generic save path, which the CLI uses, does the same.
    assert save_record(copy.deepcopy(record), source_root=tmp_path, mode="upsert")["id"] == legacy_iri
    assert _saved_ids(tmp_path) == [legacy_iri]


def test_the_workspace_keeps_it_across_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import battinfo  # noqa: PLC0415

    raw = _bytes(_with_metadata())
    legacy = _record_08x(raw)
    legacy_iri = legacy["parameter_set"]["id"]
    monkeypatch.setattr(battinfo, "__version__", "0.8.0")
    first = battinfo.workspace(tmp_path, registry_url=None)
    first.add("parameter_set", record=legacy)
    first.save()

    monkeypatch.setattr(battinfo, "__version__", "0.8.1")
    second = battinfo.workspace(tmp_path, registry_url=None)
    second.add("parameter_set", record=_record_now(raw))
    second.save()
    second.save()
    saved = tmp_path / ".battinfo" / "records"
    assert _saved_ids(saved) == [legacy_iri]


@pytest.mark.usefixtures("battinfo_0_8_1")
def test_the_lookup_matches_the_source_bytes_only(tmp_path: Path) -> None:
    raw = _bytes(_with_metadata())
    # A folder without the 0.8.0 record: the new IRI.
    record = _record_now(raw)
    fresh = save_parameter_set(copy.deepcopy(record), source_root=tmp_path / "fresh")
    assert fresh["id"] == record["parameter_set"]["id"]

    # A 0.8.0 record of other bytes (another Metadata) is another file: no match.
    other = _with_metadata()
    other["Metadata"]["Licence"] = "https://spdx.org/licenses/CC0-1.0.html"
    save_parameter_set(_record_08x(_bytes(other)), source_root=tmp_path / "other")
    kept = save_parameter_set(copy.deepcopy(record), source_root=tmp_path / "other")
    assert kept["id"] == record["parameter_set"]["id"]

    # A 0.8.0 record saved into a folder that holds today's record keeps its own
    # IRI (an old record never takes a new one), and today's record keeps its.
    both = tmp_path / "both"
    save_parameter_set(copy.deepcopy(record), source_root=both)
    legacy = _record_08x(raw)
    kept_old = save_parameter_set(copy.deepcopy(legacy), source_root=both)
    assert kept_old["id"] == legacy["parameter_set"]["id"]
    again = save_parameter_set(copy.deepcopy(record), source_root=both, duplicate_policy="return_existing")
    assert again["id"] == record["parameter_set"]["id"]


@pytest.mark.usefixtures("battinfo_0_8_1")
def test_a_record_that_supersedes_the_saved_one_keeps_its_own_iri(tmp_path: Path) -> None:
    raw = _bytes(_with_metadata())
    legacy = _record_08x(raw)
    save_parameter_set(legacy, source_root=tmp_path)
    record = _record_now(raw, supersedes=legacy["parameter_set"]["id"])
    saved = save_parameter_set(copy.deepcopy(record), source_root=tmp_path)
    assert saved["id"] == record["parameter_set"]["id"] != legacy["parameter_set"]["id"]


@pytest.mark.usefixtures("battinfo_0_8_1")
def test_what_the_lookup_does_not_match(tmp_path: Path) -> None:
    # The limits IDENTIFIER_POLICY 6.3 states: a 0.8.0 record without a source
    # entry, and a copy of the file in other bytes, get the new IRI beside it.
    raw = _bytes(_with_metadata())
    bare = tmp_path / "bare"
    save_parameter_set(_record_08x(raw, with_source=False), source_root=bare)
    record = _record_now(raw, with_source=False)
    assert save_parameter_set(copy.deepcopy(record), source_root=bare)["id"] == record["parameter_set"]["id"]

    crlf = tmp_path / "crlf"
    save_parameter_set(_record_08x(raw), source_root=crlf)
    other_bytes = raw.replace(b"\n", b"\r\n")
    copy_record = _record_now(other_bytes)
    assert save_parameter_set(copy.deepcopy(copy_record), source_root=crlf)["id"] == copy_record["parameter_set"]["id"]
    # The 0.8.0 IRI is still findable from the file.
    assert any(parameter_file_uid(legacy_bpx_content_digest(other_bytes)) in iri for iri in _saved_ids(crlf))


def test_no_match_while_the_version_says_0_8_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Until __version__ says 0.8.1 (the release bump), a new record is not known
    # to carry the new fingerprint, so the lookup is off and the save mints the
    # new IRI beside the 0.8.0 record.
    import battinfo  # noqa: PLC0415

    monkeypatch.setattr(battinfo, "__version__", "0.8.0")
    raw = _bytes(_with_metadata())
    save_parameter_set(_record_08x(raw), source_root=tmp_path)
    record = _record_now(raw)
    assert record["provenance"]["battinfo_version"] == "0.8.0"
    saved = save_parameter_set(copy.deepcopy(record), source_root=tmp_path)
    assert saved["id"] == record["parameter_set"]["id"]
