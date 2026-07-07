import type { Metadata } from "next";
import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { site, standards } from "@/lib/site";
import { installSnippet, quickstartPython } from "@/lib/examples";

export const metadata: Metadata = {
  title: "Documentation",
  description: "Get started with BattINFO: install, author, validate, and publish battery metadata as Linked Data.",
};

const guides = [
  { n: "1", slug: "01-concepts", title: "Concepts", body: "The record model, IRIs, and the semantic layer." },
  { n: "2", slug: "02-first-cell-type", title: "Describing a cell", body: "Author and publish a cell spec, with a taste of material-level depth." },
  { n: "3", slug: "03-linked-records", title: "Linked records", body: "Cells, test specs, tests, and datasets with the workspace." },
  { n: "4", slug: "04-semantic-layer", title: "Semantic layer", body: "JSON-LD anatomy, EMMO type stacking, RDF and SPARQL." },
  { n: "5", slug: "05-descriptors", title: "Cell descriptors", body: "Research-grade composition: materials, BOMs, electrodes, electrolyte." },
  { n: "6", slug: "06-publish-your-data", title: "Publish your first dataset", body: "Raw cycler export → validated records → DOI, in five stages." },
];

const reference = [
  { id: "schemas", title: "JSON Schemas", body: "Draft 2020-12 schemas for every record type — the canonical contract.", href: `${site.github}/tree/main/assets/schemas` },
  { id: "ontology", title: "Ontology (battinfo.ttl)", body: "OWL application ontology importing pinned EMMO domain-battery + domain-electrochemistry.", href: `${site.github}/blob/main/battinfo.ttl` },
  { id: "identifiers", title: "Identifier policy", body: "How w3id.org/battinfo IRIs are minted, governed, and kept stable.", href: `${site.github}/blob/main/IDENTIFIER_POLICY.md` },
  { id: "mappings", title: "Property & unit mappings", body: "Curated property→EMMO-IRI and unit→EMMO/QUDT-IRI tables driving the JSON-LD transform.", href: `${site.github}/tree/main/assets/mappings` },
];

function SectionHeading({ id, kicker, title }: { id?: string; kicker: string; title: string }) {
  return (
    <div id={id} className="scroll-mt-24">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-brand-600">{kicker}</h2>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-ink">{title}</p>
    </div>
  );
}

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <header className="max-w-prose">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Documentation</h1>
        <p className="mt-4 text-lg text-ink-muted">
          BattINFO is the implementation layer for the EMMO domain-battery
          ontology — JSON Schemas, a Python library, a CLI, and curated mapping
          tables for authoring, validating, and publishing battery metadata as
          Linked Data.
        </p>
      </header>

      {/* Handoff to the developer reference. This page is the user-facing hub;
          the exhaustive API/CLI/schema reference lives in the Sphinx docs. */}
      <a
        href={site.reference}
        target="_blank"
        rel="noreferrer"
        className="mt-8 flex flex-col gap-1 rounded-2xl border border-brand-200 bg-brand-50/50 p-6 transition hover:border-brand-300 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h2 className="text-base font-semibold text-ink">
            Building with BattINFO? Open the developer reference →
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            Full Python API, CLI commands, JSON Schemas, the validation contract,
            and executable notebook tutorials.
          </p>
        </div>
        <span className="mt-2 flex-none rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white sm:mt-0">
          Developer reference
        </span>
      </a>

      {/* Quickstart */}
      <section id="quickstart" className="mt-16 scroll-mt-24">
        <SectionHeading kicker="Quickstart" title="Install and publish a record" />
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <CodeBlock label="install" code={installSnippet} />
          <CodeBlock label="python" code={quickstartPython} />
        </div>
        <p className="mt-4 text-sm text-ink-muted">
          Full notebook walkthroughs ship in the repo under{" "}
          <a href={`${site.reference}/guides`} className="text-brand-600 underline" target="_blank" rel="noreferrer">
            docs/guides
          </a>
          .
        </p>
      </section>

      {/* Guides */}
      <section className="mt-20">
        <SectionHeading kicker="Tutorials" title="Learn the model step by step" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {guides.map((g) => (
            <a
              key={g.n}
              href={`${site.reference}/guides/${g.slug}.ipynb`}
              target="_blank"
              rel="noreferrer"
              className="prose-card transition hover:border-brand-300 hover:shadow-md"
            >
              <span className="font-mono text-xs font-semibold text-brand-500">{g.n}</span>
              <h3 className="mt-1 text-lg font-semibold text-ink">{g.title}</h3>
              <p className="mt-1 text-sm text-ink-muted">{g.body}</p>
            </a>
          ))}
        </div>
      </section>

      {/* Reference */}
      <section className="mt-20">
        <SectionHeading kicker="Reference" title="Schemas, ontology, and policy" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {reference.map((r) => (
            <a
              key={r.id}
              id={r.id}
              href={r.href}
              target="_blank"
              rel="noreferrer"
              className="prose-card scroll-mt-24 transition hover:border-brand-300 hover:shadow-md"
            >
              <h3 className="text-lg font-semibold text-ink">{r.title}</h3>
              <p className="mt-1 text-sm text-ink-muted">{r.body}</p>
            </a>
          ))}
        </div>
      </section>

      {/* Tools */}
      <section className="mt-20">
        <SectionHeading kicker="Tools" title="Validate and convert in the browser" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <Link href="/validate" className="prose-card transition hover:border-brand-300 hover:shadow-md">
            <h3 className="text-lg font-semibold text-ink">Validate a record</h3>
            <p className="mt-1 text-sm text-ink-muted">
              An instant structural pre-check, mirroring the package&rsquo;s issue
              model — with a one-line command to reproduce the canonical verdict.
            </p>
          </Link>
          <Link href="/convert" className="prose-card transition hover:border-brand-300 hover:shadow-md">
            <h3 className="text-lg font-semibold text-ink">Convert to JSON-LD</h3>
            <p className="mt-1 text-sm text-ink-muted">
              What ws.convert() supports for every cycler format, and how the
              converted tables become linked records.
            </p>
          </Link>
        </div>

      </section>

      {/* Standards alignment */}
      <section className="mt-20">
        <SectionHeading kicker="Standards" title="What BattINFO builds on" />
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {standards.map((s) => (
            <a
              key={s.name}
              href={s.href}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between rounded-lg border border-border bg-white px-4 py-3 transition hover:border-brand-300"
            >
              <span className="text-sm font-semibold text-ink">{s.name}</span>
              <span className="text-xs text-ink-faint">{s.role}</span>
            </a>
          ))}
        </div>
      </section>

      {/* Relationship to EMMO */}
      <section className="mt-20 rounded-2xl border border-border bg-surface p-8">
        <SectionHeading kicker="Scope" title="BattINFO and the ontology" />
        <div className="mt-4 max-w-prose space-y-3 text-sm leading-relaxed text-ink-muted">
          <p>
            The normative semantics live in{" "}
            <a href={site.emmo} className="text-brand-600 underline" target="_blank" rel="noreferrer">
              EMMO domain-battery
            </a>
            . BattINFO is the non-normative, operational layer: schemas,
            mappings, and tooling. It does not host or modify the upstream
            ontology.
          </p>
          <p>
            Identifiers minted by BattINFO resolve through the community PURL
            service at <span className="font-mono">w3id.org/battinfo</span> — this
            website is documentation, not the resolver.
          </p>
        </div>
        <div className="mt-6">
          <Link href="/examples" className="text-sm font-semibold text-brand-600 hover:text-brand-700">
            See a worked example →
          </Link>
        </div>
      </section>
    </div>
  );
}
