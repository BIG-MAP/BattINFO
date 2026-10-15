"""Guard: v1 is append-only from the v0.8.0 tag.

``tests/fixtures/context/records-v1-0.8.0.json`` holds every term of
``records.context.v1.json`` as BattINFO 0.8.0 ships it, with its full definition.
A document minted against v1 must keep expanding to the same graph, so each of
those terms keeps its definition (and with it its expanded IRI, ``@type`` and
``@container``) for good. Terms added after the snapshot are allowed.

``scripts/gen_context.py`` enforces the same rule when it writes v1: it refuses
an output that changes or drops a snapshot term, or adds a JSON-LD keyword,
whether the change comes from a hand edit of v1 or from a source table.
``PRE_RELEASE_CORRECTIONS`` is closed: the build no longer applies it, and v1
already carries every entry. Before the tag, ``gen_context.py --write-snapshot``
retakes the snapshot after the last pre-release correction; once the tag exists it
refuses.

Two checks hold the line where the snapshot file alone cannot. Against each
release tag from v0.8.0 on that the checked-out commit contains, v1 keeps every
term the tag's v1 defines, and the snapshot equals the tag's copy, so a change to
v1 and the snapshot together fails, and so does a change to a term added after
0.8.0. The CI test job fetches the tags for this. In CI for a 0.8.0 release build
(the ``release/0.8.0`` branch or a ``v0.8.0`` tag, release candidates included) the
snapshot must hold every v1 term, so that no term ships in 0.8.0 unfrozen.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
SNAPSHOT = ROOT / "tests" / "fixtures" / "context" / "records-v1-0.8.0.json"
V1_PATH = "src/battinfo/data/context/records.context.v1.json"
SNAPSHOT_PATH = "tests/fixtures/context/records-v1-0.8.0.json"
_FINAL_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


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


@pytest.mark.parametrize("keyword", ["@vocab", "@base", "@language", "@propagate", "@protected", "@import"])
def test_frozen_term_changes_flags_an_added_keyword(keyword) -> None:
    # A keyword is no term of its own: it changes how every key of every document expands.
    gen = _load_gen()
    frozen = {"@version": 1.1, "a": "emmo:A"}

    changes = gen.frozen_term_changes({**frozen, keyword: "en"}, frozen)
    assert len(changes) == 1 and changes[0].startswith(repr(keyword)) and "added" in changes[0]
    assert gen.frozen_term_changes({**frozen, keyword: "en"}, {}) == []  # no snapshot, nothing to guard


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


def test_build_no_longer_applies_pre_release_corrections(gen, monkeypatch) -> None:
    term = _plain_frozen_term(gen)
    frozen = _snapshot()["terms"][term]
    monkeypatch.setattr(
        gen,
        "PRE_RELEASE_CORRECTIONS",
        {**gen.PRE_RELEASE_CORRECTIONS, term: "emmo:Corrected", "added_by_a_correction": "emmo:Added"},
    )

    context = gen.build()["@context"]
    assert context[term] == frozen
    assert "added_by_a_correction" not in context


def test_every_pre_release_correction_is_already_in_v1() -> None:
    """The closed table is a record: v1 carries each entry, so dropping it from the build changed nothing."""
    terms = _v1_terms()
    missing = {
        term: definition
        for term, definition in _load_gen().PRE_RELEASE_CORRECTIONS.items()
        if terms.get(term) != definition
    }
    assert not missing, (
        "PRE_RELEASE_CORRECTIONS holds entries that records.context.v1.json does not carry. The build no longer "
        f"applies the table: edit v1 to match, then run python scripts/gen_context.py --write-snapshot. {missing}"
    )


def test_build_refuses_an_added_json_ld_keyword(gen, monkeypatch) -> None:
    monkeypatch.setattr(gen, "EMITTER_CLASS_TERMS", {**gen.EMITTER_CLASS_TERMS, "@vocab": "https://w3id.org/battinfo/"})

    with pytest.raises(gen.FrozenTermError) as caught:
        gen.build()
    assert "'@vocab' added" in str(caught.value)


def test_refusal_names_the_retake_only_before_the_tag(gen, monkeypatch) -> None:
    term = _plain_frozen_term(gen)
    doc = json.loads(gen.OUT.read_text(encoding="utf-8"))
    doc["@context"][term] = "emmo:SomethingElse"
    gen.OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(gen.FrozenTermError) as before_tag:
        gen.build()
    assert "--write-snapshot" in str(before_tag.value)

    monkeypatch.setattr(gen, "release_tagged", lambda: True)
    with pytest.raises(gen.FrozenTermError) as after_tag:
        gen.build()
    assert "--write-snapshot" not in str(after_tag.value)
    assert "new term" in str(after_tag.value)


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


def _hand_edit(gen, term: str, definition: str) -> None:
    doc = json.loads(gen.OUT.read_text(encoding="utf-8"))
    doc["@context"][term] = definition
    gen.OUT.write_text(gen.render(doc), encoding="utf-8")


def test_build_without_a_snapshot_has_nothing_to_guard(gen) -> None:
    gen.SNAPSHOT.unlink()
    term = _plain_frozen_term(gen)
    _hand_edit(gen, term, "emmo:Corrected")

    assert gen.build()["@context"][term] == "emmo:Corrected"


# --- retaking the snapshot ---------------------------------------------------------


def test_write_snapshot_takes_a_pre_release_correction_before_the_tag(gen, capsys) -> None:
    # A ruled correction before the tag is an edit of v1 (plus a PRE_RELEASE_CORRECTIONS
    # entry for the record), which the retake then freezes.
    term = _plain_frozen_term(gen)
    added = _added_since_snapshot(gen)
    _hand_edit(gen, term, "emmo:Corrected")
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
    _hand_edit(gen, term, "emmo:Corrected")
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


# --- against the release tags --------------------------------------------------------


def _final_release_tags(names: Iterable[str]) -> list[str]:
    """The final release tags from v0.8.0 on among *names*, oldest first."""
    versions = {}
    for name in names:
        match = _FINAL_TAG.match(name)
        if match and tuple(int(part) for part in match.groups()) >= (0, 8, 0):
            versions[name] = tuple(int(part) for part in match.groups())
    return sorted(versions, key=versions.__getitem__)


def _local_tags(root: Path = ROOT) -> list[str]:
    """The ``v*`` tags that the checked-out commit contains. A tag on a later line, such as
    v0.9.0 seen from a branch cut from v0.8.0, is not a release this commit has to keep."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "tag", "--merged", "HEAD", "--list", "v*"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    return result.stdout.split() if result.returncode == 0 else []


