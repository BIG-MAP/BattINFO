# Anatomy of a published BattINFO record (`battinfo.json`)

A published record is a single JSON-LD document: an inlined `@context` plus a `@graph`
of typed nodes. It is designed so a consumer fluent in **any one** of schema.org, DCAT,
PROV, EMMO, or DQV/EARL can traverse it end-to-end. This page maps the vocabularies,
the node types, and how to follow the links.

## The node graph at a glance

```text
dcat:Catalog (the deposit)          ── the DOI, title, licence, creators, publisher, keywords, version
 ├─ dcat:dataset / schema:hasPart ─▶ dcat:Dataset (one per test result)
 │                                    ├─ dcat:distribution ─▶ dcat:Distribution (downloadURL, checksum)
 │                                    ├─ schema:distribution ─▶ schema:DataDownload (contentUrl, sha256)  ← schema.org mirror
 │                                    └─ schema:about ─▶ BatteryCell
 ├─ BatteryCellSpecification          ── the cell spec (catalogue facts; the described battery with its hasProperty quantities rides isDescriptionFor), or a typed stub if remote
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
| Battery domain | **EMMO / domain-battery / -electrochemistry** | `BatteryCell`, `BatteryCellSpecification`, `BatteryTest`, `hasProperty`, `hasNumberValue`, `hasMeasurementUnit` |
| Quality / conformance | **DQV + W3C EARL + OA** | `dqv:hasQualityAnnotation`, `earl:outcome` (`earl:passed/failed/cantTell`), `oa:motivatedBy` |
| Integrity | **SPDX** | `spdx:checksum` (`spdx:checksumAlgorithm`, `spdx:checksumValue`) |
| Identifiers / dates | **dcterms / xsd** | `dcterms:license/isPartOf/conformsTo/isVersionOf`, typed dates (`xsd:gYearMonth`) |

Cross-vocabulary equivalences (e.g. `hasOutput ≡ prov:generated`,
`dcat:downloadURL ≡ schema:contentUrl`) are declared once in
`assets/ontology/interop-mappings.ttl`; the mirror triples in the data are generated
from one source so they cannot drift.

## Quantities

Every quantity (capacity, voltage, …) uses **one** EMMO encoding in this graph, in `battinfo.record_to_jsonld` output and in the SHACL shapes that check them:

```json
"hasProperty": [{ "@type": "NominalVoltage",
                  "hasNumericalPart": { "@type": "RealData", "hasNumberValue": 3.0 },
                  "hasMeasurementUnit": { "@id": "emmo:Volt" } }]
```

Every unit IRI is an EMMO or domain-electrochemistry class from the pinned closure, compound units such as `W/kg` included. A unit with no IRI in the unit map is kept as text in `schema:unitText`.

The records contexts type `hasNumberValue` as `xsd:double`, so it only ever holds a number. A `value` written as a string that is not a number, such as `"about 500"`, is published as text in `hasStringValue`, as `value_text` is; when the quantity has a `value_text` as well, only the `value_text` is published. A quantity given as a range keeps both bounds on the same node, as `schema:minValue` and `schema:maxValue`. Where the class names a bound, such as `MaximumPulseChargingCurrent`, a bound given alone is also the `hasNumberValue`. Every percent spelling is the unit `PercentUnit`; `wt%` and `vol%` add `WeightPercent` or `VolumePercent` as an extra class of the node, and a porosity or a mass or volume fraction is a fraction of 1 with `UnitOne`.

A unit with no IRI in the unit map, such as `years` for a calendar life, is written as text only, as `schema:unitText` with no `hasMeasurementUnit`. Validation warns `semantic.unit_unmapped` when this happens in a record's `properties` or in the `property` map of a material, material-spec, electrode or electrode-spec record. Units elsewhere, such as those of test conditions, `conditions` maps and the components of a cell spec, are not checked for an IRI.

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
handled by the BattINFO registry deployment. What a record's IRI serves today is the record body expanded with the records context, not the graph this page describes; see the [known limitations](scope.md#known-limitations-in-080).

## Round-trip fidelity (`ws.import_`)

`import_()` reconstructs the **structural core** — cell specs, cell instances, tests
(kind, protocol name, instrument), datasets and distributions — losslessly.
Every record keeps the IRI it was published under, and a test that produced several data files comes back as one test with one dataset per file. A dataset that several tests list as an output comes back once, related to each of them.

**Not restored on import** (the published graph is the source of truth; re-importing then
re-publishing would drop these): conformance/quality annotations (`dqv`/`earl` +
deviations), the catalog's creators/publisher/keywords/version, the structured test
conditions, and test spec records (a test keeps its protocol name, not its link to the spec). Treat `battinfo.bundle.json` (the `ZenodoCellRecord`) as the lossless
round-trip artifact; `battinfo.json` is the semantic-web view. (Closing this gap is a
tracked enhancement.)

A cell spec's format, chemistry, IEC code and cell configuration come back from the classes of its described battery, and its electrode bases from the classes of its electrode nodes. The chemistry is the first class the chemistry vocabulary names, which is the declared chemistry's. A deposit written before 0.8.0 also carries classes its electrode bases added whatever the chemistry, such as `LithiumManganeseDioxideBattery` on an alkaline cell, and those are not read as its chemistry. A specific NMC grade comes back as `nmc`, since all grades share one electrode class. A property's bounds come back as `min_value` and `max_value`, and a percent unit as `wt%` or `vol%` when its node carries `WeightPercent` or `VolumePercent`. A chemistry written as free text names no class, so it cannot come back: when the class read in its place contradicts the negative electrode, the import prints a warning and the strict save refuses the record until the chemistry is set.

A test whose cell the deposit only points at (a "defined elsewhere" stub for a cell published in the registry) is not imported, nor are its datasets. They are listed under `skipped` in the counts `import_()` returns, each with its cell and the reason, and the counts of tests and datasets say how many were imported.

The document may come from anyone, so `import_()` keeps only http(s) download URLs. A distribution whose download URL is a `file:` URL or a path, on this computer or another one, is left out with a warning, and a later `ws.zenodo()` of the workspace never reads a file the document named. A dataset left without a file keeps the http(s) page the deposit gives it as its `access_url`, and its notes say which URL was left out. A Zenodo token passed as `token=` goes only over https to the Zenodo host, never to another host and never on a redirect.
