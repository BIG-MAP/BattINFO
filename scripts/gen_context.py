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
