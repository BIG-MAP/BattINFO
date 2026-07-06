// Shared editorial content for the marketing/reference pages.
// Kept here (not inline in JSX) so copy can be reviewed and reused across pages,
// the way schema.org / Gene Ontology keep a single coherent narrative.

// The author → validate → convert → publish pipeline. The four-verb spine of
// the whole project; shown on the home page and echoed by the two tools.
export const pipeline = [
  {
    verb: "Author",
    body: "Write plain, readable JSON — the same fields you already put on a datasheet or spec. No ontology expertise required.",
  },
  {
    verb: "Validate",
    body: "Check structure, references, and semantics against one contract-grade engine, with stable issue codes.",
  },
  {
    verb: "Convert",
    body: "A deterministic, mapping-driven transform emits canonical EMMO-aligned JSON-LD — and valid RDF.",
  },
  {
    verb: "Publish",
    body: "Get back a stable w3id.org/battinfo IRI. Your record is now Linked Data anyone can resolve and reuse.",
  },
] as const;

// Why BattINFO is trustworthy infrastructure, not a one-off schema.
export const features = [
  {
    title: "Ontology-aligned",
    body: "Every record is typed against EMMO domain-battery. BattINFO is the non-normative implementation layer; the ontology stays the source of truth.",
  },
  {
    title: "JSON-LD first",
    body: "Author plain JSON; publish valid RDF. A deterministic, mapping-table-driven transform produces canonical EMMO-aligned JSON-LD.",
  },
  {
    title: "Validated, multi-layer",
    body: "JSON Schema 2020-12, Pydantic, JSON-LD URDNA2015 normalisation, semantic rules, and referential integrity — not just shape-checking.",
  },
  {
    title: "Persistent identifiers",
    body: "Published entities carry stable, opaque w3id.org/battinfo/{type}/{uid} IRIs, governed by a published identifier policy.",
  },
] as const;

// Dual-audience framing, the Gene Ontology pattern: the same resource serves the
// people who describe batteries and the people who build tools, and says so.
export const audiences = [
  {
    who: "Engineers, designers & data owners",
    body: "Describe cells, builds, and tests in JSON you can read. Keep units explicit and provenance linked — and move data cleanly across teams, suppliers, and tools without learning RDF.",
    cta: { label: "Author your first record", href: "/docs#quickstart" },
  },
  {
    who: "Software & data teams",
    body: "A stable JSON Schema contract, a Python library and CLI, structured validation issue codes, and JSON-LD you can load into any database or triplestore.",
    cta: { label: "Read the schemas & API", href: "/docs#schemas" },
  },
] as const;

// The linked data model — record types and how they chain. Used on the home
// page and docs to show this is one coherent model, not a bag of schemas.
export const recordModel = [
  { type: "Cell spec", blurb: "An as-designed cell specification (a product / SKU)." },
  { type: "Cell", blurb: "A physical, individually-tracked cell of a spec." },
  { type: "Test", blurb: "A measurement performed on a cell under a protocol." },
  { type: "Dataset", blurb: "The data and files a test produced, with distributions." },
  { type: "Test spec", blurb: "The reusable procedure a test was run under." },
  { type: "Organization", blurb: "Manufacturers, labs, and publishers, as linked entities." },
] as const;

// The provenance chain, rendered as a single readable line.
export const provenanceChain = "Cell spec → Cell → Test → Dataset";

// The publishing journey — the five stages of turning raw cycler exports into
// citable, findable Linked Data. This is the spine of the /publish page and the
// homepage hero. Code lines are asserted against ws.quickstart() by
// tests/test_web_snippets.py so this page can never teach a different recipe
// than the library does.
export const publishJourney = [
  {
    stage: "Convert",
    verb: "ws.convert()",
    code: `ws.convert()          # NEWARE / Biologic / Excel auto-detected
ws.convert("*.csv")   # or force generic CSV exports`,
    produces: "bdf/*.bdf.csv — every cycler's export in one tidy, documented table format (BDF).",
    why: "Instrument formats are the first interoperability wall. One canonical table format means every later step — and every colleague — reads the same thing.",
  },
  {
    stage: "Identify",
    verb: "ws.search() + ws.add(\"cell\")",
    code: `spec = ws.search("molicel p45b")[0]
ws.add("cell", spec=spec, serial_numbers=["S1", "S2", "S3"])`,
    produces: "Cell records for the physical cells you tested, linked to a shared cell spec with a persistent IRI.",
    why: "Your measurements are about specific physical cells. Naming them once gives every test and dataset an unambiguous subject — the start of the provenance chain.",
  },
  {
    stage: "Link",
    verb: "ws.add(\"test\")",
    code: `ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")`,
    produces: "A test record tied to the cell, plus a dataset record pointing at the converted data file.",
    why: "Data without its test conditions is trivia. The link cell → test → dataset is what makes the numbers reusable by someone who wasn't in the lab.",
  },
  {
    stage: "Save & validate",
    verb: "ws.save()",
    code: `ws.save()`,
    produces: ".battinfo/records/** — canonical JSON records, schema-validated, with deterministic w3id.org IRIs minted from each record's identity.",
    why: "Validation runs before anything leaves your machine. Re-running the same save is a no-op — identical inputs always mint identical identifiers.",
  },
  {
    stage: "Publish",
    verb: "ws.publish()",
    code: `ws.publish(note="Cycling campaign, 2026")  # add zenodo=True for a DOI`,
    produces: "A citable archive (Zenodo DOI) and records staged for the Battery Genome registry, where curators review and index them.",
    why: "This is the payoff: a DOI reviewers can cite, machine-readable JSON-LD any tool can consume, and a record the whole field can find.",
  },
] as const;

// What publishing buys you — now, for your lab, for the field. Homepage cards.
export const payoffs = [
  {
    horizon: "For you, today",
    body: "A citable DOI for your dataset, validated records instead of folder chaos, and a provenance chain reviewers can actually check.",
  },
  {
    horizon: "For your lab",
    body: "Every cell, test, and file linked and findable when the student who made them has graduated. Re-running an ingest never duplicates records.",
  },
  {
    horizon: "For the field",
    body: "Your data joins the Battery Genome: EMMO-aligned, machine-readable records that models and meta-analyses can consume without asking you for a spreadsheet.",
  },
] as const;

// Project principles — the OBO Foundry move: state the governance commitments
// that make a standard dependable, not just functional.
export const principles = [
  {
    title: "Open & non-proprietary",
    body: "Schemas, mappings, and tooling are public and openly licensed. The normative semantics live in the community EMMO ontology, not in this project.",
  },
  {
    title: "Stable, resolvable identifiers",
    body: "Published entities get opaque, persistent IRIs under w3id.org/battinfo, governed by a written identifier policy — they don't break when the site changes.",
  },
  {
    title: "Versioned & reproducible",
    body: "Upstream ontologies are pinned; the transform is deterministic; validation policies are versioned so downstream systems can rely on them.",
  },
  {
    title: "Layered, not monolithic",
    body: "EMMO is the source of truth; BattINFO is the operational layer of schemas and tools. Each layer can evolve without rewriting the other.",
  },
] as const;
