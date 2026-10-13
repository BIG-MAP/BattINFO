"""Phase 1+2 regression tests for ws.submit(): staged-by-default + fail-closed/observable.

Pins the curated-index submission contract:
- submissions are STAGED by default (publication_intent.mode = staged-publication);
  an explicit publication_mode flips to immediate (canonical-publication);
- a per-record failure is surfaced (SubmitError), never swallowed into a misleading
  shorter list; "all failed" is distinguishable from "no records";
- a corrupt/unreadable record fails the batch CLOSED before any network call (R-2);
- an unknown only= token is rejected loudly (A-2);
- submit() without a save this session refuses to publish leftovers (R-9).

All offline: the registry is mocked at battinfo.api.submit_publication_package.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import quantity  # noqa: E402
from battinfo.ws import (  # noqa: E402
    CANONICAL_PUBLICATION_MODE,
    STAGED_PUBLICATION_MODE,
    AuthoringWorkspace,
    SubmitError,
)

_CREDS = dict(registry_url="https://registry.example", api_key="k", workspace_id="w", publisher_id="p")


# ── helpers ───────────────────────────────────────────────────────────────────


class _FakeRegistry:
    """Stand-in for api.submit_publication_package; records payloads, scripts results."""

    def __init__(self, behavior) -> None:
        self.behavior = behavior  # callable(payload) -> result dict, or raises
        self.payloads: list[dict] = []

    def __call__(self, payload, *, registry_base_url, api_key, **kw):
        self.payloads.append(copy.deepcopy(payload))
        return self.behavior(payload)

    @property
    def calls(self) -> int:
        return len(self.payloads)


def _result(status: str = "validated", iri: str = "iri-1") -> dict:
    return {
        "status": "ok",
        "url": "https://registry.example",
        "status_code": 200,
        "response": {"status": status, "resources": [{"canonical_iri": iri}]},
    }


def _author_specs(ws: AuthoringWorkspace, n: int) -> None:
    for i in range(n):
        ws._ws.cell_spec(
            manufacturer="Acme",
            model=f"X{i}",
            format="coin",
            chemistry="Li-primary",
            specs={
                "nominal_voltage": quantity(3.0, "V"),
                "diameter": quantity(20.0, "mm"),
                "height": quantity(3.2, "mm"),
            },
            source_file=f"acme-x{i}.manual.json",
        )


def _saved_ws(tmp_path: Path, n: int = 1) -> AuthoringWorkspace:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_specs(ws, n)
    ws.save(validation_policy="strict")
    return ws


def _patch_registry(monkeypatch, behavior) -> _FakeRegistry:
    fake = _FakeRegistry(behavior)
    monkeypatch.setattr("battinfo.api.submit_publication_package", fake)
    return fake


# ── Phase 1: staged-by-default ────────────────────────────────────────────────


def test_submit_defaults_to_staged_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    outcomes = ws.submit(**_CREDS)
    assert fake.calls == 1
    assert fake.payloads[0]["publication_intent"]["mode"] == STAGED_PUBLICATION_MODE
    assert outcomes and outcomes[0]["status"] == "validated" and outcomes[0]["ok"]


def test_submit_immediate_mode_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("published"))
    ws.submit(publication_mode=CANONICAL_PUBLICATION_MODE, **_CREDS)
    assert fake.payloads[0]["publication_intent"]["mode"] == CANONICAL_PUBLICATION_MODE


# ── Phase 2: fail-closed & observable ─────────────────────────────────────────


def test_submit_raises_on_record_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)

    def boom(_p):
        raise RuntimeError("Registry submission failed with HTTP 422: invalid")

    _patch_registry(monkeypatch, boom)
    with pytest.raises(SubmitError) as exc_info:
        ws.submit(**_CREDS)
    assert exc_info.value.failed and len(exc_info.value.failed) == 1


def test_submit_allow_partial_returns_failures_without_raising(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=2)

    def half(payload):
        # Fail X0, stage X1 — keyed on the title in the payload.
        if payload.get("title", "").endswith("X0"):
            raise RuntimeError("HTTP 500: boom")
        return _result("validated")

    _patch_registry(monkeypatch, half)
    outcomes = ws.submit(allow_partial=True, **_CREDS)
    failed = [o for o in outcomes if not o["ok"]]
    staged = [o for o in outcomes if o["status"] == "validated"]
    assert len(failed) == 1 and len(staged) == 1  # no raise; both surfaced


def test_submit_all_failed_is_distinct_from_no_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # All-failed raises (loud), whereas an empty workspace returns [] (quiet no-op).
    ws = _saved_ws(tmp_path)
    _patch_registry(monkeypatch, lambda p: (_ for _ in ()).throw(RuntimeError("HTTP 503")))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)

    empty = AuthoringWorkspace(root=tmp_path / "empty", registry_url=None)
    (empty._ws.source_root).mkdir(parents=True, exist_ok=True)
    assert empty.submit(**_CREDS) == []


def test_submit_fails_closed_on_corrupt_record_before_any_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _saved_ws(tmp_path, n=2)
    spec_files = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))
    assert len(spec_files) == 2
    spec_files[0].write_text("{ this is not valid json", encoding="utf-8")  # truncate one

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0  # aborted before submitting ANY record (incl. the good one)


def test_submit_fails_closed_on_corrupt_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # R-6: a corrupt NON-selected sibling (its relationships would be silently stripped from the
    # submitted graph) must fail closed, not publish a record with links quietly missing.
    ws = _saved_ws(tmp_path, n=1)
    ds_dir = ws._ws.source_root / "dataset"
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "corrupt.json").write_text("{ not valid json", encoding="utf-8")

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0


def test_submit_allow_partial_tolerates_corrupt_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=1)
    ds_dir = ws._ws.source_root / "dataset"
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "corrupt.json").write_text("{ not valid json", encoding="utf-8")

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(allow_partial=True, **_CREDS)  # explicit opt-in: proceed without that relationship
    assert fake.calls == 1


def test_submit_reads_bom_sibling_instead_of_dropping_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # R-10: a BOM-prefixed (Excel/Windows norm) but otherwise valid sibling must be read, not
    # treated as corrupt and dropped/aborted.
    ws = _saved_ws(tmp_path, n=1)
    ds_dir = ws._ws.source_root / "dataset"
    ds_dir.mkdir(parents=True, exist_ok=True)
    bom_json = chr(0xFEFF) + '{"dataset": {"id": "https://w3id.org/battinfo/dataset/x"}}'
    (ds_dir / "d.json").write_text(bom_json, encoding="utf-8")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)  # must NOT raise
    assert fake.calls == 1


def test_submit_rejects_unknown_only_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(ValueError):
        ws.submit(only="cellspec", **_CREDS)  # missing dash — must not silently match nothing
    with pytest.raises(ValueError):
        ws.submit(only=["cell-spec", "bogus"], **_CREDS)
    with pytest.raises(ValueError):
        ws.submit(only=123, **_CREDS)  # non-string scalar — clean ValueError, not raw TypeError
    with pytest.raises(ValueError):
        ws.submit(only={"cell-spec": 1}, **_CREDS)  # wrong-type container


def test_submit_without_save_refuses_leftovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _saved_ws(tmp_path)  # populates the examples dir on disk
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)  # no save this session
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        fresh.submit(**_CREDS)
    assert fake.calls == 0  # nothing submitted without an explicit opt-in
    # ... but submit_all=True is the explicit escape hatch.
    fresh.submit(submit_all=True, **_CREDS)
    assert fake.calls >= 1


# ── single-source-of-truth mode override + every record kind + publish() ──────


def _author_full_chain(ws: AuthoringWorkspace, tmp_path: Path) -> None:
    data_file = tmp_path / "inputs" / "cap.csv"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")
    spec = ws._ws.cell_spec(
        manufacturer="Acme",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        specs={"nominal_voltage": quantity(3.0, "V"), "diameter": quantity(20.0, "mm"), "height": quantity(3.2, "mm")},
        source_file="acme-cr2032.manual.json",
    )
    cell = ws._ws.cell(spec, serial_number="cr2032-001", source_type="lab")
    test = ws._ws.test(
        cell, kind="capacity_check", protocol="0.2 mA CC discharge", instrument="VSP-300", status="completed"
    )
    ws._ws.dataset(cell, title="cap", description="d", test=test, path=data_file, license="CC-BY-4.0")


def test_submit_stamps_staged_mode_on_all_record_kinds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_full_chain(ws, tmp_path)
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    # The chain's dataset is a local file; the mocked registry stands in for a test registry.
    ws.submit(allow_local_files=True, **_CREDS)
    assert fake.calls >= 4  # cell_spec, cell, test, dataset (+ test-spec)
    assert all(p["publication_intent"]["mode"] == STAGED_PUBLICATION_MODE for p in fake.payloads)
    assert {p["resource"]["resource_type"] for p in fake.payloads} >= {"cell_spec", "cell", "test", "dataset"}


def test_do_submit_overrides_publication_intent_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # _do_submit is the authoritative single source of truth for the mode: it
    # overrides whatever the builder already put in the payload.
    import battinfo.ws as ws_module

    captured: dict = {}

    def fake(payload, *, registry_base_url, api_key, **kw):
        captured["mode"] = payload["publication_intent"]["mode"]
        return _result("validated")

    monkeypatch.setattr("battinfo.api.submit_publication_package", fake)

    ws_module._do_submit(
        {"publication_intent": {"mode": "WRONG"}, "source_version": "v1", "resource": {"source_version": "v1"}},
        "https://r",
        "k",
        "T",
    )
    assert captured["mode"] == STAGED_PUBLICATION_MODE  # default flips WRONG -> staged
    ws_module._do_submit(
        {"publication_intent": {"mode": "WRONG"}, "source_version": "v1", "resource": {"source_version": "v1"}},
        "https://r",
        "k",
        "T",
        publication_mode=CANONICAL_PUBLICATION_MODE,
    )
    assert captured["mode"] == CANONICAL_PUBLICATION_MODE


def test_publish_defaults_to_staged_and_forwards_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://registry.example")
    monkeypatch.setenv("BATTINFO_API_KEY", "k")
    monkeypatch.setenv("BATTINFO_WORKSPACE_ID", "w")
    monkeypatch.setenv("BATTINFO_PUBLISHER_ID", "p")

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_specs(ws, 1)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.publish()  # save + submit, staged by default
    assert fake.payloads and fake.payloads[0]["publication_intent"]["mode"] == STAGED_PUBLICATION_MODE

    ws2 = AuthoringWorkspace(root=tmp_path / "two", registry_url=None)
    _author_specs(ws2, 1)
    fake2 = _patch_registry(monkeypatch, lambda p: _result("published"))
    ws2.publish(publication_mode=CANONICAL_PUBLICATION_MODE)
    assert fake2.payloads[0]["publication_intent"]["mode"] == CANONICAL_PUBLICATION_MODE


def test_submit_allow_partial_includes_unreadable_and_submits_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _saved_ws(tmp_path, n=2)
    spec_files = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))
    spec_files[0].write_text("{ broken", encoding="utf-8")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    outcomes = ws.submit(allow_partial=True, **_CREDS)
    assert len(outcomes) == 2
    assert sum(1 for o in outcomes if o["status"] == "unreadable") == 1
    assert fake.calls == 1  # the good record was still submitted despite the corrupt sibling


def test_submit_error_partitions_outcomes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=2)

    def half(payload):
        if payload.get("title", "").endswith("X0"):
            raise RuntimeError("HTTP 500")
        return _result("validated")

    _patch_registry(monkeypatch, half)
    with pytest.raises(SubmitError) as exc_info:
        ws.submit(**_CREDS)
    assert len(exc_info.value.outcomes) == 2
    assert len(exc_info.value.failed) == 1
    assert len(exc_info.value.submitted) == 1


# ── C-6: validate at submit (no validation lie) ───────────────────────────────


def test_submit_fails_closed_on_unrecognised_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))[0]
    spec_file.write_text('{"bogus": {}}', encoding="utf-8")  # valid JSON, not a known record type
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0  # blocked before any network call


def test_submit_fails_closed_on_invalid_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))[0]
    rec = json.loads(spec_file.read_text(encoding="utf-8"))
    rec["cell_spec"] = {"name": "broken"}  # recognised as a cell_spec, but missing required fields
    spec_file.write_text(json.dumps(rec), encoding="utf-8")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0  # an invalid record never reaches the registry


def test_submit_payload_carries_real_validation_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
    block = fake.payloads[0]["validation"]
    # The real verdict, not the builder's hardcoded {"ok": True, ..., "policy": "default"}.
    assert block["ok"] is True
    assert block["policy"] == "publisher"


@pytest.mark.parametrize("body", ["[1, 2, 3]", "5", "true", "null", '"hello"'])
def test_submit_fails_closed_on_non_object_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    # A hand-edited record that is valid JSON but NOT an object (array/number/bool/null/
    # string) must fail closed with a clean SubmitError, not crash submit() with a raw
    # TypeError from validate_record.
    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))[0]
    spec_file.write_text(body, encoding="utf-8")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0


# ── Resumable submit journal (3.5) ────────────────────────────────────────────


def test_successful_submit_writes_the_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=2)
    _patch_registry(monkeypatch, lambda p: _result("validated"))
    outcomes = ws.submit(**_CREDS)
    assert len(outcomes) == 2
    journal = tmp_path / ".battinfo" / "submit-journal.jsonl"
    assert journal.exists()
    lines = [ln for ln in journal.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2

    import json as _json

    entries = [_json.loads(ln) for ln in lines]
    assert all(e["ok"] and e["payload_hash"] and e["source_local_id"] for e in entries)


def test_rerun_skips_already_submitted_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=2)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
    assert fake.calls == 2

    again = ws.submit(**_CREDS)
    assert fake.calls == 2, "identical re-run must not re-POST anything"
    assert [o["status"] for o in again] == ["skipped_journal", "skipped_journal"]
    assert all(o["ok"] for o in again)


def test_resume_false_bypasses_the_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
    ws.submit(**_CREDS, resume=False)
    assert fake.calls == 2


def test_failed_outcomes_are_journaled_but_retried_on_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path, n=2)
    state = {"count": 0}

    def half(payload):
        state["count"] += 1
        if state["count"] == 2:
            raise RuntimeError("boom")
        return _result("validated")

    _patch_registry(monkeypatch, half)
    outcomes = ws.submit(**_CREDS, allow_partial=True)
    assert sum(1 for o in outcomes if o["ok"]) == 1

    # Resume: the successful record is skipped, the failed one is re-sent.
    _patch_registry(monkeypatch, lambda p: _result("validated"))
    resumed = ws.submit(**_CREDS)
    statuses = sorted(o["status"] for o in resumed)
    assert statuses == ["skipped_journal", "validated"]


def test_journal_counts_a_success_only_at_the_same_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Empa evaluation's E-10: a workspace rehearsed against one registry skipped
    every record as "already submitted" when pointed at another, because the journal
    did not record where a record went."""
    import json

    ws = _saved_ws(tmp_path, n=2)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**dict(_CREDS, registry_url="http://127.0.0.1:8012"))
    assert fake.calls == 2

    other = ws.submit(**dict(_CREDS, registry_url="http://localhost:8012"))
    assert fake.calls == 4, "a success at one registry must not count for another"
    assert [o["status"] for o in other] == ["validated", "validated"]

    # The first registry again, spelled differently: still the same registry.
    again = ws.submit(**dict(_CREDS, registry_url="HTTP://127.0.0.1:8012/"))
    assert fake.calls == 4
    assert [o["status"] for o in again] == ["skipped_journal", "skipped_journal"]

    journal = tmp_path / ".battinfo" / "submit-journal.jsonl"
    entries = [json.loads(ln) for ln in journal.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [e["registry_url"] for e in entries] == ["http://127.0.0.1:8012"] * 2 + ["http://localhost:8012"] * 2


def test_journal_entries_without_a_registry_match_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
    journal = tmp_path / ".battinfo" / "submit-journal.jsonl"
    entries = [json.loads(ln) for ln in journal.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for entry in entries:
        del entry["registry_url"]  # as journals were written before the registry was recorded
    journal.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")

    outcomes = ws.submit(**_CREDS)
    assert fake.calls == 2  # sent once more; the registry deduplicates identical payloads
    assert [o["status"] for o in outcomes] == ["validated"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://registry.example", "https://registry.example"),
        ("HTTPS://Registry.Example:443/", "https://registry.example"),
        ("http://localhost:80/api/v1/", "http://localhost/api/v1"),
        ("http://127.0.0.1:8012", "http://127.0.0.1:8012"),
        ("https://user:secret@registry.example/", "https://registry.example"),
        ("http://[::1]:8012/", "http://[::1]:8012"),
    ],
)
def test_journal_records_a_registry_url_in_one_spelling(url: str, expected: str) -> None:
    from battinfo.ws import _normalize_registry_url

    assert _normalize_registry_url(url) == expected


def test_changed_content_is_resubmitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)

    spec_file = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))[0]
    import json as _json

    doc = _json.loads(spec_file.read_text(encoding="utf-8"))
    doc["cell_spec"]["model"] = "X0-revised"
    spec_file.write_text(_json.dumps(doc), encoding="utf-8")

    outcomes = ws.submit(**_CREDS)
    assert fake.calls == 2, "changed content must be re-submitted"
    assert outcomes[0]["status"] == "validated"


