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
      (data/context/records.context.json) AND every battinfo: slot_uri/class_uri
      declared in schema/*.yaml. Each awaits an upstream EMMO term (step-6
      drain, gated on domain-battery/electrochemistry releases).
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

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
OUT = ROOT / "assets" / "vocab" / "battinfo-records.ttl"
CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"
# The frozen, hosted context. Its terms stay published forever, so its
# battinfo: aliases stay in the inventory even after the working context
# repoints them at an upstream EMMO class.
PUBLISHED_CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
SAVE_GATE = ROOT / "src" / "battinfo" / "data" / "schemas" / "cell-canonical.schema.json"
UNIT_MAP = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "unit_map.curated.json"
PROPERTY_MAP = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "property_map.curated.json"

# The hash namespace served records EXPAND against (@vocab in the registry
# wrapper context). Distinct from the slash namespace above: the slash form is
# the closed placeholder inventory; ns# is the term set that the served
# JSON-LD / Turtle representations actually use, generated below from the same
# records context (plus the save-gate quantity keys and the record envelope) so
# that every predicate/type a served record carries dereferences to a defining
# subject. See gen: _ns_terms().
NS = "https://w3id.org/battinfo/ns#"

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
        for key, value in context.items():
            iri = value.get("@id") if isinstance(value, dict) else value
            if isinstance(iri, str) and iri.startswith("battinfo:"):
                keys = out.setdefault(iri[len("battinfo:"):], [])
                if key not in keys:
                    keys.append(key)

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
                    keys = out.setdefault(iri[len("battinfo:"):], [])
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


# ── ns# vocabulary (the terms served records actually use) ────────────────────
# Records are served under `@vocab https://w3id.org/battinfo/ns#`, so every bare
# predicate/type in the served JSON-LD (and its Turtle projection) is an ns#
# IRI. This section GENERATES a defining subject for each, sourced from the same
# records context as the placeholders above (for the EMMO seeAlso links), plus
# the save-gate quantity keys and the record-envelope scaffolding, so nothing a
# served record carries is a dereference dead-end. No term is hand-authored as a
# raw triple: the inventory is computed.

_LOCALNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Record-type classes: the ``@type`` each BattINFO submission envelope stamps
# (api/_staging.build_submission_envelope, ws.py) -> the context class-label key
# whose EMMO IRI grounds it (None where no single EMMO class applies).
_NS_CLASSES: dict[str, str | None] = {
    "CellSpec": "BatteryCellSpecification",
    "BatteryCell": "BatteryCell",
    "TestSpec": None,
    "BatteryTest": "BatteryTest",
    "Dataset": None,
    # Material and electrode records became submittable alongside the five above;
    # their envelope @type needs a defining subject too, or a served record
    # dereferences to nothing. None throughout: the grounding classes live in the
    # domain-battery context, not the records context this generator reads, and a
    # key that resolves to nothing would be a mapping that only looks present.
    "MaterialSpec": None,
    "Material": None,
    "ElectrodeSpec": None,
    "Electrode": None,
}
# Registry Turtle projection spellings that MUST resolve to the same class as
# their canonical ns# sibling (documented divergence: the registry emits these
# instead of the JSON-LD @type). Kept as owl:equivalentClass so both dereference
# until the registry converges on the canonical spelling.
_NS_CLASS_ALIASES: dict[str, str] = {
    "CellSpecification": "CellSpec",
}

# Record-envelope / datasheet-scaffolding terms that carry no domain semantics
# (registry wrapper keys, quantity-node structure, provenance plumbing). Emitted
# verbatim in the spelling the served representations use.
_NS_SCAFFOLDING: dict[str, str] = {
    "schema_version": "Record schema version stamp.",
    "battinfo_records": "Wrapper holding the canonical BattINFO record body inside a served resource.",
    "cell_spec": "The cell-specification body of a served record.",
    "properties": "The quantitative property set of a served record.",
    "provenance": "Provenance block of a served record.",
    "brand": "Product brand of a cell specification.",
    "category": "Coarse product category of a cell specification.",
    "cell_format": "Physical cell format (snake-case record key).",
    "format": "Physical cell format (registry projection key).",
    "type": "Node type discriminator inside a served record.",
    "raw": "Provenance of an extracted datasheet value (source text / page / confidence).",
    "text": "Source text a datasheet value was extracted from.",
    "page": "Source page a datasheet value was extracted from.",
    "confidence": "Extraction-confidence score for a datasheet value.",
    "value": "Numeric value of a quantity node.",
    "value_text": "Verbatim text value of a quantity node (when not numeric).",
    "unit": "Measurement unit symbol of a quantity node.",
    "short_id": "Short human-facing identifier of a record.",
    "source_file": "Source file a record was extracted from.",
    "file_hash": "Content hash of a source or distribution file.",
    "metadata": "Registry-projected summary block of a served resource.",
    "distributions": "Data distributions attached to a served resource.",
    "relatedResources": "Related resources linked from a served resource.",
    "publisherId": "Identifier of the publishing agent (registry envelope).",
    "sourceLocalId": "Publisher-local identifier of the source record (registry envelope).",
    "sourceVersion": "Version stamp of the published source (registry envelope).",
    # Registry projection keys. Minted by battinfo-registry when it wraps a
    # record for serving (publishing/normalizers.py, publishing/display.py,
    # api/routes.py), so no battinfo schema declares them — but they are served
    # under this @vocab and so have to resolve.
    "canonical_iri": "Canonical IRI of a resource referenced from a served record (registry projection).",
    "relationship": "How a related resource stands to the record that links it (registry projection).",
    "resource_type": "Registry resource type of a referenced record (registry projection).",
    "record_url": "Landing-page URL of a served record (registry projection).",
    "manufacturer_id": "Canonical IRI of the manufacturer organization (registry projection).",
    "immutable": "Whether a distribution's bytes are guaranteed not to change (registry projection).",
    # Test-protocol summary block: computed by api/_records.py from the
    # protocol's steps rather than declared as schema properties, and carried
    # into the served record.
    "facets": "Computed summary facets of a test protocol.",
    "modes": "Control modes a test protocol uses, as a computed summary facet.",
    "control_modes": "Per-step control modes of a test protocol.",
    "directions": "Charge/discharge directions a test protocol covers, as a computed summary facet.",
    "c_rates": "C-rates a test protocol uses, as a computed summary facet.",
    "has_rest": "Whether a test protocol contains a rest step (computed summary facet).",
    "has_eis": "Whether a test protocol contains an impedance step (computed summary facet).",
    "has_cv_hold": "Whether a test protocol contains a constant-voltage hold (computed summary facet).",
    # Further registry projection keys, all appearing under the ``metadata``
    # block the registry composes per record type. They are not record fields:
    # the normalizer lifts and renames them for display, so the spelling is the
    # registry's and only this inventory can account for it.
    "contributors": "Contributor summary lifted into the registry metadata block.",
    "funding_identifier": "Grant identifier lifted into the registry metadata block.",
    "protocol": "Test-protocol reference lifted into the registry metadata block.",
    "conformance_note": "Conformance statement lifted into the registry metadata block.",
    "specification_note": "Specification remark lifted into the registry metadata block.",
    "processing_route": "Electrode processing route lifted into the registry metadata block.",
    "processing_solvent": "Electrode processing solvent lifted into the registry metadata block.",
    # These two are both a registry metadata key and a real test-condition key
    # in the record body (``test.conditions``). Declared so they resolve; they
    # carry no rdfs:seeAlso because the transform's measurement-parameter table
    # does not map them, which is an upstream grounding gap rather than
    # something to invent here.
    "ambient_temperature": "Ambient temperature a test was run at (test condition; also a registry metadata key).",
    "voltage_reference": "Reference electrode a test's voltages are quoted against "
    "(test condition; also a registry metadata key).",
}


def _to_camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _context_prefixes(ctx: dict) -> dict[str, str]:
    """Prefix declarations in the context (value is a bare namespace URI)."""
    out: dict[str, str] = {}
    for key, val in ctx.items():
        if key.startswith("@") or not isinstance(val, str):
            continue
        if (val.endswith("#") or val.endswith("/")) and "://" in val:
            out[key] = val
    return out


def _unit_symbols() -> set[str]:
    data = json.loads(UNIT_MAP.read_text(encoding="utf-8"))
    return {m["symbol"] for m in data.get("mappings", []) if m.get("symbol")}


def _save_gate_quantity_keys() -> list[str]:
    data = json.loads(SAVE_GATE.read_text(encoding="utf-8"))
    return list(data["$defs"]["SpecSet"]["properties"])


def _cell_spec_identity_keys() -> list[str]:
    """Cell-specification identity fields (product identity, not quantities)."""
    schema = ROOT / "src" / "battinfo" / "data" / "schemas" / "cell-spec.schema.json"
    data = json.loads(schema.read_text(encoding="utf-8"))
    return list(data["properties"]["cell_spec"].get("properties", {}))


def _curated_property_terms() -> dict[str, str]:
    """Component/datasheet property key -> the EMMO class the curation assigns.

    These keys (``loading``, ``dry_thickness``, ``areal_capacity``,
    ``mass_fraction``, ...) live in open property blocks, so no schema declares
    them and the two schema-shaped sources above cannot see them. The curated
    map is where their meaning is actually recorded, and it carries a real EMMO
    IRI — so they ground properly here rather than becoming bare stubs.

    Only ``curated`` rows: the candidate map is a proposal, not a commitment.
    """
    data = json.loads(PROPERTY_MAP.read_text(encoding="utf-8"))
    return {
        row["key"]: row["class_iri"]
        for row in data.get("mappings", [])
        if row.get("status") == "curated" and row.get("key") and row.get("class_iri")
    }


def _transform_property_terms(ctx: dict) -> dict[str, str | None]:
    """Emitter property key -> EMMO IRI, from the transform's own term tables.

    These keys live in open ``property`` blocks and test-condition blocks, so
    no schema declares them and the curated map does not carry them either.
    The transform is where their meaning is decided — it is the code that turns
    ``dry_thickness`` into ``DryCoatingThickness`` — so read the decision from
    there rather than restating it.

    The tables give an EMMO *term name*; the records context is what turns that
    into an IRI. A term the context does not carry still gets a defining
    subject, just without the ``seeAlso``: resolving is the requirement here,
    grounding is the bonus.
    """
    from battinfo.transform.json_to_jsonld import (
        _ASSEMBLY_QUANTITY_TERMS,
        _MEASUREMENT_PARAMETER_TERMS,
        COMPONENT_PROPERTY_TERM_TABLES,
    )

    out: dict[str, str | None] = {}
    tables = (*COMPONENT_PROPERTY_TERM_TABLES, _MEASUREMENT_PARAMETER_TERMS, _ASSEMBLY_QUANTITY_TERMS)
    for table in tables:
        for key, term in table.items():
            if _LOCALNAME_RE.match(key):
                out.setdefault(key, _context_iri(ctx.get(term)))
    return out


def _record_body_keys() -> list[str]:
    """Every property name declared by any record schema.

    The two functions above read the cell save-gate and the cell-spec identity
    block, which is the whole surface only for as long as a record *is* a cell.
    It stopped being true when datasets, tests, protocols, materials and
    electrodes became record types of their own: their body keys — ``contributor``,
    ``same_as``, ``funding``, ``loading``, ``variable_measured``, and 100-odd
    more — were served under ``@vocab`` with nothing at the other end, which is
    exactly the dead-end this section exists to prevent.

    So source the inventory from the schemas themselves. Every ``properties``
    block anywhere in any schema (top level, ``$defs``, nested objects) is a set
    of keys some record can carry, which is the same criterion the ``@vocab``
    fallback applies at serving time. Reading the shipped schema tree rather
    than a hand-kept list means a new record type arrives here on its own.
    """
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    keys: set[str] = set()

    def walk(node) -> None:  # noqa: ANN001 - arbitrary JSON Schema
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                keys.update(k for k in properties if _LOCALNAME_RE.match(k))
            for key, value in node.items():
                # "properties" is a key namespace, not a schema: recursing into
                # it as one would read a property literally named "type" or
                # "required" as a JSON Schema keyword.
                if key == "properties" and isinstance(value, dict):
                    for subschema in value.values():
                        walk(subschema)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in sorted(schema_root.rglob("*.schema.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return sorted(keys)


def _context_iri(value) -> str | None:
    iri = value.get("@id") if isinstance(value, dict) else value
    return iri if isinstance(iri, str) else None


def _context_property_terms(ctx: dict) -> dict[str, str]:
    """Context keys that are record predicates -> their mapped IRI.

    Excludes prefix declarations, unit symbols, and class-label aliases (which
    map to a battery: class and are never used as ns# predicates by records).
    """
    prefixes = set(_context_prefixes(ctx))
    units = _unit_symbols()
    out: dict[str, str] = {}
    for key, val in ctx.items():
        if key.startswith("@") or key in prefixes or key in units:
            continue
        if not _LOCALNAME_RE.match(key):
            continue
        iri = _context_iri(val)
        if iri is None or iri.startswith("battery:battery_") or iri.endswith(("#", "/")):
            continue
        out[key] = iri
    return out


def _ttl_iri(curie_or_url: str) -> str:
    """Render a context value as a Turtle object: CURIE as-is, else <full IRI>."""
    return f"<{curie_or_url}>" if "://" in curie_or_url else curie_or_url


def _ns_terms() -> tuple[list[dict], set[str]]:
    """Compute the ns# inventory.

    Returns (subjects, prefixes_used). Each subject dict has: name, kind
    (owl:Class / rdf:Property), label, and optional see_also / equivalent_of /
    equivalent_class / comment.
    """
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    props = _context_property_terms(ctx)
    quantity = set(_save_gate_quantity_keys())
    subjects: list[dict] = []
    seen: set[str] = set()
    prefixes: set[str] = set()

    def add(name: str, kind: str, **extra) -> None:
        if name in seen or not _LOCALNAME_RE.match(name):
            return
        seen.add(name)
        subjects.append({"name": name, "kind": kind, "label": label_of(name), **extra})
        for iri in (extra.get("see_also"),):
            if isinstance(iri, str) and "://" not in iri and ":" in iri:
                prefixes.add(iri.split(":", 1)[0])

    # Classes: canonical @type names + their EMMO grounding.
    for cls, emmo_key in _NS_CLASSES.items():
        see = _context_iri(ctx.get(emmo_key)) if emmo_key else None
        add(cls, "owl:Class", see_also=see)
    for alias, canonical in _NS_CLASS_ALIASES.items():
        emmo_key = _NS_CLASSES.get(canonical)
        see = _context_iri(ctx.get(emmo_key)) if emmo_key else None
        add(alias, "owl:Class", equivalent_class=canonical, see_also=see)

    # Property predicates from the records context, in both the snake-case
    # spelling the JSON-LD uses and the lowerCamelCase spelling the Turtle
    # projection uses; quantity keys additionally get a *_unit companion.
    def add_property(key: str, see: str | None, with_unit: bool = False) -> None:
        add(key, "rdf:Property", see_also=see)
        camel = _to_camel(key)
        if camel != key:
            add(camel, "rdf:Property", equivalent_of=key, see_also=see)
        if key in quantity or with_unit:
            add(f"{key}_unit", "rdf:Property", comment=f"Measurement unit of {key}.")
            camel_unit = f"{camel}Unit"
            add(camel_unit, "rdf:Property", equivalent_of=f"{key}_unit",
                comment=f"Measurement unit of {key}.")

    for key, iri in sorted(props.items()):
        add_property(key, iri)
    # Save-gate quantity keys not present in the context (datasheet keys with no
    # EMMO term yet) still appear in records and must resolve.
    for key in sorted(quantity - set(props)):
        add_property(key, None)
    # Cell-specification identity fields (chemistry, size_code, ... — not
    # quantities, so no unit companion); link to their context IRI where mapped.
    for key in sorted(_cell_spec_identity_keys()):
        if _LOCALNAME_RE.match(key):
            add_property(key, props.get(key))
    # Curated open-block property keys, grounded by the curation's own EMMO
    # class. Before the schema sweep, so these arrive with their grounding
    # rather than as bare stubs (`add` keeps the first spelling it sees).
    # Both carry quantities, so both get the `<key>_unit` companion the served
    # records pair every value with.
    curated = _curated_property_terms()
    for key in sorted(curated):
        add_property(key, curated[key], with_unit=True)
    transform_terms = _transform_property_terms(ctx)
    for key in sorted(transform_terms):
        add_property(key, transform_terms[key], with_unit=True)
    # Every remaining record-body key, from every record schema. `add` is
    # idempotent on `seen`, so the mapped and quantity keys handled above keep
    # their EMMO grounding and their unit companions; this pass only picks up
    # what nothing else claimed.
    for key in _record_body_keys():
        add_property(key, props.get(key))

    # Envelope / scaffolding, emitted verbatim.
    for name, comment in _NS_SCAFFOLDING.items():
        add(name, "rdf:Property", comment=comment)

    return subjects, prefixes


def _render_ns_section(subjects: list[dict]) -> list[str]:
    lines = [
        "",
        "# ── ns# record vocabulary (served @vocab) ────────────────────────────────",
        "# GENERATED (see scripts/gen_battinfo_vocab.py _ns_terms). The hash",
        "# namespace served records expand against. Every predicate/type a served",
        "# JSON-LD or Turtle record carries is defined here; domain terms link to",
        "# their EMMO grounding via rdfs:seeAlso. This section is a projection of",
        "# the records context and may be regenerated whenever the context changes.",
        "",
        "ns: a owl:Ontology ;",
        '    rdfs:label "BattINFO served-record vocabulary (ns#)"@en ;',
        '    rdfs:comment "Terms used by canonical BattINFO records as served under '
        "@vocab https://w3id.org/battinfo/ns#. Domain predicates carry an rdfs:seeAlso "
        'to their EMMO grounding; envelope terms are record plumbing."@en ;',
        "    dcterms:source <https://github.com/BIG-MAP/BattINFO> .",
        "",
    ]
    for s in subjects:
        lines.append(f"ns:{s['name']} a {s['kind']} ;")
        lines.append(f'    rdfs:label "{s["label"]}"@en ;')
        if s.get("comment"):
            lines.append(f'    rdfs:comment "{s["comment"]}"@en ;')
        if s.get("equivalent_class"):
            lines.append(f"    owl:equivalentClass ns:{s['equivalent_class']} ;")
        if s.get("equivalent_of"):
            lines.append(f"    owl:equivalentProperty ns:{s['equivalent_of']} ;")
        if s.get("see_also"):
            lines.append(f"    rdfs:seeAlso {_ttl_iri(s['see_also'])} ;")
        lines.append("    rdfs:isDefinedBy <https://w3id.org/battinfo/ns> .")
        lines.append("")
    return lines


def build() -> str:
    placeholders = placeholder_terms()
    check_honesty(placeholders)
    ns_subjects, ns_prefixes_used = _ns_terms()
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    ctx_prefixes = _context_prefixes(ctx)
    prefix_lines = [
        "@prefix battinfo: <https://w3id.org/battinfo/> .",
        f"@prefix ns: <{NS}> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
    ]
    for prefix in sorted(ns_prefixes_used):
        if prefix in {"battinfo", "owl", "rdf", "rdfs", "dcterms"}:
            continue
        if prefix in ctx_prefixes:
            prefix_lines.append(f"@prefix {prefix}: <{ctx_prefixes[prefix]}> .")
    lines = [
        "# GENERATED by scripts/gen_battinfo_vocab.py - do not edit.",
        "# Two record-layer namespaces:",
        "#   battinfo: (slash) - closed inventory of placeholder terms awaiting",
        "#     upstream EMMO terms, plus a hand-curated residue (currently "
        f"{len(RESIDUE)}).",
        "#   ns: (hash) - the terms served records expand against (@vocab), a",
        "#     GENERATED projection of the records context + save-gate + envelope",
        "#     so every served predicate/type dereferences here.",
        "# battinfo: never carries domain semantics (IDENTIFIER_POLICY.md s.14);",
        "# the placeholder block may only SHRINK as upstream EMMO releases drain",
        "# it. Unmapped-property fallback terms (warned at emit time as",
        "# semantic.property_unmapped) are ad hoc and intentionally not declared.",
        *prefix_lines,
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
    lines += _render_ns_section(ns_subjects)
    return "\n".join(lines)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    ns_subjects, _ = _ns_terms()
    n = len(placeholder_terms()) + len(RESIDUE)
    print(f"Wrote {OUT} ({n} battinfo: terms, {len(ns_subjects)} ns: terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
