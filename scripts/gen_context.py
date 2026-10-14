"""Generate the complete, versioned battinfo records @context.

Materializes the hosted context served at
``https://w3id.org/battinfo/context/records/v1.json``: a frozen, self-contained
superset of every term the record emitters use (the base records conveniences,
the prefLabel -> compact-IRI class table, and the test-method terms), so a
document can reference the URL instead of inlining ~350 terms. It is what the
transform embeds when asked for a self-contained document, and the copy the
offline validator/viewer resolve the URL against — one source of truth.

Regenerate when new EMMO terms are adopted; bump to a v2 file for a breaking
change (a published version's meaning must never change).

v1 is append-only from the v0.8.0 tag. ``tests/fixtures/context/records-v1-0.8.0.json``
holds every term as 0.8.0 ships it, and this script refuses to write a v1 that
changes or drops one of them. ``--write-snapshot`` retakes that snapshot from the
v1 it writes; it is for the release work before the tag and refuses once the
v0.8.0 tag exists.

    uv run python scripts/gen_context.py                    # write
    uv run python scripts/gen_context.py --check             # CI drift gate
    uv run python scripts/gen_context.py --write-snapshot    # before the v0.8.0 tag only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import (  # noqa: E402
    _CONTEXT_INLINE,
    TEST_METHOD_CONTEXT_TERMS,
    TEST_PROTOCOL_CONTEXT_TERMS,
)
from battinfo.transform.cell_spec_node import label_to_compact  # noqa: E402

OUT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
CONTEXT_URL = "https://w3id.org/battinfo/context/records/v1.json"

# v1 as the first release ships it. From the v0.8.0 tag on, every term here keeps
# its definition: build() refuses an output that changes or drops one, and
# tests/test_context_v1_freeze.py checks the bundled v1 against the same file.
SNAPSHOT = ROOT / "tests" / "fixtures" / "context" / "records-v1-0.8.0.json"
SNAPSHOT_RELEASE = "0.8.0"

# The repository (and thus every generated artifact it serves) is Apache-2.0.
# The claim rides as a top-level sibling of ``@context`` — JSON-LD context
# processors read only the ``@context`` member, so this neither changes the
# term count nor affects expansion, it just makes the served document
# self-describing.
LICENSE = "https://www.apache.org/licenses/LICENSE-2.0"

# Class terms the emitters stack on nodes but that no other source carries —
# IRIs verified against the vendored domain contexts. The corpus-wide sweep in
# tests/test_jsonld_type_guards.py fails whenever an emitted bare @type is
# missing from the context, so additions land here (0.8.0 review follow-up).
EMITTER_CLASS_TERMS = {
    "Manufacturing": "emmo:EMMO_a4d66059_5dd3_4b90_b4cb_10960559441b",
    "NegativeElectrode": "electrochemistry:electrochemistry_c94c041b_8ea6_43e7_85cc_d2bce7785b4c",
    "PositiveElectrode": "electrochemistry:electrochemistry_aff732a9_238a_4734_977c_b2ba202af126",
    "MolarMass": "emmo:EMMO_e980389d_6dfe_4156_9b40_32050c9644a5",
    "SpecificSurfaceArea": "electrochemistry:electrochemistry_cf54e7c1_f359_4715_b61d_0350b890d597",
    # The classes the candidate property map gives the two nominal continuous
    # current keys. Those keys stay deferred in the curated map, so nothing else
    # brings these terms into the context.
    "ChargingCurrent": "electrochemistry:electrochemistry_79551e01_4bc6_4292_916e_08fe28a84600",
    "DischargingCurrent": "electrochemistry:electrochemistry_e4d666ee_d637_45cd_a904_dc33941ead4f",
}


# Corrections of v1 before the first release (owner rulings 2026-10-07 and
# 2026-10-13). v1 was frozen before domain-electrochemistry 0.37.1 and
# domain-battery 0.20.2 were adopted, so the first eight terms kept a private
# battinfo: mint, a superseded class or a deprecated IRI while the curated
# property map and the entity type map had moved on. The last two were wrong
# from the start: degC named EMMO's class for the programming language C, and
# TemperatureCoefficientOfTheOpenCircuitVoltage named the CoatingThickness IRI.
# No released package has shipped v1, so it is corrected in place rather than
# bumped to v2. After 0.8.0 this table must not grow: a change of meaning then
# needs a v2 context. tests/test_context_v1_agreement.py fails if v1 and the
# curated maps disagree again. The table is closed: build() no longer applies it,
# v1 already carries every entry (tests/test_context_v1_freeze.py checks that),
# and it stays as the record of what was corrected in place, which the erratum to
# section 11.1 of IDENTIFIER_POLICY.md lists. A correction ruled before the v0.8.0
# tag is an edit of v1 plus an entry here, taken into the snapshot with
# --write-snapshot (RELEASING.md, "The frozen v1 records context").
PRE_RELEASE_CORRECTIONS = {
    # private battinfo: mints -> the classes added in domain-electrochemistry 0.37.1
    "power_capability": "electrochemistry:electrochemistry_4e6c4e9d_64cb_4c24_a0f3_5b4146ebbeb0",
    "maximum_power": "electrochemistry:electrochemistry_4e6c4e9d_64cb_4c24_a0f3_5b4146ebbeb0",
    "power_energy_ratio": "electrochemistry:electrochemistry_917660a7_2d98_4564_9ce7_6b5d1087de2c",
    "round_trip_energy_efficiency": "electrochemistry:electrochemistry_c413d29a_b814_4d88_8db0_0fd0171cff11",
    "capacity_threshold_exhaustion": "electrochemistry:electrochemistry_02dc55b3_18a1_438e_bee0_ab77670cb2d5",
    "charging_time": "electrochemistry:electrochemistry_a3d54f83_4dc2_4833_acc2_c8652702d9b7",
    # CapacityFade (a degradation phenomenon) -> CapacityFadeRate (the quantity)
    "capacity_fade": "electrochemistry:electrochemistry_5b59a86e_99b4_493e_ae12_33ae8b5ec7c0",
    # deprecated hyphen-named IRI -> its underscore twin (domain-battery issue #73)
    "PrismaticBattery": "battery:battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d",
    # EMMO_36a9bf69_... is the programming language C (a CompiledLanguage), not
    # the unit; EMMO 1.0.2 declares the degree Celsius as emmo:DegreeCelsius.
    "degC": "emmo:DegreeCelsius",
    # was electrochemistry_3b938708_..., the IRI of CoatingThickness
    "TemperatureCoefficientOfTheOpenCircuitVoltage": (
        "electrochemistry:electrochemistry_3bb5ae23_59fa_4bc7_9495_803eb6719f28"
    ),
}


class FrozenTermError(ValueError):
    """A build would change or drop a term that the v1 snapshot holds."""


def _published() -> dict:
    """The v1 terms already served at the hosted URL, or ``{}`` before first write."""
    if not OUT.exists():
        return {}
    return json.loads(OUT.read_text(encoding="utf-8")).get("@context", {})


def snapshot_terms() -> dict:
    """The terms frozen in the snapshot, or ``{}`` before the snapshot is taken."""
    if not SNAPSHOT.exists():
        return {}
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["terms"]


def frozen_term_changes(context: dict, frozen: dict) -> list[str]:
    """One line for each *frozen* term that *context* removes or defines differently.

    The whole definition counts, so a term keeps its expanded IRI, ``@type`` and
    ``@container``. Terms in *context* that *frozen* lacks are additions and pass,
    except a JSON-LD keyword such as ``@vocab``, ``@base`` or ``@language``: adding
    one changes how the terms and keys of every document expand, so it counts as a
    change.
    """
    changes = []
    for term, definition in frozen.items():
        if term not in context:
            changes.append(f"{term!r} removed (was {json.dumps(definition)})")
        elif context[term] != definition:
            changes.append(f"{term!r} changed from {json.dumps(definition)} to {json.dumps(context[term])}")
    if frozen:
        for term, definition in context.items():
            if term.startswith("@") and term not in frozen:
                changes.append(
                    f"{term!r} added as {json.dumps(definition)}: a JSON-LD keyword changes how every document expands"
                )
    return changes


def _refusal(changes: list[str]) -> str:
    snapshot = SNAPSHOT.relative_to(ROOT).as_posix() if SNAPSHOT.is_relative_to(ROOT) else str(SNAPSHOT)
    lines = [f"Refusing to change {len(changes)} v1 term(s) frozen in {snapshot}:"]
    lines += [f"  {change}" for change in changes]
    lines.append(
        "v1 is append-only: a term keeps the meaning it shipped with, so documents that use it "
        "keep expanding to the same graph. Give a new meaning a new term (or a v2 context) "
        "and leave the old term as it is."
    )
    if not release_tagged():
        lines.append(
            f"Before the v{SNAPSHOT_RELEASE} tag, a correction the release has ruled on is taken into the "
            "snapshot with `python scripts/gen_context.py --write-snapshot` (RELEASING.md, "
            '"The frozen v1 records context").'
        )
    return "\n".join(lines)


def build(*, enforce_snapshot: bool = True) -> dict:
    """The complete records context: base conveniences + class table + method terms.

    v1 is append-only. Every source below is merged with ``setdefault`` on top of
    the terms already published, so regenerating can add a term but can never
    rewrite one: a document minted against v1 keeps expanding to the same graph
    forever. Changing what an existing term means requires a v2 file, not an edit
    here. The merge alone cannot hold that line, because it starts from the
    committed v1 and so keeps a hand edit. So once the snapshot exists, a build
    that changes or drops one of its terms, or adds a JSON-LD keyword, raises
    :class:`FrozenTermError`. Only ``--write-snapshot`` builds without that check.
    ``PRE_RELEASE_CORRECTIONS`` is not applied: the table is closed, and v1
    already carries each of its entries.
    """
    context: dict = _published()
    for source in (
        _CONTEXT_INLINE,
        label_to_compact(),
        TEST_METHOD_CONTEXT_TERMS,
        TEST_PROTOCOL_CONTEXT_TERMS,
        EMITTER_CLASS_TERMS,
    ):
        for term, value in source.items():
            context.setdefault(term, value)
    if enforce_snapshot:
        changes = frozen_term_changes(context, snapshot_terms())
        if changes:
            raise FrozenTermError(_refusal(changes))
    return {"license": LICENSE, "@context": context}


def render(doc: dict | None = None) -> str:
    return json.dumps(build() if doc is None else doc, indent=2, ensure_ascii=False) + "\n"


def render_snapshot(doc: dict) -> str:
    """The snapshot of the v1 document *doc*: every term with its full definition."""
    snapshot = {
        "description": (
            "Every term of the v1 records context as BattINFO 0.8.0 ships it. v1 is append-only "
            "from the v0.8.0 tag: each term here keeps this definition, and a new meaning needs a "
            "new term. scripts/gen_context.py refuses to change these terms, and "
            "tests/test_context_v1_freeze.py checks the bundled copy against them. Written by "
            "scripts/gen_context.py --write-snapshot, which refuses once the tag exists."
        ),
        "context": CONTEXT_URL,
        "release": SNAPSHOT_RELEASE,
        "terms": doc["@context"],
    }
    return json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"


def release_tagged() -> bool:
    """Whether this checkout has the tag of the snapshot's release (best effort, via git)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"refs/tags/v{SNAPSHOT_RELEASE}"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate records.context.v1.json.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail when the committed v1 differs from a fresh build")
    mode.add_argument(
        "--write-snapshot",
        action="store_true",
        help=f"write v1 and retake the {SNAPSHOT_RELEASE} snapshot from it (before the v{SNAPSHOT_RELEASE} tag only)",
    )
    args = parser.parse_args(argv)

    if args.write_snapshot:
        if release_tagged():
            print(
                f"v{SNAPSHOT_RELEASE} is tagged, so its v1 snapshot is final. v1 is append-only: "
                "give a new meaning a new term instead of changing one the snapshot holds.",
                file=sys.stderr,
            )
            return 1
        doc = build(enforce_snapshot=False)
        previous = snapshot_terms()
        changes = frozen_term_changes(doc["@context"], previous)
        added = [term for term in doc["@context"] if term not in previous]
        _write(OUT, render(doc))
        _write(SNAPSHOT, render_snapshot(doc))
        print(f"Wrote {OUT} and {SNAPSHOT} ({len(doc['@context'])} terms).")
        if previous:
            print(f"Against the previous snapshot: {len(added)} term(s) added, {len(changes)} changed or removed.")
            for change in changes:
                print(f"  {change}")
        return 0

    try:
        doc = build()
    except FrozenTermError as exc:
        print(exc, file=sys.stderr)
        return 1
    text = render(doc)
    count = len(doc["@context"])
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("src/battinfo/data/context/records.context.v1.json drifts — run scripts/gen_context.py")
            return 1
        frozen = snapshot_terms()
        added = f"; {count - len(frozen)} added since the {SNAPSHOT_RELEASE} snapshot" if frozen else ""
        print(f"records.context.v1.json in sync ({count} terms{added}).")
        return 0
    _write(OUT, text)
    print(f"Wrote {OUT} ({count} terms).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