# ── G11: equipment / channel / parameter-set reach the registry ───────────────
# ws.add("equipment", ...) writes records at add()-time; before this fix they
# were absent from the submit sweep AND from the session set, so an
# equipment-only workspace published nothing, silently.

_EQUIPMENT_SPEC_EXAMPLE = (
    ROOT / "src" / "battinfo" / "data" / "examples" / "equipment-spec" / "rchb-csx8-3vp8-ekcs.json"
)


def test_add_equipment_then_submit_sends_spec_unit_and_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add(
        "equipment", spec=str(_EQUIPMENT_SPEC_EXAMPLE), serial_number="AA:BB:CC:DD:EE:FF", name="Bench unit", channels=2
    )
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    # No ws.save() call: the add()-written records themselves are the session.
    outcomes = ws.submit(**_CREDS)

    types = [p["resource"]["resource_type"] for p in fake.payloads]
    assert types == ["equipment_spec", "equipment", "channel", "channel"]
    assert all(o["ok"] for o in outcomes)

    eq_payload = fake.payloads[1]
    eq_links = eq_payload["resource"].get("related_resources") or []
    assert {ln["relationship"] for ln in eq_links} == {"instanceOf", "hasChannel"}
    channel_links = [ln for ln in eq_links if ln["relationship"] == "hasChannel"]
    assert len(channel_links) == 2
    assert all(ln["resource_type"] == "channel" for ln in channel_links)
    assert all(ln.get("title") for ln in channel_links), "channel labels ride as titles"

    for ch_payload in fake.payloads[2:]:
        ch_links = ch_payload["resource"].get("related_resources") or []
        assert [ln["relationship"] for ln in ch_links] == ["channelOf"]
        assert ch_links[0]["resource_type"] == "equipment"
        assert (
            ch_links[0]["canonical_iri"]
            == eq_payload["resource"]["semantic_payload"]["battinfo_records"]["equipment"]["equipment"]["id"]
        )


