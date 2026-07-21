import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { Constellation } from "@/components/constellation";
import { ProofStrip } from "@/components/proof-strip";
import { SectionHeading } from "@/components/section-heading";
import { site, standards } from "@/lib/site";
import {
  audiences,
  features,
  pipeline,
  principles,
  provenanceChain,
  recordModel,
} from "@/lib/content";
import { installSnippet, publishJourneySnippet } from "@/lib/examples";

export default function HomePage() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-border bg-paper">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div>
              <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-surface px-3 py-1 text-xs font-medium text-brandtext">
                <span className="h-1.5 w-1.5 rounded-full bg-volt-500" />
                Open standard · Beta
              </span>
              <h1 className="mt-5 text-4xl font-bold tracking-tight text-ink sm:text-5xl">
                The language machines use to{" "}
                <span className="text-brandtext">understand batteries</span>
              </h1>
              <p className="mt-5 max-w-prose text-lg text-ink-muted">
                BattINFO builds on the open EMMO ontology — a shared, standardized
                vocabulary for materials and battery science — so battery data is
                machine-readable and reusable across tools and teams. It turns a
                folder of cycler exports into citable, findable records in about
                fifteen minutes.{" "}
                <a
                  href={`${site.reference}/pages/glossary.html`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-semibold text-brandtext hover:text-brandtext"
                >
                  New to the terms? The glossary.
                </a>
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="/publish"
                  className="rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-fg shadow-sm transition hover:opacity-90"
                >
                  Publish your data
                </Link>
                <Link
                  href="/validate"
                  className="rounded-lg border border-border bg-surface px-5 py-3 text-sm font-semibold text-ink transition hover:bg-tint"
                >
                  Validate a record
                </Link>
              </div>
              <div className="mt-8">
                <ProofStrip />
              </div>
            </div>

            <div className="lg:pl-6">
              <Constellation />
            </div>
          </div>
        </div>
      </section>

      {/* Standards strip, "we build on accepted foundations" */}
      <section className="border-b border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
          <p className="text-center text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Built on open, accepted standards
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-8 gap-y-4">
            {standards.map((s) => (
              <a
                key={s.name}
                href={s.href}
                target="_blank"
                rel="noreferrer"
                className="group text-center"
                title={s.role}
              >
                <span className="text-sm font-semibold text-ink transition group-hover:text-brandtext">
                  {s.name}
                </span>
                <span className="block text-[11px] text-ink-faint">{s.role}</span>
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* Quickstart, near the top, because it is the quickstart */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-2">
          <div>
            <SectionHeading
              kicker="Quickstart"
              title="From cycler files to a citable dataset."
            />
            <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
              This is the real recipe, the same one <code>ws.quickstart()</code>{" "}
              prints, kept in sync by the test suite.{" "}
              <Link href="/publish" className="font-semibold text-brandtext hover:text-brandtext">
                Every step explained →
              </Link>
            </p>
            <div className="mt-6">
              <CodeBlock label="install" code={installSnippet} />
            </div>
          </div>
          <div className="lg:pt-16">
            <CodeBlock label="the whole journey" code={publishJourneySnippet} />
          </div>
        </div>
      </section>

      {/* How it works, the four-verb pipeline */}
      <section className="border-t border-border mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          kicker="How it works"
          title="From datasheet to machine-readable Linked Data, in four steps."
        />
        <ol className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {pipeline.map((step, i) => (
            <li key={step.verb} className="relative">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 font-mono text-sm font-bold text-white">
                  {i + 1}
                </span>
                <h3 className="text-lg font-semibold text-ink">{step.verb}</h3>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {/* Features */}
      <section className="border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            kicker="What BattINFO does"
            title="Real semantics, without losing the data on the way."
          />
          <div className="mt-10 grid gap-6 sm:grid-cols-2">
            {features.map((f) => (
              <div key={f.title} className="prose-card">
                <h3 className="text-lg font-semibold text-ink">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-muted">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Record model */}
      <section className="border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            kicker="One coherent model"
            title="Linked record types with a shared provenance chain."
          />
          <p className="mt-4 font-mono text-sm text-brandtext">{provenanceChain}</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {recordModel.map((r) => (
              <div key={r.type} className="prose-card">
                <h3 className="font-mono text-sm font-semibold text-ink">{r.type}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">
                  {r.blurb}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-ink-muted">
            Each type has a canonical JSON Schema and an EMMO mapping.{" "}
            <Link href="/examples" className="font-semibold text-brandtext hover:text-brandtext">
              See a worked example →
            </Link>
          </p>
        </div>
      </section>

      {/* Who it's for */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading kicker="Who it's for" title="One model, two audiences." />
        <div className="mt-10 grid gap-6 lg:grid-cols-2">
          {audiences.map((a) => (
            <div key={a.who} className="prose-card flex flex-col">
              <h3 className="text-lg font-semibold text-ink">{a.who}</h3>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-ink-muted">{a.body}</p>
              <Link
                href={a.cta.href}
                className="mt-4 text-sm font-semibold text-brandtext hover:text-brandtext"
              >
                {a.cta.label} →
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Principles */}
      <section className="border-y border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading
            kicker="Principles"
            title="Built to be depended on."
          />
          <div className="mt-10 grid gap-6 sm:grid-cols-2">
            {principles.map((p) => (
              <div key={p.title} className="flex gap-4">
                <span className="mt-1 h-2 w-2 flex-none rounded-full bg-volt-500" />
                <div>
                  <h3 className="text-base font-semibold text-ink">{p.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-ink-muted">{p.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border bg-brand-950">
        <div className="mx-auto max-w-6xl px-4 py-16 text-center sm:px-6">
          <h2 className="text-2xl font-semibold tracking-tight text-white">Build on the battery genome.</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-brand-100">
            BattINFO is open infrastructure. Publish your data, validate a
            record in the browser, or read the docs.
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <Link href="/publish" className="rounded-lg bg-surface px-5 py-3 text-sm font-semibold text-brandtext transition hover:bg-tint">
              Publish your data
            </Link>
            <Link href="/docs" className="rounded-lg border border-white/30 px-5 py-3 text-sm font-semibold text-white transition hover:bg-surface/10">
              Read the docs
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