def _file_at(tag: str, path: str) -> str | None:
    """*path* as *tag* holds it, or ``None`` when the tag has no such file."""
    result = subprocess.run(["git", "-C", str(ROOT), "show", f"{tag}:{path}"], capture_output=True, check=False)
    return result.stdout.decode("utf-8") if result.returncode == 0 else None


def tagged_release_problems(tags: Iterable[str], read: Callable[[str, str], str | None]) -> list[str]:
    """What the bundled v1 and snapshot change against each release tag's copies."""
    gen = _load_gen()
    current = _v1_terms()
    snapshot = _snapshot()
    problems = []
    for tag in tags:
        tagged_v1 = read(tag, V1_PATH)
        if tagged_v1 is not None:
            for change in gen.frozen_term_changes(current, json.loads(tagged_v1)["@context"]):
                problems.append(f"{tag}: {change}")
        tagged_snapshot = read(tag, SNAPSHOT_PATH)
        if tagged_snapshot is not None and json.loads(tagged_snapshot) != snapshot:
            problems.append(f"{tag}: {SNAPSHOT_PATH} differs from the copy the tag holds")
    return problems


def test_final_release_tags_start_at_0_8_0() -> None:
    names = ["v0.0.1", "v0.6.0", "v0.8.0rc1", "v0.8.0", "v0.10.0", "v0.8.2", "v1.0.0-beta", "release"]
    assert _final_release_tags(names) == ["v0.8.0", "v0.8.2", "v0.10.0"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        check=True,
        capture_output=True,
    )


def test_tagged_release_checks_read_only_the_tags_the_commit_contains(tmp_path: Path) -> None:
    # A release/0.8.x branch cut from v0.8.0 must not be held to the terms v0.9.0 adds.
    if shutil.which("git") is None:
        pytest.skip("needs git")
    _git(tmp_path, "init", "-q")
    (tmp_path / "v1.json").write_text("{}", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "0.8.0")
    _git(tmp_path, "tag", "v0.8.0")
    _git(tmp_path, "branch", "release-0.8.x")
    (tmp_path / "v1.json").write_text('{"later": 1}', encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "0.9.0")
    _git(tmp_path, "tag", "v0.9.0")

    assert _final_release_tags(_local_tags(tmp_path)) == ["v0.8.0", "v0.9.0"]
    _git(tmp_path, "checkout", "-q", "release-0.8.x")
    assert _final_release_tags(_local_tags(tmp_path)) == ["v0.8.0"]