def test_only_equipment_filters_the_sweep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("equipment", spec=str(_EQUIPMENT_SPEC_EXAMPLE), serial_number="AA:BB:CC:DD:EE:FF", channels=1)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(only=["equipment_spec", "channel"], **_CREDS)
    assert [p["resource"]["resource_type"] for p in fake.payloads] == ["equipment_spec", "channel"]


# ws.add("equipment") writes its records at once, and ws.save() used to reset the
# session set to the files it wrote itself. A session that added a unit, a cell
# and a test on one of the unit's channels then sent the cell and the test, but
# not the unit, its spec or the channel the test points at.

_SESSION_RECORD_TYPES = ["equipment_spec", "equipment", "channel", "channel", "cell_spec", "cell", "test"]


def _author_equipment_cell_and_test(ws: AuthoringWorkspace) -> None:
    from battinfo import CellSpec

    ws.add(
        "equipment", spec=str(_EQUIPMENT_SPEC_EXAMPLE), serial_number="AA:BB:CC:DD:EE:FF", name="Bench unit", channels=2
    )
    spec = CellSpec(manufacturer="Acme", model="X-1", format="cylindrical", chemistry="Li-ion")
    ws.add("cell", spec=spec, serial_numbers=["CELL-001"])
    ws.add("test", type="cycling", cell="CELL-001", channel="Bench unit/CH2")


