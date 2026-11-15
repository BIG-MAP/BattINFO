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
      (data/context/records.context.json, including property-scoped contexts)
      AND every battinfo: slot_uri/class_uri declared in schema/*.yaml. Each
      awaits an upstream EMMO term (step-6 drain, gated on
      domain-battery/electrochemistry releases).
  (b) RESIDUE terms — hand-curated, genuinely-local record-plumbing terms the
      code still emits, each with a hand-written rdfs:comment. Currently empty.
  (c) RETIRED terms — terms an earlier served copy declared and a later one
      dropped. Published records and deposits still use them, so each stays
      declared, as owl:deprecated, with dcterms:isReplacedBy where the term
      that replaced it is known.

The vocabulary is an ontology of its own, https://w3id.org/battinfo/vocab/records
(BIG-MAP/BattINFO#481), under the reserved vocab segment, and every term says
rdfs:isDefinedBy it. The terms themselves stay at the root,
https://w3id.org/battinfo/<term>, whose bare address belongs to the BattINFO
ontology (battinfo.ttl).

There is deliberately NO hash-namespace (ns#) section: served artifacts no
longer expand anything against https://w3id.org/battinfo/ns#. Every predicate
in a served record is a real vocabulary term, a battinfo: slash placeholder
from this inventory, or excluded from RDF by the registry's artifact context —
the registry's honesty check enforces that, so this file only has to account
for the slash namespace.

Honesty check (replaces the old blind regex scan): the generator scans
src/battinfo for battinfo: mints in ALL forms — double-quoted CURIEs,
whole-string full IRIs ("https://w3id.org/battinfo/<Term>") and f-string mints
(f"battinfo:{...}") — and FAILS if it finds an emitted term that is not in the
inventory. Known non-emitting sites are allowlisted:

  * READER_FALLBACK_TERMS — terms only *read* for back-compat with previously
    published packages / dataframes, never emitted.
  * DYNAMIC_MINT_FILES — files allowed to mint battinfo: terms dynamically.
    Empty: an unmapped property key is typed by its value-basis class only and
    warns `semantic.property_unmapped`; no class name is ever generated.

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

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
OUT = ROOT / "assets" / "vocab" / "battinfo-records.ttl"
CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"
# The frozen, hosted context. Its terms stay published forever, so its
# battinfo: aliases stay in the inventory even after the working context
# repoints them at an upstream EMMO class.
PUBLISHED_CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"

# ── Scan patterns (the honesty check) ─────────────────────────────────────────
# Both quote styles. Hand-written source uses double quotes, but LinkML's
# gen-pydantic renders the `linkml_meta` slot_uri/class_uri declarations with
# single quotes, so a double-quote-only scan skipped bundle_generated.py in its
# entirety — 46 battinfo: CURIEs the inventory never had to account for.
CURIE_RE = re.compile(r"""["']battinfo:([A-Za-z_][A-Za-z0-9_]*)["']""")
FULL_IRI_RE = re.compile(r"""["']https://w3id\.org/battinfo/([A-Za-z][A-Za-z0-9_]*)["']""")
# CURIE-form f-strings mint vocabulary terms; full-IRI f-strings under the
# slash namespace mint record *identifiers* (spec/<uid>, cell/<uid> - policy
# section 3), which are not vocabulary terms and are out of scope here.
FSTRING_RE = re.compile(r'f"battinfo:\{')
SCAN = ["src/battinfo"]
SUFFIXES = {".py", ".json"}

# Terms that appear in source only as BACK-COMPAT READS of old exports
# (never emitted). They are deliberately NOT part of the vocabulary: the
# canonical emitters use standard vocabularies for these concepts now.
# (cellFormat/chemistry used to sit here as reader-only terms; the canonical
# record context now declares them as placeholders, so they are inventoried
# like any other context alias.)
READER_FALLBACK_TERMS = {
    "columns",  # metadata.py: legacy dataframe attrs key (csvw:column now)
}

# Files allowed to contain a dynamic (f-string) battinfo: mint. Exactly one is
# sanctioned: the unmapped-property fallback term, which is warned at emit time
# (semantic.property_unmapped) and documented as non-canonical.
DYNAMIC_MINT_FILES: set[str] = set()

# The vocabulary's own ontology IRI. The root, https://w3id.org/battinfo/, is the
# address of the BattINFO ontology, so the vocabulary does not claim it.
ONTOLOGY_IRI = "https://w3id.org/battinfo/vocab/records"

# ── Static section: genuinely-local residue terms ─────────────────────────────
# term -> hand-written rdfs:comment. Add a term here ONLY if it is truly local
# record plumbing that no standard vocabulary covers; the honesty check forces
# every emitted term through either this dict or the context placeholders.
RESIDUE: dict[str, str] = {}

# ── Retired terms ─────────────────────────────────────────────────────────────
# term -> the IRI of the term that replaced it, or None when none is recorded.
# Each was declared by a served copy of this vocabulary and dropped by a later
# one; the registry's case table (battinfo_registry.api.w3id_cases) keeps the
# same list. They stay declared, as owl:deprecated, because published records
# and deposits use them, the Flores deposits on Zenodo among them
# (ambientTemperature). profile is left out: it is a reserved segment, and no
# record used it. A term is never both retired and current.
_ELECTROCHEMISTRY = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
RETIRED: dict[str, str | None] = {
    # Replaced by EMMO terms (the erratum to IDENTIFIER_POLICY 11.1 lists the v1 terms).
    "operatingTemperatureMin": _ELECTROCHEMISTRY + "08a73f4b_3242_4356_af24_68ba0bf66d51",  # PR #331
    "operatingTemperatureMax": _ELECTROCHEMISTRY + "e999bd7d_93ad_47fb_8d8d_dd667e4ef553",  # PR #331
    "powerCapability": _ELECTROCHEMISTRY + "4e6c4e9d_64cb_4c24_a0f3_5b4146ebbeb0",  # MaximumPower, PR #415
    "maximumPower": _ELECTROCHEMISTRY + "4e6c4e9d_64cb_4c24_a0f3_5b4146ebbeb0",  # MaximumPower, PR #415
    "powerEnergyRatio": _ELECTROCHEMISTRY + "917660a7_2d98_4564_9ce7_6b5d1087de2c",  # PR #415
    "roundTripEnergyEfficiency": _ELECTROCHEMISTRY + "c413d29a_b814_4d88_8db0_0fd0171cff11",  # PR #415
    "capacityThresholdExhaustion": _ELECTROCHEMISTRY + "02dc55b3_18a1_438e_bee0_ab77670cb2d5",  # PR #415
    "chargingTime": _ELECTROCHEMISTRY + "a3d54f83_4dc2_4833_acc2_c8652702d9b7",  # PR #415
    "ambientTemperature": _ELECTROCHEMISTRY + "abd08921_6f3b_4a48_811e_7685c58aec0b",  # PR #465
    # Served from 2026-07-08 until the registry's re-vendor of 2026-07-18. No
    # replacement recorded.
    **dict.fromkeys(
        (
            "Battery",
            "BatteryCell",
            "BatteryMetadataRecord",
            "BatteryModule",
            "BatteryPack",
            "BatterySystem",
            "Cell",
            "affectedProperty",
            "citationDOI",
            "columns",
            "deviationCategory",
            "doi",
            "hasBattery",
            "hasMeasurement",
            "instrumentName",
            "mass",
            "nominalCapacity",
            "nominalVoltage",
            "protocolName",
            "provenance",
            "retrievedAt",
            "sourceFile",
            "sourceType",
            "sourceURL",
            "status",
            "testProtocol",
            "testedCell",
            "typicalValue",
            "valueText",
            "workflowVersion",
        )
    ),
}


def _collect_context_aliases(context: dict, out: dict[str, list[str]]) -> None:
    """Record every battinfo: alias in a context, scoped contexts included.

    A term definition may carry its own ``@context`` (the conformance and
    checksum nodes do); a battinfo: alias declared there is served exactly like
    a top-level one and must dereference the same way.
    """
    for key, value in context.items():
        if key.startswith("@"):
            continue
        iri = value.get("@id") if isinstance(value, dict) else value
        if isinstance(iri, str) and iri.startswith("battinfo:"):
            keys = out.setdefault(iri[len("battinfo:") :], [])
            if key not in keys:
                keys.append(key)
        if isinstance(value, dict) and isinstance(value.get("@context"), dict):
            _collect_context_aliases(value["@context"], out)


def placeholder_terms() -> dict[str, list[str]]:
    """battinfo: placeholder term -> the record keys that alias it.

    Sourced from BOTH the records context and the LinkML schema. The context
    alone is not the whole surface: assemble_context.py drops internal
    prefixed slot names (ci_, ts_, ct_, ...) from the emitted context, so
    schema-declared terms like battinfo:batchId never appeared as placeholders
    even though the generated models and the published schema both carry them.
    Every battinfo: IRI that exists anywhere must dereference here.
    """
    out: dict[str, list[str]] = {}

    # Both the working context and every frozen published context. Retiring a
    # term from the working context (because an upstream EMMO class finally
    # landed) must not un-publish its IRI: documents minted against v1 still
    # expand to battinfo:<term>, so w3id.org/battinfo/<term> has to keep
    # dereferencing for as long as that context version is served.
    for path in (CONTEXT, PUBLISHED_CONTEXT):
        if not path.exists():
            continue
        context = json.loads(path.read_text(encoding="utf-8"))["@context"]
        _collect_context_aliases(context, out)

    for path in sorted(SCHEMA_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for block, uri_key in (("slots", "slot_uri"), ("classes", "class_uri")):
            for name, defn in (data.get(block) or {}).items():
                if not isinstance(defn, dict):
                    continue
                iri = defn.get(uri_key)
                if isinstance(iri, str) and iri.startswith("battinfo:"):
                    keys = out.setdefault(iri[len("battinfo:") :], [])
                    if name not in keys:
                        keys.append(name)
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
    revived = sorted((set(placeholders) | set(RESIDUE)) & set(RETIRED))
    if revived:
        raise SystemExit(
            f"gen_battinfo_vocab: term(s) {revived} are both current and RETIRED. "
            "A term the code uses again is current: take it out of RETIRED."
        )
    rogue_dynamic = dynamic_files - DYNAMIC_MINT_FILES
    if rogue_dynamic:
        raise SystemExit(
            "gen_battinfo_vocab: unsanctioned dynamic battinfo: mint (f-string) "
            f"in: {sorted(rogue_dynamic)}. BattINFO never generates class or "
            "property names; map the key to an EMMO class instead."
        )


def label_of(term: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", term.replace("_", " "))
    return words[0].upper() + words[1:]


def _kind(term: str) -> str:
    return "owl:Class" if term[0].isupper() else "rdf:Property"


def build() -> str:
    placeholders = placeholder_terms()
    check_honesty(placeholders)
    lines = [
        "# GENERATED by scripts/gen_battinfo_vocab.py - do not edit.",
        "# battinfo: (slash) - closed inventory of placeholder terms awaiting",
        f"# upstream EMMO terms, plus a hand-curated residue (currently {len(RESIDUE)}),",
        f"# and {len(RETIRED)} retired terms, kept as owl:deprecated.",
        "# battinfo: never carries domain semantics (IDENTIFIER_POLICY.md s.14);",
        "# the placeholder block may only SHRINK as upstream EMMO releases drain",
        "# it. Unmapped-property fallback terms (warned at emit time as",
        "# semantic.property_unmapped) are ad hoc and intentionally not declared.",
        "# There is no ns# (hash) section: served artifacts expand against real",
        "# vocabularies and this slash inventory only.",
        "@prefix battinfo: <https://w3id.org/battinfo/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "",
        f"<{ONTOLOGY_IRI}> a owl:Ontology ;",
        '    rdfs:label "BattINFO record-layer vocabulary"@en ;',
        '    rdfs:comment "Placeholder terms used by canonical BattINFO record '
        "exports (JSON-LD) while the corresponding EMMO domain terms are pending "
        "upstream. This is the record/data layer under the slash namespace; the "
        'EMMO-based application ontology lives in its own hash namespace."@en ;',
        "    dcterms:source <https://github.com/BIG-MAP/BattINFO> .",
        "",
    ]
    for term in sorted(placeholders):
        kind = _kind(term)
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
            f"    rdfs:isDefinedBy <{ONTOLOGY_IRI}> .",
            "",
        ]
    for term in sorted(RESIDUE):
        lines += [
            f"battinfo:{term} a {_kind(term)} ;",
            f'    rdfs:label "{label_of(term)}"@en ;',
            f'    rdfs:comment "{RESIDUE[term]}"@en ;',
            f"    rdfs:isDefinedBy <{ONTOLOGY_IRI}> .",
            "",
        ]
    for term in sorted(RETIRED):
        replacement = RETIRED[term]
        comment = (
            "Retired record-layer term, replaced by the term dcterms:isReplacedBy names"
            if replacement
            else "Retired record-layer term with no recorded replacement"
        ) + "; it stays declared because published records use it."
        lines += [
            f"battinfo:{term} a {_kind(term)} ;",
            f'    rdfs:label "{label_of(term)}"@en ;',
            f'    rdfs:comment "{comment}"@en ;',
            "    owl:deprecated true ;",
            *([f"    dcterms:isReplacedBy <{replacement}> ;"] if replacement else []),
            f"    rdfs:isDefinedBy <{ONTOLOGY_IRI}> .",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    n = len(placeholder_terms()) + len(RESIDUE)
    print(f"Wrote {OUT} ({n} battinfo: terms and {len(RETIRED)} retired ones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
