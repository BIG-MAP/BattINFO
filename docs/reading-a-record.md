# How to read a published BattINFO record (`battinfo.json`)

A published record is a single JSON-LD document: an inlined `@context` plus a `@graph`
of typed nodes. It is designed so a consumer fluent in **any one** of schema.org, DCAT,
PROV, EMMO, or DQV/EARL can traverse it end-to-end. This guide maps the vocabularies,
the node types, and how to follow the links.

## The node graph at a glance

```
dcat:Catalog (the deposit)          ── the DOI, title, licence, creators, publisher, keywords, version
 ├─ dcat:dataset / schema:hasPart ─▶ dcat:Dataset (one per test result)
 │                                    ├─ dcat:distribution ─▶ dcat:Distribution (downloadURL, checksum)
 │                                    ├─ schema:distribution ─▶ schema:DataDownload (contentUrl, sha256)  ← schema.org mirror
 │                                    └─ schema:about ─▶ BatteryCell
 ├─ BatteryCellSpecification          ── the cell spec (EMMO classes + hasProperty quantities), or a typed stub if remote
 ├─ BatteryCell (one per cell)        ── conformsTo / hasDescription ─▶ the spec
 ├─ prov:Plan / schema:HowTo          ── the test protocol (+ structured conditions, see below)
 └─ BatteryTest / prov:Activity       ── hasTestObject ─▶ cell ; prov:used ─▶ cell+spec ; prov:generated / hasOutput ─▶ dataset
                                          dqv:hasQualityAnnotation ─▶ conformance (earl:outcome)
```

## Vocabulary map (one canonical vocab per concern)

| Concern | Vocabulary | Key terms |
|---|---|---|
| Packaging / catalog | **DCAT** (+ schema.org mirror) | `dcat:Catalog`, `dcat:dataset`, `dcat:distribution`, `dcat:downloadURL` |
| Discovery / rights | **schema.org** | `schema:DataCatalog/Dataset/DataDownload`, `name`, `description`, `license`, `creator`, `publisher`, `keywords`, `version` |
| Provenance | **PROV** | `prov:Activity`, `prov:Plan`, `prov:used`, `prov:generated`, `prov:wasGeneratedBy`, `prov:wasAttributedTo` |
| Battery domain | **EMMO / domain-battery / -electrochemistry** | `BatteryCell`, `BatteryCellSpecification`, `BatteryTest`, `hasProperty`, `hasNumericalValue`, `hasMeasurementUnit` |
| Quality / conformance | **DQV + W3C EARL + OA** | `dqv:hasQualityAnnotation`, `earl:outcome` (`earl:passed/failed/cantTell`), `oa:motivatedBy` |
| Integrity | **SPDX** | `spdx:checksum` (`spdx:checksumAlgorithm`, `spdx:checksumValue`) |
| Identifiers / dates | **dcterms / xsd** | `dcterms:license/isPartOf/conformsTo/isVersionOf`, typed dates (`xsd:gYearMonth`) |

Cross-vocabulary equivalences (e.g. `hasOutput ≡ prov:generated`,
`dcat:downloadURL ≡ schema:contentUrl`) are declared once in
`assets/ontology/interop-mappings.ttl`; the mirror triples in the data are generated
from one source so they cannot drift.

## Quantities

Every quantity (capacity, voltage, …) uses **one** EMMO encoding everywhere — published
record and SHACL validation alike:

```json
"hasProperty": [{ "@type": "NominalVoltage",
                  "hasNumericalPart": { "hasNumericalValue": 3.0 },
                  "hasMeasurementUnit": { "@id": "emmo:Volt" } }]
```

Unit IRIs are EMMO where defined; compound units EMMO lacks (`W/kg`, `W/L`) use QUDT.

## Structured test conditions

The test protocol node (`prov:Plan` / `schema:HowTo`) carries machine-readable
conditions as `schema:PropertyValue`s — not just prose — so they are queryable:

```json
"battinfo:cycles": 50,
"schema:additionalProperty": [
  { "@type": "schema:PropertyValue", "schema:name": "temperature",
    "schema:value": 25, "schema:unitText": "degC", "schema:propertyID": "conditions" },
  { "@type": "schema:PropertyValue", "schema:name": "cutoff_voltage",
    "schema:value": 0.9, "schema:unitText": "V", "schema:propertyID": "termination_criteria" }
]
```
`schema:propertyID` distinguishes `conditions` / `setpoints` / `termination_criteria`.

## "Follow your nose"

Every `@id` either resolves to a node in the document or is a typed stub pointing at the
authoritative resource (e.g. a remote `BatteryCellSpecification` with `rdfs:isDefinedBy`).
Registry IRI resolution (`w3id.org/battinfo/spec/…`) and the published context URL are
tracked in `dereferenceability.md`.

## Round-trip fidelity (`ws.import_`)

`import_()` reconstructs the **structural core** — cell specs, cell instances, tests
(kind, protocol name, instrument), datasets and distributions — losslessly.

**Not restored on import** (the published graph is the source of truth; re-importing then
re-publishing would drop these): conformance/quality annotations (`dqv`/`earl` +
deviations), the catalog's creators/publisher/keywords/version, and the structured test
conditions. Treat `battinfo.bundle.json` (the `ZenodoCellRecord`) as the lossless
round-trip artifact; `battinfo.json` is the semantic-web view. (Closing this gap is a
tracked enhancement.)
