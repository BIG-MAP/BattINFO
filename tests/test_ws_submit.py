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


def test_submit_allow_partial_returns_failures_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_submit_all_failed_is_distinct_from_no_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # All-failed raises (loud), whereas an empty workspace returns [] (quiet no-op).
    ws = _saved_ws(tmp_path)
    _patch_registry(monkeypatch, lambda p: (_ for _ in ()).throw(RuntimeError("HTTP 503")))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)

    empty = AuthoringWorkspace(root=tmp_path / "empty", registry_url=None)
    (empty._records_root / "examples").mkdir(parents=True, exist_ok=True)
    assert empty.submit(**_CREDS) == []


def test_submit_fails_closed_on_corrupt_record_before_any_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _saved_ws(tmp_path, n=2)
    spec_files = sorted((ws._records_root / "examples" / "cell-spec").glob("*.json"))
    assert len(spec_files) == 2
    spec_files[0].write_text("{ this is not valid json", encoding="utf-8")  # truncate one

    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0  # aborted before submitting ANY record (incl. the good one)


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
        manufacturer="Acme", model="CR2032", format="coin", chemistry="Li-primary",
        specs={"nominal_voltage": quantity(3.0, "V"), "diameter": quantity(20.0, "mm"),
               "height": quantity(3.2, "mm")},
        source_file="acme-cr2032.manual.json",
    )
    cell = ws._ws.cell(spec, serial_number="cr2032-001", source_type="lab")
    test = ws._ws.test(cell, kind="capacity_check", protocol="0.2 mA CC discharge",
                       instrument="VSP-300", status="completed")
    ws._ws.dataset(cell, title="cap", description="d", test=test, path=data_file, license="CC-BY-4.0")


def test_submit_stamps_staged_mode_on_all_record_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _author_full_chain(ws, tmp_path)
    ws.save(validation_policy="strict")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    ws.submit(**_CREDS)
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
        "https://r", "k", "T",
    )
    assert captured["mode"] == STAGED_PUBLICATION_MODE  # default flips WRONG -> staged
    ws_module._do_submit(
        {"publication_intent": {"mode": "WRONG"}, "source_version": "v1", "resource": {"source_version": "v1"}},
        "https://r", "k", "T", publication_mode=CANONICAL_PUBLICATION_MODE,
    )
    assert captured["mode"] == CANONICAL_PUBLICATION_MODE


def test_publish_defaults_to_staged_and_forwards_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    spec_files = sorted((ws._records_root / "examples" / "cell-spec").glob("*.json"))
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
    spec_file = sorted((ws._records_root / "examples" / "cell-spec").glob("*.json"))[0]
    spec_file.write_text('{"bogus": {}}', encoding="utf-8")  # valid JSON, not a known record type
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0  # blocked before any network call


def test_submit_fails_closed_on_invalid_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._records_root / "examples" / "cell-spec").glob("*.json"))[0]
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
def test_submit_fails_closed_on_non_object_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    # A hand-edited record that is valid JSON but NOT an object (array/number/bool/null/
    # string) must fail closed with a clean SubmitError, not crash submit() with a raw
    # TypeError from validate_record.
    ws = _saved_ws(tmp_path)
    spec_file = sorted((ws._records_root / "examples" / "cell-spec").glob("*.json"))[0]
    spec_file.write_text(body, encoding="utf-8")
    fake = _patch_registry(monkeypatch, lambda p: _result("validated"))
    with pytest.raises(SubmitError):
        ws.submit(**_CREDS)
    assert fake.calls == 0
