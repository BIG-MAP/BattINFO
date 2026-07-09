"""Generate the battinfo: record-layer vocabulary (Turtle).

POLICY OF RECORD (IDENTIFIER_POLICY.md section 14, 2026-07-07): battinfo: never
carries scientific/domain semantics — quantities and battery concepts live in
EMMO domain-battery / domain-electrochemistry (which we control upstream;
missing terms are ADDED THERE, not minted here), and administrative terms
re-home to dcterms/PROV/DCAT/schema.org/PAV. The human layer is labels and
contexts, not identifiers.

The vocabulary written to assets/vocab/battinfo-records.ttl is therefore an
explicit, closed inventory:

  (a) PLACEHOLDER terms — every battinfo: alias in the bundled records context
      (data/context/records.context.json). Each awaits an upstream EMMO term
      (step-6 drain, gated on domain-battery/electrochemistry releases).
  (b) RESIDUE terms — hand-curated, genuinely-local record-plumbing terms the
      code still emits, each with a hand-written rdfs:comment. Currently empty.

Honesty check (replaces the old blind regex scan): the generator scans
src/battinfo for battinfo: mints in ALL forms — double-quoted CURIEs,
whole-string full IRIs ("https://w3id.org/battinfo/<Term>") and f-string mints
(f"battinfo:{...}") — and FAILS if it finds an emitted term that is not in the
inventory. Known non-emitting sites are allowlisted:

  * READER_FALLBACK_TERMS — terms only *read* for back-compat with previously
    published packages / dataframes, never emitted.
  * DYNAMIC_MINT_FILES — the one deliberate dynamic mint: the unmapped-property
    fallback (_property_type_term), which warns `semantic.property_unmapped`
    at emit time and is by definition not enumerable here.

Serving: w3id.org/battinfo/<term> should resolve to this document (W2 routing
work); the namespace is the SLASH form by decision — the hash form belongs to
the application ontology (battinfo.ttl).

Usage:
    uv run python scripts/gen_battinfo_vocab.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "vocab" / "battinfo-records.ttl"
CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"

# ── Scan patterns (the honesty check) ─────────────────────────────────────────
CURIE_RE = re.compile(r'"battinfo:([A-Za-z_][A-Za-z0-9_]*)"')
FULL_IRI_RE = re.compile(r'"https://w3id\.org/battinfo/([A-Za-z][A-Za-z0-9_]*)"')
# CURIE-form f-strings mint vocabulary terms; full-IRI f-strings under the
# slash namespace mint record *identifiers* (spec/<uid>, cell/<uid> - policy
# section 3), which are not vocabulary terms and are out of scope here.
FSTRING_RE = re.compile(r'f"battinfo:\{')
SCAN = ["src/battinfo"]
SUFFIXES = {".py", ".json"}

# Terms that appear in source only as BACK-COMPAT READS of old exports
# (never emitted). They are deliberately NOT part of the vocabulary: the
# canonical emitters use standard vocabularies for these concepts now.
READER_FALLBACK_TERMS = {
    "cellFormat",   # ws.py package importer: legacy spec-node literal
    "chemistry",    # ws.py package importer: legacy spec-node literal
    "columns",      # metadata.py: legacy dataframe attrs key (csvw:column now)
}

# Files allowed to contain a dynamic (f-string) battinfo: mint. Exactly one is
# sanctioned: the unmapped-property fallback term, which is warned at emit time
# (semantic.property_unmapped) and documented as non-canonical.
DYNAMIC_MINT_FILES = {"transform/json_to_jsonld.py"}

# ── Static section: genuinely-local residue terms ─────────────────────────────
# term -> hand-written rdfs:comment. Add a term here ONLY if it is truly local
# record plumbing that no standard vocabulary covers; the honesty check forces
# every emitted term through either this dict or the context placeholders.
RESIDUE: dict[str, str] = {}


def placeholder_terms() -> dict[str, list[str]]:
    """battinfo: aliases in the records context -> the record keys aliasing them."""
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    out: dict[str, list[str]] = {}
    for key, value in context.items():
        iri = value.get("@id") if isinstance(value, dict) else value
        if isinstance(iri, str) and iri.startswith("battinfo:"):
            out.setdefault(iri[len("battinfo:"):], []).append(key)
    return out


def scanned_terms() -> tuple[set[str], set[str]]:
    """(static battinfo: terms found in src, files containing dynamic mints)."""
    terms: set[str] = set()
    dynamic_files: set[str] = set()
    for base in SCAN:
        for path in (ROOT / base).rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in CURIE_RE.findall(text):
                terms.add(match)
            for match in FULL_IRI_RE.findall(text):
                terms.add(match)
            if FSTRING_RE.search(text):
                dynamic_files.add(path.relative_to(ROOT / "src" / "battinfo").as_posix())
    return terms, dynamic_files


def check_honesty(placeholders: dict[str, list[str]]) -> None:
    terms, dynamic_files = scanned_terms()
    emitted = terms - READER_FALLBACK_TERMS
    unaccounted = emitted - set(placeholders) - set(RESIDUE)
    if unaccounted:
        raise SystemExit(
            "gen_battinfo_vocab: battinfo: term(s) minted in src/battinfo but "
            f"missing from the vocabulary inventory: {sorted(unaccounted)}. "
            "Re-home them to a standard vocabulary (IDENTIFIER_POLICY.md "
            "section 14) or, if genuinely local, add them to RESIDUE with a "
            "hand-written comment."
        )
    rogue_dynamic = dynamic_files - DYNAMIC_MINT_FILES
    if rogue_dynamic:
        raise SystemExit(
            "gen_battinfo_vocab: unsanctioned dynamic battinfo: mint (f-string) "
            f"in: {sorted(rogue_dynamic)}. Only the warned unmapped-property "
            "fallback in transform/json_to_jsonld.py is allowed."
        )


def label_of(term: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", term.replace("_", " "))
    return words[0].upper() + words[1:]


def build() -> str:
    placeholders = placeholder_terms()
    check_honesty(placeholders)
    lines = [
        "# GENERATED by scripts/gen_battinfo_vocab.py - do not edit.",
        "# Closed inventory of battinfo: record-layer terms (slash namespace):",
        "# context placeholders awaiting upstream EMMO terms, plus a hand-curated",
        "# residue of genuinely local record-plumbing terms (currently "
        f"{len(RESIDUE)}).",
        "# battinfo: never carries domain semantics (IDENTIFIER_POLICY.md s.14);",
        "# this file may only SHRINK as upstream EMMO releases drain the",
        "# placeholders. Unmapped-property fallback terms (warned at emit time",
        "# as semantic.property_unmapped) are ad hoc and intentionally not",
        "# declared here.",
        "@prefix battinfo: <https://w3id.org/battinfo/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "",
        "<https://w3id.org/battinfo/> a owl:Ontology ;",
        '    rdfs:label "BattINFO record-layer vocabulary"@en ;',
        '    rdfs:comment "Placeholder terms used by canonical BattINFO record '
        "exports (JSON-LD) while the corresponding EMMO domain terms are pending "
        "upstream. This is the record/data layer under the slash namespace; the "
        'EMMO-based application ontology lives in its own hash namespace."@en ;',
        "    dcterms:source <https://github.com/BIG-MAP/BattINFO> .",
        "",
    ]
    for term in sorted(placeholders):
        kind = "owl:Class" if term[0].isupper() else "rdf:Property"
        keys = ", ".join(sorted(placeholders[term]))
        comment = (
            f"Placeholder for record key(s) '{keys}' pending an upstream EMMO "
            "domain-battery/electrochemistry term; will be retired when the "
            "upstream term is published."
        )
        lines += [
            f"battinfo:{term} a {kind} ;",
            f'    rdfs:label "{label_of(term)}"@en ;',
            f'    rdfs:comment "{comment}"@en ;',
            "    rdfs:isDefinedBy <https://w3id.org/battinfo/> .",
            "",
        ]
    for term in sorted(RESIDUE):
        kind = "owl:Class" if term[0].isupper() else "rdf:Property"
        lines += [
            f"battinfo:{term} a {kind} ;",
            f'    rdfs:label "{label_of(term)}"@en ;',
            f'    rdfs:comment "{RESIDUE[term]}"@en ;',
            "    rdfs:isDefinedBy <https://w3id.org/battinfo/> .",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    n = len(placeholder_terms()) + len(RESIDUE)
    print(f"Wrote {OUT} ({n} terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
