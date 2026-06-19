"""
Assemble records.context.json from the LinkML YAML schema files.

This script extracts every `slot_uri:` mapping from the schema/*.yaml modules
and merges it with the curated unit-symbol → EMMO-IRI table to produce the
authoritative JSON-LD context at:
  src/battinfo/data/context/records.context.json

Usage:
  python scripts/assemble_context.py            # write the file
  python scripts/assemble_context.py --check    # exit non-zero if file is stale

The script is intentionally linkml-generator-free (just PyYAML) so it never
conflicts with linkml-runtime's built-in prefix declarations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
OUT_PATH = REPO_ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"

# ── Namespace prefixes emitted verbatim into @context ─────────────────────────
# https://schema.org/ (not http) — we deliberately override linkml's built-in.
PREFIXES: dict[str, str] = {
    "battery":          "https://w3id.org/emmo/domain/battery#",
    "electrochemistry": "https://w3id.org/emmo/domain/electrochemistry#",
    "emmo":             "https://w3id.org/emmo#",
    "battinfo":         "https://w3id.org/battinfo/",
    "schema":           "https://schema.org/",
    "dcterms":          "http://purl.org/dc/terms/",
    "prov":             "http://www.w3.org/ns/prov#",
    "dcat":             "http://www.w3.org/ns/dcat#",
    "dqv":              "http://www.w3.org/ns/dqv#",
    "oa":               "http://www.w3.org/ns/oa#",
    "earl":             "http://www.w3.org/ns/earl#",
    # No QUDT prefixes: quantities use ONE EMMO serialization
    # (hasNumericalPart/hasNumericalValue/hasMeasurementUnit) in both the published
    # battinfo.json and the SHACL validation view. The few compound-unit IRIs sourced
    # from QUDT are emitted as full URLs, not via a prefix.
    "spdx":             "http://spdx.org/rdf/terms#",
    "rdfs":             "http://www.w3.org/2000/01/rdf-schema#",
    "xsd":              "http://www.w3.org/2001/XMLSchema#",
}

# ── EMMO battery class types ───────────────────────────────────────────────────
CLASS_TYPES: dict[str, str] = {
    "BatteryCell":                         "battery:battery_68ed592a_7924_45d0_a108_94d6275d57f0",
    "BatteryCellSpecification":            "battery:battery_1cfbba6c_8824_4932_a23e_2141483acef7",
    "CylindricalBattery":                  "battery:battery_ac604ecd_cc60_4b98_b57c_74cd5d3ccd40",
    "PrismaticBattery":                    "battery:battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d",
    "PouchCell":                           "battery:battery_392b3f47_d62a_4bd4_a819_b58b09b8843a",
    "CoinCell":                            "battery:battery_b7fdab58_6e91_4c84_b097_b06eff86a124",
    "LithiumIonBattery":                   "battery:battery_96addc62_ea04_449a_8237_4cd541dd8e5f",
    "LithiumMetalBattery":                 "battery:battery_ada13509_4eed_4e40_a7b1_4cc488144154",
    "SodiumIonBattery":                    "battery:battery_42329a95_03fe_4ec1_83cb_b7e8ed52f68a",
    "AlkalineZincManganeseDioxideBattery": "battery:battery_b572826a_b4e4_4986_b57d_f7b945061f8b",
    "AlkalineCell":                        "battery:battery_50b911f7_c903_4700_9764_c308d8a95470",
    "PrimaryBattery":                      "battery:battery_3b0b0d6e_8b0e_4491_885e_8421d3eb3b69",
    "SecondaryBattery":                    "battery:battery_efc38420_ecbb_42e4_bb3f_208e7c417098",
    "BatteryTest":                         "battery:battery_dca7729a_421a_4921_90cf_9692bb9eb081",
}

# ── EMMO object properties (IRIs verified against EMMO release used in ws.py) ─
# Link-type properties use {"@id": ..., "@type": "@id"} so JSON-LD processors
# treat their values as IRI references rather than plain strings.
EMMO_OBJECT_PROPERTIES: dict[str, object] = {
    "hasProperty": {
        "@id":   "emmo:EMMO_e1097637_70d2_4895_973f_2396f04fa204",
        "@type": "@id",
    },
    "hasNumericalPart": {
        "@id":   "emmo:EMMO_8ef3cd6d_ae58_4a8d_9fc0_ad8f49015cd0",
        "@type": "@id",
    },
    # hasNumberValue is EMMO's canonical prefLabel (and what bmgen emits); we emit it.
    # hasNumericalValue is the altLabel for the SAME IRI — kept so older published
    # documents that used it still resolve on read.
    "hasNumberValue": "emmo:EMMO_faf79f53_749d_40b2_807c_d34244c192f4",
    "hasNumericalValue": "emmo:EMMO_faf79f53_749d_40b2_807c_d34244c192f4",
    "hasMeasurementUnit": {
        "@id":   "emmo:EMMO_bed1d005_b04e_4a90_94cf_02bc678a8569",
        "@type": "@id",
    },
    "isDescriptionFor": {
        "@id":   "emmo:EMMO_f702bad4_fc77_41f0_a26d_79f6444fd4f3",
        "@type": "@id",
    },
    "hasDescription": {
        "@id":   "emmo:EMMO_c58c799e_cc6c_4310_a3f1_78da70705b2a",
        "@type": "@id",
    },
    "hasTestObject": {
        "@id":   "battery:battery_da3b3f28_aaad_4d67_b674_df47e109fb8b",
        "@type": "@id",
    },
    "hasTestEquipment": {
        "@id":   "battery:battery_df4ff8f1_2cf2_444a_9498_23f533bd295c",
        "@type": "@id",
    },
    "hasOutput": {
        "@id":   "emmo:EMMO_c4bace1d_4db0_4cd3_87e9_18122bae2840",
        "@type": "@id",
    },
}

# ── Schema.org common property aliases ────────────────────────────────────────
# The bare `value`/`unit` aliases are intentionally NOT declared: neither
# serialization uses them. The published battinfo.json uses EMMO hasNumericalValue
# / hasMeasurementUnit; the validation view emits qudt:value / qudt:unit directly
# (compact form, via the qudt prefix), never the bare aliases.
COMMON_PROPERTY_ALIASES: dict[str, object] = {
    "name":         "schema:name",
    "model":        "schema:model",
    "manufacturer": "schema:manufacturer",
}

# ── Curated unit symbol → EMMO IRI table ──────────────────────────────────────
# IMPORTANT: term keys here MUST NOT contain "/" (or ":"). JSON-LD 1.1 treats any
# term whose key has the form of an IRI (i.e. contains "/") as one that MUST expand
# to its own definition; a compound-unit symbol like "Wh/kg" does not, so a strict
# 1.1 processor rejects the ENTIRE context with:
#   "Invalid JSON-LD syntax; term in form of IRI must expand to definition."
# Compound units (Wh/kg, Wh/L, W/kg, W/L, 1/h, …) are therefore intentionally NOT
# defined as symbol terms. They remain fully representable because:
#   1. quantity nodes always emit the unit as an explicit IRI reference
#      (hasMeasurementUnit / qudt:unit -> {"@id": "emmo:WattHourPerKilogram"}),
#      never as a bare @vocab symbol string; and
#   2. ws.py adds slash-free EMMO prefLabel aliases (WattHourPerKilogram, …) to the
#      embedded context from unit_map.curated.json.
UNIT_SYMBOLS: dict[str, str] = {
    "V":      "emmo:Volt",
    "mV":     "emmo:MilliVolt",
    "kV":     "emmo:KiloVolt",
    "Ah":     "emmo:AmpereHour",
    "mAh":    "emmo:MilliAmpereHour",
    "A":      "emmo:Ampere",
    "mA":     "emmo:MilliAmpere",
    "W":      "emmo:Watt",
    "kW":     "emmo:KiloWatt",
    "Wh":     "emmo:WattHour",
    "kWh":    "emmo:KiloWattHour",
    "MWh":    "emmo:MegaWattHour",
    "Ohm":    "emmo:Ohm",
    "mOhm":   "emmo:MilliOhm",
    "mohm":   "emmo:MilliOhm",
    "degC":   "emmo:EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc",
    "K":      "emmo:Kelvin",
    "g":      "emmo:Gram",
    "kg":     "emmo:Kilogram",
    "mg":     "emmo:MilliGram",
    "mm":     "emmo:MilliMetre",
    "cm":     "emmo:CentiMetre",
    "m":      "emmo:Metre",
    "L":      "emmo:Litre",
    "mL":     "emmo:MilliLitre",
    "cm3":    "emmo:CubicCentiMetre",
    "h":      "emmo:Hour",
    "min":    "emmo:Minute",
    "s":      "emmo:Second",
    "C":      "emmo:CoulombUnit",
    "1":      "emmo:EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978",
    "%":      "emmo:Percent",
}

# ── Provenance/DCAT typed terms ────────────────────────────────────────────────
TYPED_TERMS: dict[str, object] = {
    "license":        {"@id": "dcterms:license",   "@type": "@id"},
    "created_at":     {"@id": "dcterms:created",   "@type": "xsd:integer"},
    "modified_at":    {"@id": "dcterms:modified",  "@type": "xsd:integer"},
    # Note: cell production/expiry are emitted directly as typed schema:productionDate
    # / schema:expires values (xsd:gYearMonth), so no extra aliases are declared here.
}


def _compact_iri(raw_uri: str, prefixes: dict[str, str]) -> str:
    """Convert a full IRI to a compact prefix:local form, or return as-is."""
    for prefix, base in sorted(prefixes.items(), key=lambda kv: -len(kv[1])):
        if raw_uri.startswith(base):
            return f"{prefix}:{raw_uri[len(base):]}"
    return raw_uri


def _expand_slot_uri(slot_uri: str, local_prefixes: dict[str, str]) -> str:
    """Expand a compact IRI from the schema's own prefix map."""
    if ":" not in slot_uri:
        return slot_uri
    prefix, local = slot_uri.split(":", 1)
    base = local_prefixes.get(prefix)
    if base:
        return f"{base}{local}"
    return slot_uri


