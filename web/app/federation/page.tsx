import type { Metadata } from "next";
import Link from "next/link";
import { SectionHeading } from "@/components/section-heading";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Data federation",
  description:
    "Data federation keeps battery data where it lives and makes it interoperable through a shared semantic layer. BattINFO is that backbone; Battery Genome is it in practice.",
};

// The three things every record needs to share for federation to work, the
// pillars BattINFO standardises. Kept here so the page stays declarative.
const pillars = [
  {
    title: "Shared meaning",
    body: "Every property and unit maps to an EMMO domain-battery IRI, so “nominal capacity” means the same thing in a datasheet, a lab export, and a regulator's database, no per-source glossary required.",
  },
  {
    title: "Shared identifiers",
    body: "Cells, specs, tests, and datasets get persistent w3id.org/battinfo IRIs. A record in one repository can point at a record in another, and the link still resolves years later.",
  },
  {
    title: "Shared serialization",
    body: "Records publish as JSON-LD aligned to one context. Independently authored documents merge into a single RDF graph you can query, without anyone agreeing on a database schema first.",
  },
];

const centralVsFederated = [
  {
    label: "Centralized",
    body: "Copy everyone's data into one database under one schema. Breaks on ownership, scale, privacy, and the next format change. Whoever holds the database holds the power.",
    tone: "muted",
  },
  {
    label: "Federated",
    body: "Data stays with its owner. A shared vocabulary, shared identifiers, and a shared serialization let independent sources interoperate and link, queried as if they were one graph.",
    tone: "brand",
  },
];

export default function FederationPage() {
  return (
    <>
      {/* Hero */}
      <section className="border-b border-border bg-gradient-to-b from-brand-50/60 to-white">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-24">
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-surface px-3 py-1 text-xs font-medium text-brand-700">
            <span className="h-1.5 w-1.5 rounded-full bg-volt-500" />
            Concept
          </span>
          <h1 className="mt-5 max-w-3xl text-4xl font-bold tracking-tight text-ink sm:text-5xl">
            Data federation, and why{" "}
            <span className="text-brand-600">battery data needs it</span>
          </h1>
          <p className="mt-5 max-w-prose text-lg text-ink-muted">
            Battery knowledge is scattered across datasheets, lab notebooks,
            cycler exports, suppliers, and regulators. Federation makes those
            sources interoperable without forcing them into one database.
            BattINFO is the backbone that makes it possible, and{" "}
            <span className="font-semibold text-ink">Battery Genome</span> is
            that backbone in practice.
          </p>
        </div>
      </section>

      {/* What it is, centralize vs federate */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          kicker="What it is"
          title="Don't move the data. Agree on how to describe and address it."
        />
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
          Data federation is an architecture for making many independent
          datasets behave like one. Instead of centralizing everything into a
          single store, federation keeps each dataset where it lives and adds a
          thin shared layer, a common vocabulary, persistent identifiers, and
          a common serialization, so the pieces can be linked and queried
          together.
        </p>
        <div className="mt-10 grid gap-6 sm:grid-cols-2">
          {centralVsFederated.map((c) => (
            <div
              key={c.label}
              className={`prose-card ${
                c.tone === "brand" ? "border-brand-200 bg-brand-50/40" : ""
              }`}
            >
              <h3
                className={`text-sm font-semibold uppercase tracking-wider ${
                  c.tone === "brand" ? "text-brand-700" : "text-ink-faint"
                }`}
              >
                {c.label}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                {c.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* BattINFO as the backbone */}
      <section className="border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            kicker="The backbone"
            title="BattINFO supplies the three things federation depends on."
          />
          <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
            Federation only works if independent parties share a small,
            well-governed core. BattINFO standardises exactly that core, and
            nothing more, so data owners stay in control of everything else.
          </p>
          <div className="mt-10 grid gap-6 lg:grid-cols-3">
            {pillars.map((p, i) => (
              <div key={p.title} className="prose-card">
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 font-mono text-sm font-bold text-white">
                    {i + 1}
                  </span>
                  <h3 className="text-lg font-semibold text-ink">{p.title}</h3>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                  {p.body}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-8 max-w-prose text-sm leading-relaxed text-ink-muted">
            A publication backend, the{" "}
            <span className="font-semibold text-ink">BattINFO registry</span>,
            mints those canonical identifiers and renders public, resolvable
            artifacts, so a record published by one group is addressable and
            linkable by everyone else.{" "}
            <Link
              href="/docs#identifiers"
              className="font-semibold text-brand-600 hover:text-brand-700"
            >
              How identifiers work →
            </Link>
          </p>
        </div>
      </section>

      {/* Battery Genome in practice */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          kicker="In practice"
          title="Battery Genome: federation, running."
        />
        <div className="mt-8 grid gap-10 lg:grid-cols-2">
          <div>
            <p className="text-sm leading-relaxed text-ink-muted">
              Battery Genome is a working instance of this idea. It brings
              together cell specifications, instances, test protocols, and
              cycling datasets contributed from many sources, manufacturers,
              research labs, and public collections, and binds them with
              BattINFO.
            </p>
            <p className="mt-4 text-sm leading-relaxed text-ink-muted">
              Nothing is forced into a single proprietary schema. Each
              contribution is described with the shared vocabulary, gets a
              persistent IRI, and is published as Linked Data. The result is a
              growing, queryable graph of battery knowledge that no single
              organization owns, the &ldquo;genome&rdquo; assembled from
              independently held parts.
            </p>
          </div>
          <ol className="space-y-4">
            {[
              "A lab describes a cell and its tests with BattINFO, in plain JSON.",
              "Publishing mints persistent IRIs and emits EMMO-aligned JSON-LD.",
              "The registry renders resolvable public artifacts for each resource.",
              "Records from different contributors link by IRI into one graph.",
              "Battery Genome queries across all of it, as if it were one dataset.",
            ].map((step, i) => (
              <li key={i} className="flex gap-4">
                <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-brand-600 font-mono text-xs font-bold text-white">
                  {i + 1}
                </span>
                <p className="pt-0.5 text-sm leading-relaxed text-ink-muted">
                  {step}
                </p>
              </li>
            ))}
          </ol>
        </div>
        <p className="mt-10 max-w-prose text-sm leading-relaxed text-ink-muted">
          The same machinery you use to publish one record is what makes the
          whole federation cohere. Build on the shared backbone and your data is
          interoperable by construction, not by a future migration.
        </p>
      </section>

      {/* CTA */}
      <section className="border-t border-border bg-brand-950">
        <div className="mx-auto max-w-6xl px-4 py-16 text-center sm:px-6">
          <h2 className="text-2xl font-semibold tracking-tight text-white">
            Join the federation.
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-brand-100">
            Describe your battery data once with BattINFO and it links into the
            wider graph. Start with the docs, or convert a record in the browser.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <Link
              href="/docs"
              className="rounded-lg bg-surface px-5 py-3 text-sm font-semibold text-brand-700 transition hover:bg-brand-50"
            >
              Read the docs
            </Link>
            <a
              href={site.github}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-white/30 px-5 py-3 text-sm font-semibold text-white transition hover:bg-surface/10"
            >
              View on GitHub
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