def _sent_iris(fake: _FakeRegistry) -> set[str | None]:
    from battinfo.entities import entity_id_from_doc

    return {
        entity_id_from_doc(record)
        for payload in fake.payloads
        for record in payload["resource"]["semantic_payload"]["battinfo_records"].values()
    }


def _saved_iris(ws: AuthoringWorkspace) -> set[str | None]:
    import json

    from battinfo.entities import entity_id_from_doc

    return {
        entity_id_from_doc(json.loads(path.read_text(encoding="utf-8"))) for path in ws._ws.source_root.glob("*/*.json")
    }


def test_save_then_submit_sends_the_equipment_records_add_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_equipment_cell_and_test(ws)
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    outcomes = ws.submit(**_CREDS)

    assert [p["resource"]["resource_type"] for p in fake.payloads] == _SESSION_RECORD_TYPES
    assert all(o["ok"] for o in outcomes)
    assert _sent_iris(fake) == _saved_iris(ws)
    test_record = fake.payloads[-1]["resource"]["semantic_payload"]["battinfo_records"]["test"]
    assert {test_record["test"]["equipment_id"], test_record["test"]["channel_id"]} <= _sent_iris(fake)


def test_a_second_save_keeps_the_equipment_records_in_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_equipment_cell_and_test(ws)
    ws.save(validation_policy="strict")
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    ws.submit(**_CREDS)

    assert [p["resource"]["resource_type"] for p in fake.payloads] == _SESSION_RECORD_TYPES