def _collect_prefixes_recursive(data: dict) -> dict[str, str]:
    """Walk YAML data and collect all prefix declarations."""
    prefixes: dict[str, str] = {}
    if isinstance(data, dict):
        if "prefixes" in data and isinstance(data["prefixes"], dict):
            prefixes.update(data["prefixes"])
        for v in data.values():
            prefixes.update(_collect_prefixes_recursive(v))
    return prefixes


def extract_slot_iris(schema_dir: Path) -> dict[str, str]:
    """
    Parse all *.yaml files in schema_dir and return a mapping of
    slot_name → compact IRI (using the global PREFIXES table).
    """
    # We need all prefix declarations across all files to expand compact IRIs.
    all_local_prefixes: dict[str, str] = {}
    all_slots: dict[str, str] = {}

    yaml_files = list(schema_dir.glob("*.yaml"))

    # First pass: collect all prefix declarations.
    for path in yaml_files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        raw_prefixes = data.get("prefixes", {})
        if isinstance(raw_prefixes, dict):
            all_local_prefixes.update(raw_prefixes)

    # Add our canonical prefixes to the lookup table.
    all_local_prefixes.update(PREFIXES)

    # Second pass: extract slot_uri declarations.
    for path in yaml_files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        slots_block = data.get("slots", {})
        if not isinstance(slots_block, dict):
            continue
        for slot_name, slot_def in slots_block.items():
            if not isinstance(slot_def, dict):
                continue
            raw_uri = slot_def.get("slot_uri")
            if not raw_uri:
                continue
            # Expand any compact IRI using all local prefixes.
            expanded = _expand_slot_uri(raw_uri, all_local_prefixes)
            # Re-compact against our canonical PREFIXES table.
            compact = _compact_iri(expanded, PREFIXES)
            # Use the slot name (snake_case) as the JSON-LD key.
            all_slots[slot_name] = compact

    return all_slots


