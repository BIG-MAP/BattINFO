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
  // "how/reference" — see docs/CONTENT-MODEL.md. The rendered Sphinx site is
  // deployed by CI (docs.yml) on every push to main; /dev is the tip-of-main
  // build. Versioned paths appear alongside it at release tags. A future
  // docs.battinfo.org alias would change only this constant.
  reference: "https://big-map.github.io/BattINFO/dev",
  github: "https://github.com/BIG-MAP/BattINFO",
  pypi: "https://pypi.org/project/battinfo/",
  // The package is not on PyPI until the 0.8 release train publishes it
  // (user decision: release LAST, once everything is in shape). The badge,
  // footer link, and install copy stay hidden until this flips.
  pypiLive: false,
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

// Every primary item is either a browser tool you USE (Playground, Validate) or
// a guide/reference you READ (Publish, About, Docs) — split by user intent, not
// by mechanism. Convert folds into Publish (it is Publish's first stage) and
// Examples into the tools' presets plus the docs gallery; both stay reachable
// (footer, deep links, cross-links), just not as top-level peers.
export const primaryNav = [
  { label: "Playground", href: "/create" },
  { label: "Validate", href: "/validate" },
  { label: "Publish", href: "/publish" },
  { label: "About", href: "/about" },
  { label: "Docs", href: "/docs" },
] as const;

// Standards this project builds on or aligns with — the "we did not invent our
// own world" signal that the best semantic standards lead with.
export const standards = [
  {
    name: "EMMO",
    role: "Normative semantics",
    href: "https://github.com/emmo-repo/domain-battery",
  },
  {
    name: "JSON-LD",
    role: "Linked Data serialization",
    href: "https://www.w3.org/TR/json-ld11/",
  },
  {
    name: "JSON Schema",
    role: "Structural contract",
    href: "https://json-schema.org/",
  },
  {
    name: "Pydantic",
    role: "Typed authoring models",
    href: "https://docs.pydantic.dev/",
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
      { label: "Convert cycler data", href: "/convert" },
      { label: "Quickstart", href: "/docs#quickstart" },
      { label: "Examples", href: "/examples" },
    ],
  },
  {
    heading: "Tools",
    links: [
      { label: "Playground", href: "/create" },
      { label: "Validate a record", href: "/validate" },
      { label: "Properties & units", href: "/properties" },
      { label: "About BattINFO", href: "/about" },
    ],
  },
  {
    heading: "Reference",
    links: [
      { label: "Glossary", href: `${site.reference}/pages/glossary.html`, external: true },
      { label: "Ontology (battinfo.ttl)", href: "/docs#ontology" },
      { label: "JSON Schemas", href: "/docs#schemas" },
      { label: "Identifier policy", href: "/docs#identifiers" },
    ],
  },
  {
    heading: "Project",
    links: [
      { label: "GitHub", href: site.github, external: true },
      { label: "EMMO domain-battery", href: site.emmo, external: true },
    ],
  },
] as const;