def _set_registry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://registry.example")
    monkeypatch.setenv("BATTINFO_API_KEY", "k")
    monkeypatch.setenv("BATTINFO_WORKSPACE_ID", "w")
    monkeypatch.setenv("BATTINFO_PUBLISHER_ID", "p")


def test_publish_sends_the_equipment_records_add_wrote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_registry_env(monkeypatch)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_equipment_cell_and_test(ws)
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    outcomes = ws.publish()

    assert [p["resource"]["resource_type"] for p in fake.payloads] == _SESSION_RECORD_TYPES
    assert all(o["ok"] for o in outcomes)
    assert _sent_iris(fake) == _saved_iris(ws)


def test_publish_of_an_equipment_only_session_sends_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # publish() saves first, and that save left nothing for submit() to select,
    # which then refused with "No records were saved in this session".
    _set_registry_env(monkeypatch)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add(
        "equipment", spec=str(_EQUIPMENT_SPEC_EXAMPLE), serial_number="AA:BB:CC:DD:EE:FF", name="Bench unit", channels=1
    )
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    ws.publish()

    assert [p["resource"]["resource_type"] for p in fake.payloads] == ["equipment_spec", "equipment", "channel"]


def test_clear_drops_equipment_records_from_the_next_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # After ws.clear() the unit belongs to an earlier session: it stays on disk,
    # and the next submit() leaves it out like any record an earlier session wrote.
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add(
        "equipment", spec=str(_EQUIPMENT_SPEC_EXAMPLE), serial_number="AA:BB:CC:DD:EE:FF", name="Bench unit", channels=1
    )
    ws.clear()
    _author_specs(ws, 1)
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    ws.submit(**_CREDS)

    assert [p["resource"]["resource_type"] for p in fake.payloads] == ["cell_spec"]