def build_context(schema_dir: Path) -> dict:
    """Assemble the full @context dict."""
    slot_iris = extract_slot_iris(schema_dir)

    # Remove slots that would shadow the explicit common-property aliases.
    for key in list(COMMON_PROPERTY_ALIASES):
        slot_iris.pop(key, None)

    # Also remove internal prefixed-name slots (sv_*, ci_*, ct_*, etc.) —
    # these are implementation names; only the semantic slot_uri values matter.
    # We keep all snake_case slots that have an EMMO/external IRI.
    keep = {}
    skip_prefixes = {
        "sv_", "ci_", "ct_", "ts_", "t_", "tc_", "dev_",
        "ds_", "dd_", "cs_", "poo_", "org_",
    }
    for slot_name, iri in slot_iris.items():
        if any(slot_name.startswith(p) for p in skip_prefixes):
            continue
        keep[slot_name] = iri

    ctx: dict = {"@version": 1.1}
    ctx.update(PREFIXES)
    ctx.update(CLASS_TYPES)
    ctx.update(COMMON_PROPERTY_ALIASES)
    ctx.update(EMMO_OBJECT_PROPERTIES)
    ctx.update(keep)
    ctx.update(UNIT_SYMBOLS)
    ctx.update(TYPED_TERMS)

    # Guard: a term key in the form of an IRI (contains "/" or ":") must expand to
    # its own definition under JSON-LD 1.1, otherwise a strict processor rejects the
    # whole context. None of our terms do, so forbid such keys outright. Namespace
    # prefixes (whose value is the base IRI) are exempt — they are the definition.
    offenders = [
        k for k, v in ctx.items()
        if not k.startswith("@")
        and k not in PREFIXES
        and ("/" in k or ":" in k)
    ]
    if offenders:
        raise ValueError(
            "JSON-LD 1.1 forbids term keys in the form of an IRI "
            f"(containing '/' or ':'): {sorted(offenders)}. "
            "Define such units/terms by a slash-free alias instead."
        )

    return {"@context": ctx}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if the file is up-to-date; exit 1 if stale.",
    )
    args = parser.parse_args()

    new_context = build_context(SCHEMA_DIR)
    new_text = json.dumps(new_context, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT_PATH.exists():
            print(f"STALE: {OUT_PATH} does not exist", file=sys.stderr)
            return 1
        current = OUT_PATH.read_text(encoding="utf-8")
        if current == new_text:
            print("OK: records.context.json is up-to-date")
            return 0
        # Show which keys differ.
        cur_ctx = json.loads(current).get("@context", {})
        new_ctx = new_context.get("@context", {})
        added = set(new_ctx) - set(cur_ctx)
        removed = set(cur_ctx) - set(new_ctx)
        changed = {k for k in cur_ctx if k in new_ctx and cur_ctx[k] != new_ctx[k]}
        print("STALE: records.context.json differs from schema:", file=sys.stderr)
        if added:
            print(f"  + added   : {sorted(added)}", file=sys.stderr)
        if removed:
            print(f"  - removed : {sorted(removed)}", file=sys.stderr)
        if changed:
            print(f"  ~ changed : {sorted(changed)}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(new_text, encoding="utf-8")
    print(f"Written: {OUT_PATH}")
    # Report stats.
    ctx = new_context["@context"]
    n_prefixes = sum(1 for k, v in ctx.items() if isinstance(v, str) and v.endswith(("/", "#")))
    n_props = sum(1 for k, v in ctx.items() if isinstance(v, str) and not v.endswith(("/", "#")))
    n_typed = sum(1 for v in ctx.values() if isinstance(v, dict))
    print(f"  {n_prefixes} namespace prefixes, {n_props} property IRIs, {n_typed} typed terms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
