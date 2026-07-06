// Central site configuration: identity, nav, external links.
// Keep all "where does X live" constants here so pages stay declarative.

export const site = {
  name: "BattINFO",
  tagline: "The semantic data layer for battery technology",
  description:
    "BattINFO makes battery data machine-readable and interoperable: a shared vocabulary, ready-to-use JSON Schemas, a Python library and CLI, and persistent identifiers that turn datasheets, specs, and test data into data any tool can read.",
  url: "https://battinfo.org",
  // The IRI namespace is resolved by w3id.org, NOT by this site.
  iriBase: "https://w3id.org/battinfo/",
  // Developer reference (Sphinx). This site owns "why/try"; the reference owns
  // "how/reference" — see docs/CONTENT-MODEL.md. TODO: point at
  // https://docs.battinfo.org once the Sphinx site is deployed; until then the
  // canonical reference is the docs/ tree on GitHub.
  reference: "https://github.com/BIG-MAP/BattINFO/tree/main/docs",
  github: "https://github.com/BIG-MAP/BattINFO",
  pypi: "https://pypi.org/project/battinfo/",
  genome: "https://www.battery-genome.org",
  ciBadge: "https://github.com/BIG-MAP/BattINFO/actions/workflows/ci.yml/badge.svg?branch=main",
  ciRuns: "https://github.com/BIG-MAP/BattINFO/actions/workflows/ci.yml",
  pypiBadge: "https://img.shields.io/pypi/v/battinfo?label=PyPI&color=0e7c86",
  // Zenodo concept DOI — set when the 0.8 release is archived (D.1); the proof
  // strip renders the badge only when non-empty.
  doi: "",
  emmo: "https://github.com/emmo-repo/domain-battery",
  emmoElectrochem: "https://github.com/emmo-repo/domain-electrochemistry",
  license: "Apache-2.0",
  // Pinned upstream ontology versions — keep in sync with battinfo.ttl.
  versions: {
    domainBattery: "0.18.7",
    domainElectrochemistry: "0.33.0",
    schema: "JSON Schema 2020-12",
  },
} as const;

// Publish first: the primary action a visitor with data should see.
export const primaryNav = [
  { label: "Publish", href: "/publish" },
  { label: "Validate", href: "/validate" },
  { label: "Convert", href: "/convert" },
  { label: "Examples", href: "/examples" },
  { label: "Why", href: "/federation" },
  { label: "Docs", href: "/docs" },
] as const;

// Standards this project builds on or aligns with — the "we did not invent our
// own world" signal that the best semantic standards lead with.
export const standards = [
  {
    name: "EMMO domain-battery",
    role: "Normative semantics",
    href: "https://github.com/emmo-repo/domain-battery",
  },
  {
    name: "JSON-LD 1.1",
    role: "Linked Data serialization",
    href: "https://www.w3.org/TR/json-ld11/",
  },
  {
    name: "JSON Schema 2020-12",
    role: "Structural contract",
    href: "https://json-schema.org/",
  },
  {
    name: "QUDT / EMMO units",
    role: "Quantities & units",
    href: "https://qudt.org/",
  },
  {
    name: "w3id.org",
    role: "Persistent identifiers",
    href: "https://w3id.org/",
  },
  {
    name: "schema.org",
    role: "Web-native vocabulary bridge",
    href: "https://schema.org/",
  },
] as const;

export const footerNav = [
  {
    heading: "Get started",
    links: [
      { label: "Publish your data", href: "/publish" },
      { label: "Documentation", href: "/docs" },
      { label: "Quickstart", href: "/docs#quickstart" },
      { label: "Examples", href: "/examples" },
    ],
  },
  {
    heading: "Tools",
    links: [
      { label: "Validate a record", href: "/validate" },
      { label: "Convert to JSON-LD", href: "/convert" },
    ],
  },
  {
    heading: "Reference",
    links: [
      { label: "Ontology (battinfo.ttl)", href: "/docs#ontology" },
      { label: "JSON Schemas", href: "/docs#schemas" },
      { label: "Identifier policy", href: "/docs#identifiers" },
    ],
  },
  {
    heading: "Project",
    links: [
      { label: "GitHub", href: site.github, external: true },
      { label: "PyPI", href: site.pypi, external: true },
      { label: "EMMO domain-battery", href: site.emmo, external: true },
    ],
  },
] as const;