def test_unknown_only_token_lists_the_new_types(tmp_path: Path) -> None:
    ws = _saved_ws(tmp_path)
    with pytest.raises(ValueError, match="equipment-spec, equipment, channel, parameter-set"):
        ws.submit(only="gadget", **_CREDS)


def test_parameter_set_submits_with_about_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._ws.source_root / "cell-spec").glob("*.json"))[0]
    import json as _json

    spec_iri = _json.loads(spec_file.read_text(encoding="utf-8"))["cell_spec"]["id"]

    ws.add(
        "parameter_set",
        name="Acme fit v1",
        cell_spec_id=spec_iri,
        citation_doi="10.1000/example",
        default_provenance_class="fitted",
        claims=[{"parameter": "nominal_voltage", "quantity": {"value": 3.0, "unit": "V"}}],
    )
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))

    ws.submit(only="parameter_set", **_CREDS)

    assert [p["resource"]["resource_type"] for p in fake.payloads] == ["parameter_set"]
    links = fake.payloads[0]["resource"].get("related_resources") or []
    assert {(ln["relationship"], ln["resource_type"]) for ln in links} == {("about", "cell_spec")}
    assert links[0]["canonical_iri"] == spec_iri


def test_component_family_records_warn_instead_of_vanishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    ws = _saved_ws(tmp_path)
    sep_dir = ws._ws.source_root / "separator-spec"
    sep_dir.mkdir(parents=True, exist_ok=True)
    (sep_dir / "separator-spec-test.json").write_text("{}", encoding="utf-8")

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(submit_all=True, **_CREDS)

    out = capsys.readouterr().out
    assert "not submitted" in out and "separator-spec" in out
    assert all(p["resource"]["resource_type"] != "separator_spec" for p in fake.payloads)


