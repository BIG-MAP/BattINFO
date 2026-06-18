# Dereferenceability requirements (gold-standard Tier 1c)

A linked-data record is only "gold standard" if its IRIs **resolve** — the
"follow your nose" principle. The published `battinfo.json` / `battinfo.publish.jsonld`
is structurally complete, but several IRIs it emits do not currently dereference to
machine-readable content. These are **registry / hosting** tasks (outside the BattINFO
Python package); this file records what must be served and the status as probed
2026-06-15.

## Status (probed 2026-06-15)

| IRI / resource | Result | Required |
|---|---|---|
| `w3id.org/battinfo/spec/<id>` (cell specs, test specs) | ⚠ 302 → `battery-genome.org/auth/sign-in` (HTML login) | Content-negotiated JSON-LD for **published** records (public read), or a public landing page with embedded JSON-LD |
| `w3id.org/battinfo/cell|dataset|test/<id>` | ⚠ 302 → login (HTML) | Same as above |
| `w3id.org/battinfo/context/records/v1.json` (the records `@context`) | ✗ 404 | Serve `src/battinfo/data/context/records.context.json` at this stable URL |
| `w3id.org/battinfo/` (namespace) | ✓ 200 → BattINFO ontology TTL | OK — but must also define the locally-minted `battinfo:` terms below |
| `w3id.org/emmo/domain/battery/context` (EMMO) | ✓ 200 JSON | OK (external) |
| `interop-mappings.ttl` (equivalence axioms) | ✗ not published | Serve at a stable `battinfo:` URL and reference from the ontology |

## What the registry must serve for the data IRIs

The cell-spec **stub** in every record asserts `rdfs:isDefinedBy <spec-IRI>`; that link
is worthless unless `<spec-IRI>` returns the spec. Minimum bar:

1. **Public, content-negotiated resolution** of `spec/`, `cell/`, `dataset/`, `test/`
   IRIs for records that have been **published** (an `Accept: application/ld+json`
   request returns the record's JSON-LD; a browser gets a human landing page).
   Auth-gating published, citable records breaks every external consumer and agent.
2. The published **records context** at `…/context/records/v1.json` (and ideally a
   versioned + `latest` alias), byte-equal to the inlined context.
3. The **ontology + interop mappings** (`assets/ontology/interop-mappings.ttl`)
   published under the namespace and `owl:imports`/referenced by the BattINFO ontology.

## Locally-minted `battinfo:` terms needing a dereferenceable definition

These have no EMMO/electrochemistry equivalent yet and are minted under the `battinfo:`
namespace. Each needs an `rdfs:label`/`rdfs:isDefinedBy` definition served from the
namespace (ideally promoted into the BattINFO ontology), or migration to an EMMO class
if one exists:

```
battinfo:capacityFade                 battinfo:powerCapability
battinfo:capacityThresholdExhaustion  battinfo:powerDensity
battinfo:chargingTime                 battinfo:powerEnergyRatio
battinfo:citationDOI                  battinfo:retrievedAt
battinfo:cycleLifeCRate               battinfo:roundTripEnergyEfficiency
battinfo:maximumPower                 battinfo:roundTripEnergyEfficiency50Pct
battinfo:operatingTemperatureMax      battinfo:sourceFile
battinfo:operatingTemperatureMin      battinfo:sourceType / sourceURL
battinfo:specificPower                battinfo:workflowVersion
```

## Unit IRI verification (Tier 2 follow-up)

Quantities now use a single EMMO serialization (`hasNumericalPart`/`hasNumericalValue`/
`hasMeasurementUnit`) in both the published record and the SHACL validation view — the
QUDT `qudt:value`/`qudt:unit` schema is fully retired. The remaining unit-IRI work is
dereference-verification against the pinned EMMO/QUDT releases (same class as the IRI
resolution above — needs the ontologies, not doable offline):

| Unit class | IRI source | Status |
|---|---|---|
| Base units (`V`, `A`, `Ah`, `W`, `g`, `mm`, `degC`, …) | `emmo:<Label>` (e.g. `emmo:Volt`) and some opaque `emmo:EMMO_…` | curated; validate the readable-IRI forms resolve in the pinned EMMO release |
| `Wh/kg`, `Wh/L` | `emmo:WattHourPerKilogram` / `…PerLitre` | curated; confirm against EMMO |
| `W/kg` | `qudt:W-PER-KiloGM` (EMMO core lacks it) | curated QUDT fallback |
| `W/L` | `qudt:W-PER-L` (EMMO core lacks it) | **added now, confidence 0.9 — confirm the exact QUDT code dereferences** |

Action: load the pinned `domain-electrochemistry`/EMMO + QUDT vocab and confirm each
`unit_iri` in `assets/mappings/domain-battery/unit_map.curated.json` resolves; promote
`W/L` to confidence 1.0 (or correct the code) once checked.

## Acceptance check

A small probe (`requests.get` with an RDF `Accept` header) over one of each IRI type
should return RDF (not HTML login), and the records context URL should return the
inlined context. Re-run after the registry exposes public resolution.
