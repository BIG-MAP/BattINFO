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

    uv run python scripts/gen_context.py           # write
    uv run python scripts/gen_context.py --check    # CI drift gate
"""

from __future__ import annotations

import json
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


# One-time correction of v1 before the first release (owner ruling 2026-10-07).
# v1 was frozen before domain-electrochemistry 0.37.1 and domain-battery 0.20.2
# were adopted, so these terms kept a private battinfo: mint, a superseded class
# or a deprecated IRI while the curated property map and the entity type map had
# moved on. No released package has shipped v1, so it is corrected in place
# rather than bumped to v2. After 0.8.0 this table must not grow: a change of
# meaning then needs a v2 context. tests/test_context_v1_agreement.py fails if
# v1 and the curated maps disagree again.
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
}


def _published() -> dict:
    """The v1 terms already served at the hosted URL, or ``{}`` before first write."""
    if not OUT.exists():
        return {}
    return json.loads(OUT.read_text(encoding="utf-8")).get("@context", {})


def build() -> dict:
    """The complete records context: base conveniences + class table + method terms.

    v1 is append-only. Every source below is merged with ``setdefault`` on top of
    the terms already published, so regenerating can add a term but can never
    rewrite one: a document minted against v1 keeps expanding to the same graph
    forever. Changing what an existing term means requires a v2 file, not an edit
    here — and the drift check will not paper over it, because the inline context
    and v1 would then disagree and ``test_url_mode_is_compact_and_equivalent``
    fails until the bump is made deliberately.
    """
    context: dict = _published()
    context.update(PRE_RELEASE_CORRECTIONS)
    for source in (
        _CONTEXT_INLINE,
        label_to_compact(),
        TEST_METHOD_CONTEXT_TERMS,
        TEST_PROTOCOL_CONTEXT_TERMS,
        EMITTER_CLASS_TERMS,
    ):
        for term, value in source.items():
            context.setdefault(term, value)
    return {"license": LICENSE, "@context": context}


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            print("src/battinfo/data/context/records.context.v1.json drifts — run scripts/gen_context.py")
            sys.exit(1)
        print(f"records.context.v1.json in sync ({len(build()['@context'])} terms).")
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"Wrote {OUT} ({len(build()['@context'])} terms).")