# ── A collection (dcat:DatasetSeries) has no files of its own ─────────────────


def test_submit_sends_a_collection_without_an_empty_distributions_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dataset schema requires at least one entry when ``distributions`` is
    present. submit() used to send ``"distributions": []`` for every dataset with
    no measurement file, which is exactly what a collection is, so the registry
    gate rejected the one record the members point at."""
    import json

    from battinfo import Dataset, ProvenanceInfo
    from battinfo.validate.record import validate_record_report

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_full_chain(ws, tmp_path)
    ws.save(validation_policy="strict")

    collection = Dataset(
        id="https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd",
        name="Half-cell OCV collection",
        access_url="https://doi.org/10.5281/zenodo.20086298",
        additional_type=["DatasetSeries"],
        source=ProvenanceInfo(type="catalog", url="https://doi.org/10.5281/zenodo.20086298", retrieved_at=1755648000),
    ).to_record()
    assert "distributions" not in collection["dataset"]
    dataset_dir = next(p.parent for p in ws._session_paths if p.parent.name == "dataset")
    path = dataset_dir / "aaaa-bbbb-cccc-dddd.json"
    path.write_text(json.dumps(collection), encoding="utf-8")
    ws._session_paths.add(path)

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(allow_local_files=True, **_CREDS)  # the member's file is local; a test registry

    sent = [
        record
        for payload in fake.payloads
        if payload["resource"]["resource_type"] == "dataset"
        for record in payload["resource"]["semantic_payload"]["battinfo_records"].values()
    ]
    series = [r for r in sent if "DatasetSeries" in (r["dataset"].get("additional_type") or [])]
    assert len(series) == 1
    assert "distributions" not in series[0]["dataset"]
    assert validate_record_report(series[0]).ok
    # A dataset that does have a file still sends it.
    others = [r for r in sent if r is not series[0]]
    assert others and all(r["dataset"]["distributions"] for r in others)


def test_submit_sends_a_cell_spec_s_own_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cell spec's name is its registry title; manufacturer + model is only the fallback."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_specs(ws, 2)
    ws._ws.cell_specs[0].name = "Flores 2026 graphite AQ-1 cell spec"
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
    titles = sorted(payload["title"] for payload in fake.payloads)
    assert titles == ["Acme X1", "Flores 2026 graphite AQ-1 cell spec"]
