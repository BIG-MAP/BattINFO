"""Guard: v1 is append-only from the v0.8.0 tag.

``tests/fixtures/context/records-v1-0.8.0.json`` holds every term of
``records.context.v1.json`` as BattINFO 0.8.0 ships it, with its full definition.
A document minted against v1 must keep expanding to the same graph, so each of
those terms keeps its definition (and with it its expanded IRI, ``@type`` and
``@container``) for good. Terms added after the snapshot are allowed.

``scripts/gen_context.py`` enforces the same rule when it writes v1: it refuses
an output that changes or drops a snapshot term, whether the change comes from a
hand edit of v1, from ``PRE_RELEASE_CORRECTIONS`` or from a source table. Before
the tag, ``gen_context.py --write-snapshot`` retakes the snapshot after the last
pre-release correction; once the tag exists it refuses.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
SNAPSHOT = ROOT / "tests" / "fixtures" / "context" / "records-v1-0.8.0.json"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_context", ROOT / "scripts" / "gen_context.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _v1_terms() -> dict:
    return json.loads(V1.read_text(encoding="utf-8"))["@context"]


@pytest.fixture
def gen(tmp_path, monkeypatch):
    """gen_context with v1 and the snapshot copied to *tmp_path*, so a test can change them."""
    module = _load_gen()
    out = tmp_path / "records.context.v1.json"
    snapshot = tmp_path / "records-v1-0.8.0.json"
    shutil.copyfile(V1, out)
    shutil.copyfile(SNAPSHOT, snapshot)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "SNAPSHOT", snapshot)
    monkeypatch.setattr(module, "release_tagged", lambda: False)
    return module


def _added_since_snapshot(gen) -> int:
    """Terms v1 holds beyond the snapshot, before a test changes anything.

    Between a merge that adds terms and the next retake of the snapshot, v1 runs ahead of it, so the
    counts below are taken relative to this.
    """
    return len(set(json.loads(gen.OUT.read_text(encoding="utf-8"))["@context"]) - set(_snapshot()["terms"]))


def _plain_frozen_term(gen) -> str:
    """A class or unit term of the snapshot that no correction rewrites, so an edit to it survives a build."""
    return next(
        term
        for term, value in _snapshot()["terms"].items()
        if isinstance(value, str)
        and not term.startswith("@")
        and not value.endswith(("#", "/"))  # a prefix
        and term not in gen.PRE_RELEASE_CORRECTIONS
    )


# --- the snapshot itself ----------------------------------------------------------


def test_snapshot_describes_the_v1_context_of_0_8_0() -> None:
    snapshot = _snapshot()
    assert snapshot["context"] == "https://w3id.org/battinfo/context/records/v1.json"
    assert snapshot["release"] == "0.8.0"
    assert isinstance(snapshot["terms"], dict) and len(snapshot["terms"]) > 600


def test_snapshot_terms_keep_their_definitions_in_v1() -> None:
    """Every 0.8.0 term is still in the bundled v1 with the same definition."""
    terms = _v1_terms()
    changed = [
        f"{term}: {json.dumps(definition)} in 0.8.0, "
        + (json.dumps(terms[term]) if term in terms else "missing")
        + " now"
        for term, definition in _snapshot()["terms"].items()
        if terms.get(term, object()) != definition
    ]
    assert not changed, (
        "records.context.v1.json changes terms frozen in tests/fixtures/context/records-v1-0.8.0.json. "
        "v1 is append-only: give a new meaning a new term. " + "; ".join(changed)
    )


# --- the comparison ----------------------------------------------------------------


def test_frozen_term_changes_flags_changed_and_dropped_terms_only() -> None:
    gen = _load_gen()
    frozen = {"a": "emmo:A", "b": {"@id": "emmo:B", "@type": "@id"}}

    assert gen.frozen_term_changes({**frozen, "c": "emmo:C"}, frozen) == []

    changed = gen.frozen_term_changes({"a": "emmo:A", "b": {"@id": "emmo:B"}}, frozen)
    assert len(changed) == 1 and changed[0].startswith("'b'")

    dropped = gen.frozen_term_changes({"b": frozen["b"]}, frozen)
    assert len(dropped) == 1 and dropped[0].startswith("'a'") and "removed" in dropped[0]


# --- the generator guard -----------------------------------------------------------


def test_build_passes_on_the_committed_tree() -> None:
    gen = _load_gen()
    assert gen.frozen_term_changes(gen.build()["@context"], gen.snapshot_terms()) == []


def test_build_refuses_a_hand_edit_of_a_frozen_term(gen) -> None:
    # Before the snapshot, build() started from the committed v1, so --check
    # compared v1 with itself and a hand edit passed.
    term = _plain_frozen_term(gen)
    doc = json.loads(gen.OUT.read_text(encoding="utf-8"))
    doc["@context"][term] = "emmo:SomethingElse"
    gen.OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(gen.FrozenTermError) as caught:
        gen.build()
    message = str(caught.value)
    assert repr(term) in message
    assert "append-only" in message
    assert "new term" in message


def test_check_and_write_refuse_a_changed_frozen_term(gen, capsys) -> None:
    term = _plain_frozen_term(gen)
    doc = json.loads(gen.OUT.read_text(encoding="utf-8"))
    doc["@context"][term] = "emmo:SomethingElse"
    edited = json.dumps(doc, indent=2) + "\n"
    gen.OUT.write_text(edited, encoding="utf-8")

    assert gen.main(["--check"]) == 1
    assert repr(term) in capsys.readouterr().err

    assert gen.main([]) == 1
    assert repr(term) in capsys.readouterr().err
    assert gen.OUT.read_text(encoding="utf-8") == edited


def test_build_refuses_a_correction_of_a_frozen_term(gen, monkeypatch) -> None:
    term = _plain_frozen_term(gen)
    monkeypatch.setattr(gen, "PRE_RELEASE_CORRECTIONS", {**gen.PRE_RELEASE_CORRECTIONS, term: "emmo:Corrected"})

    with pytest.raises(gen.FrozenTermError, match="append-only"):
        gen.build()


def test_build_refuses_to_drop_a_frozen_term(gen) -> None:
    snapshot = json.loads(gen.SNAPSHOT.read_text(encoding="utf-8"))
    snapshot["terms"]["retired_in_a_test"] = "emmo:Retired"
    gen.SNAPSHOT.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(gen.FrozenTermError) as caught:
        gen.build()
    assert "'retired_in_a_test'" in str(caught.value)
    assert "removed" in str(caught.value)


def test_build_takes_new_terms(gen, monkeypatch) -> None:
    monkeypatch.setattr(gen, "EMITTER_CLASS_TERMS", {**gen.EMITTER_CLASS_TERMS, "AddedInATest": "emmo:Added"})

    assert gen.build()["@context"]["AddedInATest"] == "emmo:Added"
    assert gen.main([]) == 0
    assert json.loads(gen.OUT.read_text(encoding="utf-8"))["@context"]["AddedInATest"] == "emmo:Added"
    assert gen.main(["--check"]) == 0


def test_build_without_a_snapshot_has_nothing_to_guard(gen, monkeypatch) -> None:
    gen.SNAPSHOT.unlink()
    term = _plain_frozen_term(gen)
    monkeypatch.setattr(gen, "PRE_RELEASE_CORRECTIONS", {**gen.PRE_RELEASE_CORRECTIONS, term: "emmo:Corrected"})

    assert gen.build()["@context"][term] == "emmo:Corrected"


# --- retaking the snapshot ---------------------------------------------------------


def test_write_snapshot_takes_a_pre_release_correction_before_the_tag(gen, monkeypatch, capsys) -> None:
    term = _plain_frozen_term(gen)
    added = _added_since_snapshot(gen)
    monkeypatch.setattr(gen, "PRE_RELEASE_CORRECTIONS", {**gen.PRE_RELEASE_CORRECTIONS, term: "emmo:Corrected"})
    assert gen.main(["--check"]) == 1  # the snapshot still holds the old definition

    capsys.readouterr()

    assert gen.main(["--write-snapshot"]) == 0
    out = capsys.readouterr().out
    assert f"{added} term(s) added, 1 changed or removed" in out and repr(term) in out

    snapshot = json.loads(gen.SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["terms"][term] == "emmo:Corrected"
    assert snapshot["terms"] == json.loads(gen.OUT.read_text(encoding="utf-8"))["@context"]
    assert gen.main(["--check"]) == 0
    assert "0 added since the 0.8.0 snapshot" in capsys.readouterr().out


def test_write_snapshot_refuses_once_the_release_is_tagged(gen, monkeypatch, capsys) -> None:
    term = _plain_frozen_term(gen)
    monkeypatch.setattr(gen, "PRE_RELEASE_CORRECTIONS", {**gen.PRE_RELEASE_CORRECTIONS, term: "emmo:Corrected"})
    monkeypatch.setattr(gen, "release_tagged", lambda: True)
    before = (gen.OUT.read_text(encoding="utf-8"), gen.SNAPSHOT.read_text(encoding="utf-8"))

    assert gen.main(["--write-snapshot"]) == 1
    err = capsys.readouterr().err
    assert "v0.8.0" in err and "append-only" in err
    assert (gen.OUT.read_text(encoding="utf-8"), gen.SNAPSHOT.read_text(encoding="utf-8")) == before


def test_check_counts_terms_added_since_the_snapshot(gen, monkeypatch, capsys) -> None:
    added = _added_since_snapshot(gen)
    monkeypatch.setattr(gen, "EMITTER_CLASS_TERMS", {**gen.EMITTER_CLASS_TERMS, "AddedInATest": "emmo:Added"})
    assert gen.main([]) == 0
    capsys.readouterr()

    assert gen.main(["--check"]) == 0
    assert f"{added + 1} added since the 0.8.0 snapshot" in capsys.readouterr().out