def test_v1_keeps_every_term_of_each_tagged_release() -> None:
    """Covers what the snapshot file cannot: a pull request that changes v1 and the snapshot together,
    and a change to a term added after 0.8.0. Runs where the checkout has the release tags, as the CI
    test job does."""
    tags = _final_release_tags(_local_tags())
    if not tags:
        pytest.skip("this checkout has no release tag from v0.8.0 on")
    problems = tagged_release_problems(tags, _file_at)
    assert not problems, (
        "v1 is append-only: every term a release shipped keeps its definition, and the 0.8.0 snapshot stays "
        "as tagged. " + "; ".join(problems)
    )


def test_tagged_release_check_flags_changes_to_v1_and_the_snapshot() -> None:
    v1_text = V1.read_text(encoding="utf-8")
    snapshot_text = SNAPSHOT.read_text(encoding="utf-8")
    term = _plain_frozen_term(_load_gen())

    def reader(v1: str, snapshot: str | None) -> Callable[[str, str], str | None]:
        return lambda tag, path: {V1_PATH: v1, SNAPSHOT_PATH: snapshot}[path]

    assert tagged_release_problems(["v0.8.0"], reader(v1_text, snapshot_text)) == []
    assert tagged_release_problems(["v0.8.1"], reader(v1_text, None)) == []

    # The tag shipped the term with another definition, so the bundled v1 changed it since.
    tagged = json.loads(v1_text)
    tagged["@context"][term] = "emmo:AsTagged"
    changed = tagged_release_problems(["v0.8.1"], reader(json.dumps(tagged), None))
    assert len(changed) == 1 and changed[0].startswith(f"v0.8.1: {term!r} changed")

    # The tag shipped a term the bundled v1 has dropped since.
    tagged = json.loads(v1_text)
    tagged["@context"]["shipped_in_a_later_release"] = "emmo:Later"
    dropped = tagged_release_problems(["v0.8.2"], reader(json.dumps(tagged), None))
    assert len(dropped) == 1 and "'shipped_in_a_later_release' removed" in dropped[0]

    # The snapshot was edited after the tag.
    edited = json.loads(snapshot_text)
    edited["terms"][term] = "emmo:Loosened"
    assert tagged_release_problems(["v0.8.0"], reader(v1_text, json.dumps(edited))) == [
        f"v0.8.0: {SNAPSHOT_PATH} differs from the copy the tag holds"
    ]


# --- the release build ---------------------------------------------------------------


def is_release_build(env: Mapping[str, str], release: str = "0.8.0") -> bool:
    """Whether a GitHub Actions run builds *release*: its tags (release candidates included) or its branch."""
    version = re.escape(release) + r"(?![0-9])"
    ref = env.get("GITHUB_REF", "")
    head = env.get("GITHUB_HEAD_REF", "")
    return bool(
        re.match(rf"refs/tags/v{version}", ref)
        or re.match(rf"refs/heads/release/{version}", ref)
        or re.match(rf"release/{version}", head)
    )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"GITHUB_REF": "refs/tags/v0.8.0"}, True),
        ({"GITHUB_REF": "refs/tags/v0.8.0rc2"}, True),
        ({"GITHUB_REF": "refs/heads/release/0.8.0"}, True),
        ({"GITHUB_REF": "refs/pull/470/merge", "GITHUB_HEAD_REF": "release/0.8.0"}, True),
        ({"GITHUB_REF": "refs/heads/main"}, False),
        ({"GITHUB_REF": "refs/tags/v0.8.1"}, False),
        ({"GITHUB_REF": "refs/tags/v0.8.01"}, False),
        ({"GITHUB_REF": "refs/heads/release/0.8.x"}, False),
        ({}, False),
    ],
)
def test_is_release_build(env, expected) -> None:
    assert is_release_build(env) is expected


def test_a_0_8_0_release_build_freezes_every_v1_term() -> None:
    """RELEASING.md step 4 as a CI gate: 0.8.0 ships no v1 term that the snapshot does not freeze."""
    if not is_release_build(os.environ):
        pytest.skip("not a CI run for the 0.8.0 release branch or tags")
    added = sorted(set(_v1_terms()) - set(_snapshot()["terms"]))
    assert not added, (
        f"records.context.v1.json has {len(added)} term(s) the 0.8.0 snapshot does not freeze: {added}. "
        "Before the tag, run python scripts/gen_context.py --write-snapshot and commit v1 and the snapshot."
    )
