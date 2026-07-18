# Glossary — the vocabulary, in plain language

Two sentences per term, no prerequisites. For the full story behind any of
them, follow the link at the end of the entry.

**Linked Data**
: Data published so that every thing (a cell, a material, a test) has a web
  address, and records point at each other by those addresses instead of by
  ambiguous names. It is what lets someone else's software follow your
  cell → test → dataset chain without guessing.

**IRI**
: The web address that names one record, e.g.
  `https://w3id.org/battinfo/cell/gm6p-mrc6-p6cc-0m18` — an
  internationalized URL used as a permanent identifier. BattINFO IRIs never
  change and never get reused, so they are safe to print on a cell wrapper or
  cite in a paper ([Identifiers](../identifiers.md)).

**EMMO**
: The Elementary Multiperspective Material Ontology — a big, curated
  dictionary of science and engineering concepts, each with a formal
  definition and an IRI. BattINFO uses its battery and electrochemistry
  branches so that "capacity" in your record means exactly the same thing as
  in everyone else's.

**Ontology**
: A machine-readable dictionary plus the rules relating its terms ("a coin
  cell *is a* battery cell"). Software uses it to reason about your records;
  you mostly never touch it directly.

**JSON-LD**
: Ordinary JSON with a small `@context` block that maps its keys to ontology
  IRIs — human-readable and machine-interpretable at once. BattINFO generates
  it from your records automatically; you author plain JSON or Python.

**RDF**
: The underlying data model of Linked Data: every fact is a triple
  (*subject – property – value*), and a pile of triples forms a graph.
  JSON-LD is one way of writing RDF down; Turtle is another.

**SPARQL**
: The query language for RDF graphs — SQL's cousin for linked records. It is
  what makes questions like "all datasets from NMC811 cells cycled at 45 °C"
  answerable across datasets that have never seen each other.

**spec vs. instance**
: A *spec* is a reusable description — the datasheet: a material grade, a
  cell product, a test protocol. An *instance* is one physical realization —
  this jar of powder, the cell labelled B7-01, the test run that finished
  Tuesday.

**descriptor**
: The research-grade level of a cell spec: electrode composition,
  electrolyte formulation, separator, construction — the detail below the
  datasheet numbers ({doc}`Guide 5 <../guides/05-descriptors>`).

**@type stacking**
: One record carrying several ontology classes at once: a cylindrical LFP
  cell is simultaneously a `BatteryCell`, a `CylindricalBattery`, and a
  `LithiumIronPhosphateBattery`. BattINFO stacks these automatically from
  the format and chemistry you enter.

**SHACL**
: A rule language for checking RDF graphs — the semantic layer's
  counterpart of JSON Schema. One of the layers behind
  `validate_record_report` ([validation contract](../validation-contract.md)).

**content negotiation**
: One IRI, several representations: the same address returns JSON-LD to a
  script asking for `application/ld+json` and a human web page to a browser.
  This is why an IRI can "open a sign-in page" for you but still serve data
  to machines ([troubleshooting](troubleshooting.md)).

**BDF**
: Battery Data Format — the one tidy, documented table layout that every
  cycler export is converted into (`ws.convert()` /
  `ws.convert_csv()`), so downstream tools read one format instead of ten.

**short ID**
: The first six characters of a record's UID (e.g. `gm6pmr`) — the
  handwriting-sized version of an IRI, used in filenames and on cell labels
  ([Label your cells](../howto/label-your-cells.md)).
