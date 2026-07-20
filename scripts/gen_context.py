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

from battinfo.jsonld import TEST_METHOD_CONTEXT_TERMS, _CONTEXT_INLINE  # noqa: E402
from battinfo.transform.cell_spec_node import label_to_compact  # noqa: E402

OUT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"


def build() -> dict:
    """The complete records context: base conveniences + class table + method terms."""
    context: dict = dict(_CONTEXT_INLINE)
    context.update(label_to_compact())
    context.update(TEST_METHOD_CONTEXT_TERMS)
    return {"@context": context}


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
